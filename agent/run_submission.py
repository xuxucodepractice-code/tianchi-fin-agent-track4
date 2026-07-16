"""提交线 CLI 入口（Task 6：单题/领域批量链路）。

用法：
    python -m agent.run_submission --qid ins_a_007            # 默认 dry-run
    python -m agent.run_submission --qid ins_a_007 --dry-run  # 显式 dry-run
    python -m agent.run_submission --qid ins_a_007 --use-qwen # 正式调用 Qwen
    python -m agent.run_submission --domain insurance --limit 2 --dry-run
    python -m agent.run_submission --domain insurance --use-qwen
    python -m agent.run_submission --selection-file <frozen.json> --use-qwen --output-dir outputs/experiments/<run>

数据流：
    load questions (by qid/domain/all)
        -> retrieve_for_question（doc_ids 限定，逐选项 evidence，Task 4）
        -> reason_question_with_qwen / reason_question_dry_run（Task 5）
        -> normalize_answer（题型格式校验）
        -> answer.csv + evidence.json + run_manifest.json
        -> processed_data/reasoning_samples/{qid}.json

!!! dry-run（mode=dry_run_mock）不调用 Qwen，答案是 fallback 占位，
不是正式推理结果，不能用于正式提交。正式推理必须 --use-qwen。
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.load_questions import find_question_by_qid, load_all_questions, load_questions_by_domain
from agent.normalize_answer import validate_answer_format
from agent.output_writer import (
    write_answer_csv,
    write_evidence_json,
    write_run_manifest,
)
from agent.paths import (
    DRY_RUN_OUTPUTS_DIR,
    EXPERIMENT_OUTPUTS_DIR,
    REPO_ROOT,
    SUBMISSION_DIR,
    VERSIONED_REASONING_SAMPLES_DIR,
    bundle_paths,
    ensure_output_dirs,
)
from agent.qwen_client import MissingApiKeyError, QwenClient, resolve_api_key
from agent.reason_qwen import (
    MODE_DRY_RUN,
    MODE_QWEN,
    PIPELINE_VERSION as CURRENT_PIPELINE_VERSION,
    REASONING_SAMPLES_DIR,
    MCQ_GLOBAL_METHOD,
    parse_mcq_global_comparison_response,
    reason_mcq_question_with_qwen,
    reason_question_dry_run,
    reason_tf_question_with_qwen,
    reason_question_with_qwen,
    save_reasoning_sample,
)
from agent.retrieve import (
    B_MODE_DOC_TOP_K,
    load_chunks,
    retrieve_for_question,
    retrieve_for_tf_question,
)
from agent.trace_gate import (
    AgentTraceRecorder,
    BlindDataAccessError,
    assert_candidate_experiment_policy,
    blind_data_guard,
    default_candidate_forbidden_roots,
    display_path,
    input_artifact_snapshot,
    load_frozen_selection,
    sha256_file,
    validate_trace_directory,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _compact_retrieval(retrieval: dict[str, Any]) -> dict[str, Any]:
    if "tf" in retrieval:
        return {"tf": retrieval["tf"]}
    return {
        key: {"option_text": opt["option_text"], "evidence": opt["evidence"]}
        for key, opt in retrieval["options"].items()
    }


def solve_question(
    question: dict[str, Any],
    chunks: list[dict[str, Any]],
    use_qwen: bool,
    top_k: int = 5,
    client: QwenClient | None = None,
) -> dict[str, Any]:
    """单题全链路：检索 -> 判断 -> 答案。返回含 retrieval 的完整结果记录。"""
    if question.get("answer_format") == "tf" and use_qwen:
        retrieval = retrieve_for_tf_question(question, chunks, top_k=top_k)
        result = reason_tf_question_with_qwen(question, retrieval, client=client)
        result["retrieval"] = _compact_retrieval(retrieval)
        result["evidence"] = []
        return result
    retrieval = retrieve_for_question(question, chunks, top_k=top_k)
    if use_qwen:
        if question.get("answer_format") == "mcq":
            result = reason_mcq_question_with_qwen(
                question, retrieval, client=client
            )
        else:
            result = reason_question_with_qwen(question, retrieval, client=client)
    else:
        result = reason_question_dry_run(question, retrieval)
    # evidence.json 需要保留检索证据（去掉冗余 query_terms 以控制体积）
    result["retrieval"] = _compact_retrieval(retrieval)
    result["evidence"] = []  # 兼容 Task 1 字段：题级扁平证据列表（逐项证据在 retrieval 里）
    return result


def is_reusable_qwen_result(
    result: dict[str, Any],
    expected_qid: str | None = None,
    expected_pipeline_version: str = CURRENT_PIPELINE_VERSION,
    allow_pipeline_mismatch: bool = False,
) -> tuple[bool, str]:
    """判断 reasoning sample 是否可用于续跑复用。"""
    if expected_qid is not None and str(result.get("qid", "")) != expected_qid:
        return False, f"qid mismatch: expected {expected_qid}, got {result.get('qid')!r}"
    if result.get("mode") != MODE_QWEN:
        return False, f"mode is {result.get('mode')!r}, not qwen"
    pipeline_version = str(result.get("pipeline_version") or "v0")
    if pipeline_version != expected_pipeline_version and not allow_pipeline_mismatch:
        return False, (
            f"pipeline_version is {pipeline_version!r}, "
            f"not {expected_pipeline_version!r}"
        )
    if int(result.get("prompt_tokens") or 0) <= 0 or int(result.get("total_tokens") or 0) <= 0:
        return False, "prompt_tokens/total_tokens must be > 0"
    if int(result.get("completion_tokens") or 0) < 0:
        return False, "completion_tokens must be >= 0"
    option_judgments = result.get("option_judgments")
    if not isinstance(option_judgments, dict) or not option_judgments:
        return False, "option_judgments missing"
    if result.get("answer_format") == "tf" and isinstance(result.get("tf_judgment"), dict):
        tf_judgment = result["tf_judgment"]
        if tf_judgment.get("verdict") == "error" or bool(tf_judgment.get("error")):
            return False, "tf_judgment error"
        if int(tf_judgment.get("prompt_tokens") or 0) <= 0 or int(tf_judgment.get("total_tokens") or 0) <= 0:
            return False, "tf_judgment prompt_tokens/total_tokens must be > 0"
        bad_options = [
            key
            for key, judgment in option_judgments.items()
            if not isinstance(judgment, dict)
            or judgment.get("judgment") == "error"
            or bool(judgment.get("error"))
        ]
    else:
        bad_options = [
            key
            for key, judgment in option_judgments.items()
            if not isinstance(judgment, dict)
            or judgment.get("judgment") == "error"
            or bool(judgment.get("error"))
            or int(judgment.get("prompt_tokens") or 0) <= 0
            or int(judgment.get("total_tokens") or 0) <= 0
        ]
    if bad_options:
        return False, f"bad option judgments: {','.join(sorted(map(str, bad_options)))}"
    if result.get("answer_format") == "mcq":
        comparison = result.get("mcq_comparison")
        derivation = result.get("answer_derivation")
        options = result.get("options")
        if not isinstance(options, dict) or sorted(options) != ["A", "B", "C", "D"]:
            return False, "v2s2 mcq options must be exactly A/B/C/D"
        if sorted(option_judgments) != ["A", "B", "C", "D"]:
            return False, "v2s2 mcq reference judgments must cover A/B/C/D"
        if not isinstance(comparison, dict):
            return False, "mcq_comparison missing"
        if comparison.get("error") or str(comparison.get("answer", "")) not in {
            "A",
            "B",
            "C",
            "D",
        }:
            return False, "mcq_comparison invalid or errored"
        parsed_comparison, comparison_error = parse_mcq_global_comparison_response(
            json.dumps(
                {
                    key: comparison.get(key)
                    for key in (
                        "answer",
                        "eliminated",
                        "calculations",
                        "confidence",
                        "rationale",
                    )
                },
                ensure_ascii=False,
            ),
            ["A", "B", "C", "D"],
        )
        if comparison_error or parsed_comparison["answer"] != result.get("answer"):
            return False, "mcq_comparison schema or answer is invalid"
        if (
            int(comparison.get("prompt_tokens") or 0) <= 0
            or int(comparison.get("total_tokens") or 0) <= 0
        ):
            return False, "mcq_comparison prompt_tokens/total_tokens must be > 0"
        if not isinstance(derivation, dict) or derivation.get("method") != MCQ_GLOBAL_METHOD:
            return False, "mcq global answer_derivation missing"
        if derivation.get("fallback_used") is not False:
            return False, "mcq global derivation used fallback"
        if str(derivation.get("input_choice", "")) != str(result.get("answer", "")):
            return False, "mcq comparison choice differs from final answer"
        component_totals = {
            field: sum(int(item.get(field) or 0) for item in option_judgments.values())
            + int(comparison.get(field) or 0)
            for field in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        if any(
            component_totals[field] != int(result.get(field) or 0)
            for field in component_totals
        ):
            return False, "mcq component token totals differ from result"
    try:
        validate_answer_format(
            str(result.get("answer", "")),
            str(result.get("answer_format", "")),
            result.get("options", {}) if isinstance(result.get("options"), dict) else {},
        )
    except ValueError as exc:
        return False, f"invalid answer format: {exc}"
    return True, "ok"


def _load_reasoning_sample(
    qid: str, reasoning_samples_dir: Path | None = None
) -> tuple[dict[str, Any] | None, str]:
    cache_dir = reasoning_samples_dir or REASONING_SAMPLES_DIR
    path = cache_dir / f"{qid}.json"
    if not path.exists():
        return None, "missing"
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"unreadable: {exc}"
    if not isinstance(data, dict):
        return None, "not a JSON object"
    return data, "loaded"


def _attach_retrieval_to_cached_result(
    cached: dict[str, Any],
    question: dict[str, Any],
    chunks: list[dict[str, Any]],
    top_k: int,
) -> dict[str, Any]:
    if question.get("answer_format") == "tf" and isinstance(cached.get("tf_judgment"), dict):
        retrieval = retrieve_for_tf_question(question, chunks, top_k=top_k)
    else:
        retrieval = retrieve_for_question(question, chunks, top_k=top_k)
    result = dict(cached)
    result.update(
        {
            "domain": question.get("domain", result.get("domain", "")),
            "answer_format": question.get("answer_format", result.get("answer_format", "")),
            "question": question.get("question", result.get("question", "")),
            "options": question.get("options", result.get("options", {})),
            "doc_ids": question.get("doc_ids", result.get("doc_ids", [])),
            "retrieval": _compact_retrieval(retrieval),
            "evidence": [],
            "_reused_from_cache": True,
            "_reused_pipeline_version": str(cached.get("pipeline_version") or "v0"),
        }
    )
    return result


def _load_rerun_qids(path: str | None) -> set[str] | None:
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    if not raw:
        return set()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return {str(item).strip() for item in parsed if str(item).strip()}
    return {
        item.strip()
        for line in raw.splitlines()
        for item in line.split(",")
        if item.strip() and not item.strip().startswith("#")
    }


def run_questions(
    questions: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    use_qwen: bool,
    top_k: int,
    client: QwenClient | None = None,
    resume: bool = False,
    rerun_qids: set[str] | None = None,
    reasoning_samples_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """批量运行题目。单题失败记录后继续处理后续题目。"""
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for index, question in enumerate(questions, start=1):
        qid = str(question.get("qid", ""))
        try:
            if resume and use_qwen:
                if rerun_qids is not None and qid in rerun_qids:
                    print(f"[rerun] {qid}: forced by --rerun-qids")
                    result = solve_question(question, chunks, use_qwen, top_k=top_k, client=client)
                    results.append(result)
                    save_reasoning_sample(
                        {k: v for k, v in result.items() if k != "retrieval"},
                        (reasoning_samples_dir or REASONING_SAMPLES_DIR) / f"{qid}.json",
                    )
                    judgments = {k: v["judgment"] for k, v in result["option_judgments"].items()}
                    print(
                        f"[result] {index}/{len(questions)} qid={result['qid']} answer={result['answer']} "
                        f"low_confidence={result['low_confidence']} judgments={judgments} "
                        f"tokens={result['total_tokens']}"
                    )
                    for warning in result["warnings"]:
                        print(f"[warn] {qid}: {warning}")
                    continue
                cached, load_status = _load_reasoning_sample(qid, reasoning_samples_dir)
                if cached is not None:
                    reusable, reason = is_reusable_qwen_result(
                        cached,
                        expected_qid=qid,
                        allow_pipeline_mismatch=rerun_qids is not None,
                    )
                    if reusable:
                        result = _attach_retrieval_to_cached_result(cached, question, chunks, top_k)
                        results.append(result)
                        judgments = {
                            k: v["judgment"] for k, v in result["option_judgments"].items()
                        }
                        print(
                            f"[reuse] {index}/{len(questions)} qid={result['qid']} "
                            f"answer={result['answer']} low_confidence={result['low_confidence']} "
                            f"judgments={judgments} tokens={result['total_tokens']}"
                        )
                        continue
                    print(f"[rerun] {qid}: cached sample not reusable ({reason})")
                else:
                    print(f"[rerun] {qid}: cached sample {load_status}")
            result = solve_question(question, chunks, use_qwen, top_k=top_k, client=client)
            results.append(result)
            save_reasoning_sample(
                {k: v for k, v in result.items() if k != "retrieval"},
                (reasoning_samples_dir or REASONING_SAMPLES_DIR) / f"{qid}.json",
            )
            judgments = {k: v["judgment"] for k, v in result["option_judgments"].items()}
            print(
                f"[result] {index}/{len(questions)} qid={result['qid']} answer={result['answer']} "
                f"low_confidence={result['low_confidence']} judgments={judgments} "
                f"tokens={result['total_tokens']}"
            )
            for warning in result["warnings"]:
                print(f"[warn] {qid}: {warning}")
        except Exception as exc:
            failures.append({"qid": qid, "error": str(exc)})
            print(f"[error] {index}/{len(questions)} qid={qid}: {exc}", file=sys.stderr)
    return results, failures


def _judgment_distribution(results: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"support": 0, "refute": 0, "insufficient": 0, "error": 0}
    for result in results:
        for judgment in result.get("option_judgments", {}).values():
            value = str(judgment.get("judgment", "error"))
            counts[value] = counts.get(value, 0) + 1
    return counts


def _build_manifest(
    *,
    run_started_at: str,
    mode: str,
    requested_scope: str,
    qids: list[str],
    results: list[dict[str, Any]],
    failures: list[dict[str, str]],
    resume: bool = False,
    rerun_qids: set[str] | None = None,
    output_paths: tuple[Path, Path, Path] | None = None,
    model: str = "",
    experiment_id: str = "",
    official_output: bool = False,
    hide_doc_ids: bool = False,
) -> dict[str, Any]:
    low_confidence_qids = [r["qid"] for r in results if r.get("low_confidence")]
    total_prompt = sum(r["prompt_tokens"] for r in results)
    total_completion = sum(r["completion_tokens"] for r in results)
    total_tokens = sum(r["total_tokens"] for r in results)
    reused_qids = [r["qid"] for r in results if r.get("_reused_from_cache")]
    reused_pipeline_versions: dict[str, int] = {}
    for result in results:
        if not result.get("_reused_from_cache"):
            continue
        version = str(result.get("_reused_pipeline_version") or result.get("pipeline_version") or "v0")
        reused_pipeline_versions[version] = reused_pipeline_versions.get(version, 0) + 1
    answer_path, evidence_path, manifest_path = output_paths or bundle_paths(SUBMISSION_DIR)
    run_id = f"{CURRENT_PIPELINE_VERSION}:{run_started_at}"
    return {
        "run_started_at": run_started_at,
        "run_finished_at": _now_iso(),
        "mode": mode,
        "pipeline_version": CURRENT_PIPELINE_VERSION,
        "run_id": run_id,
        "experiment_id": experiment_id,
        "model": model,
        "submission_scope": "official_group_a" if official_output else "experiment",
        "document_selection_mode": (
            f"card_retrieval_k{B_MODE_DOC_TOP_K}" if hide_doc_ids else "provided_doc_ids"
        ),
        "hide_doc_ids_simulation": hide_doc_ids,
        "qid": qids[0] if len(qids) == 1 else None,
        "qids": qids,
        "requested_scope": requested_scope,
        "output_paths": {
            "answer_csv": _display_path(answer_path),
            "evidence_json": _display_path(evidence_path),
            "run_manifest_json": _display_path(manifest_path),
        },
        "success_count": len(results),
        "failure_count": len(failures),
        "failures": failures,
        "resume": resume,
        "rerun_qids": sorted(rerun_qids or []),
        "reused_from_cache_count": len(reused_qids),
        "reused_from_cache_qids": reused_qids,
        "reused_pipeline_versions": reused_pipeline_versions,
        "low_confidence_count": len(low_confidence_qids),
        "low_confidence_qids": low_confidence_qids,
        "judgment_distribution": _judgment_distribution(results),
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_tokens,
        "average_total_tokens": round(total_tokens / len(results), 2) if results else 0,
    }


def _select_questions(args: argparse.Namespace) -> tuple[list[dict[str, Any]], str]:
    if args.qid:
        question = find_question_by_qid(args.qid)
        return [question], f"single_question:{args.qid}"
    if args.domain:
        questions = load_questions_by_domain(args.domain)
        if args.limit is not None:
            questions = questions[: args.limit]
            scope = f"domain:{args.domain} limit={args.limit}"
        else:
            scope = f"domain:{args.domain}"
        return questions, scope
    if args.all:
        questions = load_all_questions()
        if args.limit is not None:
            questions = questions[: args.limit]
            scope = f"all limit={args.limit}"
        else:
            scope = "all"
        return questions, scope
    if getattr(args, "selection_file", None):
        selection_path = Path(args.selection_file).expanduser().resolve()
        payload = load_frozen_selection(selection_path)
        qids = payload["qids"]
        questions_by_qid = {str(item["qid"]): item for item in load_all_questions()}
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_qid in qids:
            qid = str(raw_qid)
            if qid in seen:
                raise ValueError(f"duplicate qid in selection: {qid}")
            if qid not in questions_by_qid:
                raise ValueError(f"unknown qid in selection: {qid}")
            seen.add(qid)
            selected.append(questions_by_qid[qid])
        return selected, f"frozen_selection:{payload.get('selection_id', selection_path.name)}"
    raise ValueError("必须指定 --qid、--domain、--all 或 --selection-file")


def run_scope(args: argparse.Namespace) -> int:
    run_started_at = _now_iso()
    mode = MODE_QWEN if args.use_qwen else MODE_DRY_RUN
    resume = bool(getattr(args, "resume", False))
    explicit_output = getattr(args, "output_dir", None)
    official_output = bool(getattr(args, "official_output", False))
    hide_doc_ids = bool(getattr(args, "hide_doc_ids", False))
    experiment_id = str(getattr(args, "experiment_id", "") or CURRENT_PIPELINE_VERSION)
    if official_output and not args.use_qwen:
        print("[error] --official-output requires --use-qwen", file=sys.stderr)
        return 1
    if official_output:
        print(
            "[error] direct traced inference into submission/ is disabled; "
            "promote a validated frozen candidate instead",
            file=sys.stderr,
        )
        return 1
    if args.use_qwen:
        try:
            resolve_api_key()
        except MissingApiKeyError as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 1
    if official_output and (not bool(getattr(args, "all", False)) or getattr(args, "limit", None) is not None):
        print("[error] --official-output requires an unbounded --all run", file=sys.stderr)
        return 1
    if official_output and not getattr(args, "experiment_id", None):
        print("[error] --official-output requires --experiment-id for lineage", file=sys.stderr)
        return 1
    if official_output and explicit_output:
        print("[error] --official-output and --output-dir are mutually exclusive", file=sys.stderr)
        return 1
    if official_output and hide_doc_ids:
        print("[error] --hide-doc-ids is an offline simulation and cannot write --official-output", file=sys.stderr)
        return 1
    if official_output:
        output_dir = SUBMISSION_DIR
    elif explicit_output:
        raw_output = Path(explicit_output).expanduser()
        output_dir = raw_output if raw_output.is_absolute() else REPO_ROOT / raw_output
    elif args.use_qwen:
        output_dir = EXPERIMENT_OUTPUTS_DIR / experiment_id
    else:
        output_dir = DRY_RUN_OUTPUTS_DIR / "latest"
    candidate_trace_requested = bool(
        args.use_qwen and getattr(args, "selection_file", None)
    )
    if candidate_trace_requested and (
        output_dir.resolve() == EXPERIMENT_OUTPUTS_DIR.resolve()
        or not _is_within(output_dir, EXPERIMENT_OUTPUTS_DIR)
    ):
        print(
            "[error] candidate trace output must be a new child directory under "
            f"{EXPERIMENT_OUTPUTS_DIR}",
            file=sys.stderr,
        )
        return 1
    output_paths = bundle_paths(output_dir)
    ensure_output_dirs(output_dir)
    if args.use_qwen and any(output_dir.iterdir()):
        print(
            "[error] traced Qwen run requires a new empty --output-dir; "
            "do not overwrite a prior run",
            file=sys.stderr,
        )
        return 1
    explicit_cache = getattr(args, "cache_dir", None)
    if explicit_cache:
        raw_cache = Path(explicit_cache).expanduser()
        reasoning_samples_dir = raw_cache if raw_cache.is_absolute() else REPO_ROOT / raw_cache
    elif args.use_qwen:
        reasoning_samples_dir = output_dir / "reasoning_samples"
    else:
        reasoning_samples_dir = output_dir / "reasoning_samples"
    if args.use_qwen and not _is_within(reasoning_samples_dir, output_dir):
        print(
            "[error] traced Qwen reasoning cache must stay inside --output-dir",
            file=sys.stderr,
        )
        return 1
    if args.use_qwen and reasoning_samples_dir.exists() and any(reasoning_samples_dir.iterdir()):
        print(
            "[error] traced Qwen run requires an empty reasoning cache directory",
            file=sys.stderr,
        )
        return 1
    reasoning_samples_dir.mkdir(parents=True, exist_ok=True)
    try:
        rerun_qids = _load_rerun_qids(getattr(args, "rerun_qids", None))
    except OSError as exc:
        print(f"[error] unable to read --rerun-qids: {exc}", file=sys.stderr)
        return 1

    if resume and not args.use_qwen:
        print("[error] --resume requires --use-qwen so cached real Qwen samples stay separate from dry-run", file=sys.stderr)
        return 1
    if resume and args.use_qwen:
        print(
            "[error] traced candidate inference must be fresh; inherit unchanged answers "
            "later with merge_submission instead of --resume",
            file=sys.stderr,
        )
        return 1
    if rerun_qids is not None and not resume:
        print("[error] --rerun-qids requires --resume", file=sys.stderr)
        return 1

    client: QwenClient | None = None
    trace_recorder: AgentTraceRecorder | None = None
    trace_report: dict[str, Any] | None = None
    forbidden_roots = default_candidate_forbidden_roots() if args.use_qwen else ()
    allowed_read_roots: tuple[Path, ...] = ()
    if args.use_qwen:
        allowed = [
            REPO_ROOT / "agent",
            REPO_ROOT / "public_dataset_upload" / "questions" / "group_a",
            REPO_ROOT / "processed_data" / "chunks.jsonl",
            REPO_ROOT / "processed_data" / "doc_meta.json",
            output_dir,
        ]
        if hide_doc_ids:
            allowed.append(REPO_ROOT / "processed_data" / "doc_cards.json")
        if getattr(args, "selection_file", None):
            allowed.append(Path(args.selection_file).expanduser().resolve())
        allowed_read_roots = tuple(path.resolve() for path in allowed)
    guard_context = (
        blind_data_guard(
            forbidden_roots,
            allowed_read_roots=allowed_read_roots,
            allowed_write_roots=(output_dir.resolve(),),
            block_subprocess=True,
        )
        if args.use_qwen
        else nullcontext(())
    )
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    try:
        with guard_context:
            questions, requested_scope = _select_questions(args)
            chunks = load_chunks()

            if hide_doc_ids:
                questions = [{**question, "doc_ids": []} for question in questions]
                requested_scope = f"{requested_scope} hide_doc_ids"

            qids = [str(q.get("qid", "")) for q in questions]
            if args.use_qwen:
                client = QwenClient()
                candidate_trace = candidate_trace_requested
                trace_dir = output_dir / "agent_traces" / f"run-{uuid.uuid4()}"
                trace_config = {
                    "runner": "agent.run_submission",
                    "pipeline_version": CURRENT_PIPELINE_VERSION,
                    "experiment_id": experiment_id,
                    "requested_scope": requested_scope,
                    "qids": qids,
                    "top_k": args.top_k,
                    "resume": resume,
                    "rerun_qids": sorted(rerun_qids or []),
                    "official_output": official_output,
                    "hide_doc_ids": hide_doc_ids,
                    "output_dir": display_path(output_dir),
                    "reasoning_samples_dir": display_path(reasoning_samples_dir),
                    "selection_file": (
                        display_path(Path(args.selection_file).expanduser().resolve())
                        if getattr(args, "selection_file", None)
                        else None
                    ),
                    "selection_sha256": (
                        sha256_file(Path(args.selection_file).expanduser().resolve())
                        if getattr(args, "selection_file", None)
                        else None
                    ),
                    "client_timeout_seconds": client.timeout,
                    "client_max_retries": client.max_retries,
                    "chunks_sha256": sha256_file(
                        REPO_ROOT / "processed_data" / "chunks.jsonl"
                    ),
                    "input_artifacts": {
                        "questions": input_artifact_snapshot(
                            REPO_ROOT / "public_dataset_upload" / "questions" / "group_a"
                        ),
                        "chunks": input_artifact_snapshot(
                            REPO_ROOT / "processed_data" / "chunks.jsonl"
                        ),
                        "doc_meta": input_artifact_snapshot(
                            REPO_ROOT / "processed_data" / "doc_meta.json"
                        ),
                        **(
                            {
                                "doc_cards": input_artifact_snapshot(
                                    REPO_ROOT / "processed_data" / "doc_cards.json"
                                )
                            }
                            if hide_doc_ids
                            else {}
                        ),
                    },
                }
                if candidate_trace:
                    assert_candidate_experiment_policy(
                        trace_config,
                        model=client.model,
                        base_url=client.base_url,
                    )
                trace_recorder = AgentTraceRecorder(
                    trace_dir,
                    purpose=(
                        "candidate_generation" if candidate_trace else "unscored_diagnostic"
                    ),
                    model=client.model,
                    base_url=client.base_url,
                    config=trace_config,
                )
                client.trace_recorder = trace_recorder

            print(
                f"[scope] requested_scope={requested_scope} "
                f"questions={len(questions)} top_k={args.top_k}"
            )
            results, failures = run_questions(
                questions,
                chunks,
                args.use_qwen,
                top_k=args.top_k,
                client=client,
                resume=resume,
                rerun_qids=rerun_qids,
                reasoning_samples_dir=reasoning_samples_dir,
            )
            if trace_recorder is not None:
                for result in results:
                    trace_recorder.record_derivation(result)

            answer_path = write_answer_csv(results, output_paths[0])
            evidence_path = write_evidence_json(results, output_paths[1])
            manifest = _build_manifest(
                run_started_at=run_started_at,
                mode=mode,
                requested_scope=requested_scope,
                qids=qids,
                results=results,
                failures=failures,
                resume=resume,
                rerun_qids=rerun_qids,
                output_paths=output_paths,
                model=client.model if client else "none",
                experiment_id=experiment_id,
                official_output=official_output,
                hide_doc_ids=hide_doc_ids,
            )
            if trace_recorder is not None:
                manifest["agent_trace"] = {
                    "required": True,
                    "schema_version": "agent-trace/v1",
                    "trace_run_id": trace_recorder.run_id,
                    "trace_dir": display_path(trace_recorder.trace_dir),
                    "blind_data_guard": "enforced",
                }
            manifest_path = write_run_manifest(manifest, output_paths[2])
            if trace_recorder is not None:
                trace_recorder.finalize(output_paths=output_paths, failures=failures)
                trace_report = validate_trace_directory(
                    trace_recorder.trace_dir,
                    artifact_dir=output_dir,
                    require_candidate_eligible=candidate_trace,
                    require_current_code_match=True,
                )
    except MissingApiKeyError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    except (BlindDataAccessError, KeyError, FileNotFoundError, OSError, ValueError) as exc:
        if trace_recorder is not None and trace_recorder.manifest.get("status") == "recording":
            trace_recorder.finalize(
                output_paths=None,
                failures=[{"qid": "", "error": str(exc)}],
            )
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    if mode == MODE_DRY_RUN:
        print(f"[mode] {MODE_DRY_RUN}（未调用 Qwen，fallback 占位答案，非正式推理结果）")
    else:
        print(f"[mode] {MODE_QWEN} model={client.model if client else '?'}")
        if trace_recorder is not None:
            print(f"[trace] {trace_recorder.trace_dir}")
        if trace_report is not None:
            status = "PASS" if trace_report["ok"] else "FAIL"
            print(
                f"[trace-gate] {status} calls={trace_report.get('call_count', 0)} "
                f"derivations={trace_report.get('derivation_count', 0)}"
            )
            for error in trace_report.get("errors", []):
                print(f"[trace-error] {error}", file=sys.stderr)
    print(
        f"[summary] success={len(results)} failure={len(failures)} "
        f"low_confidence={manifest['low_confidence_count']} "
        f"reused={manifest['reused_from_cache_count']} tokens={manifest['total_tokens']}"
    )
    if failures:
        for failure in failures:
            print(f"[failure] {failure['qid']}: {failure['error']}")
    print(f"[ok] answer.csv        -> {answer_path}")
    print(f"[ok] evidence.json     -> {evidence_path}")
    print(f"[ok] run_manifest.json -> {manifest_path}")
    trace_ok = trace_report is None or bool(trace_report.get("ok"))
    return 0 if not failures and trace_ok else 1


def run(qid: str, use_qwen: bool, top_k: int) -> int:
    """Backward-compatible single-question entrypoint used by earlier tests."""
    args = argparse.Namespace(
        qid=qid,
        domain=None,
        all=False,
        limit=None,
        dry_run=not use_qwen,
        use_qwen=use_qwen,
        top_k=top_k,
        resume=False,
        rerun_qids=None,
        output_dir=None,
        official_output=False,
        experiment_id="backward_compatible_run",
        cache_dir=None,
        hide_doc_ids=False,
        selection_file=None,
    )
    return run_scope(args)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agent.run_submission",
        description="AFAC2026 赛题四提交线（--use-qwen 正式推理 / --dry-run 接口联调）",
    )
    scope_group = parser.add_mutually_exclusive_group(required=True)
    scope_group.add_argument("--qid", help="题目 qid，例如 ins_a_007")
    scope_group.add_argument("--domain", help="按领域批量运行，例如 insurance")
    scope_group.add_argument("--all", action="store_true", help="运行 group_a 全部题目（Task 7 预留）")
    scope_group.add_argument(
        "--selection-file",
        help="运行预注册且 frozen_before_labeling=true 的 qid selection JSON",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run", action="store_true", help="不调用 Qwen（默认行为），mode=dry_run_mock"
    )
    mode_group.add_argument(
        "--use-qwen", action="store_true", help="正式调用 Qwen API（需 DASHSCOPE_API_KEY 或 QWEN_API_KEY）"
    )
    parser.add_argument("--top-k", type=int, default=5, dest="top_k", help="每选项证据数")
    parser.add_argument("--limit", type=int, help="限制运行题数，用于小规模冒烟测试")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="旧版兼容参数；受治理 Trace Gate 会拒绝候选续跑和缓存复用",
    )
    parser.add_argument(
        "--rerun-qids",
        help="旧版兼容参数；新候选应在 merge_submission 阶段继承父版本",
    )
    parser.add_argument(
        "--output-dir",
        help="隔离运行目录；相对路径按仓库根解析。省略时 dry-run 写 outputs/dry_runs/latest，Qwen 写 outputs/experiments/<experiment-id>",
    )
    parser.add_argument(
        "--official-output",
        action="store_true",
        help="旧版兼容参数；Trace Gate 禁止推理直接写 submission/",
    )
    parser.add_argument("--experiment-id", help="实验 ID，用于默认输出目录和 manifest lineage")
    parser.add_argument(
        "--cache-dir",
        help="trace 内部 cache；必须位于本次 --output-dir 内（通常省略并使用默认值）",
    )
    parser.add_argument(
        "--hide-doc-ids",
        action="store_true",
        help="B 模式离线模拟：隐藏 A 题 doc_ids，改用文档卡片召回；禁止正式输出",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        print("[error] --limit must be a positive integer", file=sys.stderr)
        return 1
    return run_scope(args)


if __name__ == "__main__":
    raise SystemExit(main())
