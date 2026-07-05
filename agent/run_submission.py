"""提交线 CLI 入口（Task 6：单题/领域批量链路）。

用法：
    python -m agent.run_submission --qid ins_a_007            # 默认 dry-run
    python -m agent.run_submission --qid ins_a_007 --dry-run  # 显式 dry-run
    python -m agent.run_submission --qid ins_a_007 --use-qwen # 正式调用 Qwen
    python -m agent.run_submission --domain insurance --limit 2 --dry-run
    python -m agent.run_submission --domain insurance --use-qwen
    python -m agent.run_submission --all --use-qwen --resume

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
from datetime import datetime, timezone
from typing import Any

from agent.load_questions import find_question_by_qid, load_all_questions, load_questions_by_domain
from agent.normalize_answer import validate_answer_format
from agent.output_writer import (
    write_answer_csv,
    write_evidence_json,
    write_run_manifest,
)
from agent.paths import (
    ANSWER_CSV_PATH,
    EVIDENCE_JSON_PATH,
    REPO_ROOT,
    RUN_MANIFEST_PATH,
    ensure_output_dirs,
)
from agent.qwen_client import MissingApiKeyError, QwenClient
from agent.reason_qwen import (
    MODE_DRY_RUN,
    MODE_QWEN,
    REASONING_SAMPLES_DIR,
    reason_question_dry_run,
    reason_question_with_qwen,
    save_reasoning_sample,
)
from agent.retrieve import load_chunks, retrieve_for_question


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _compact_retrieval(retrieval: dict[str, Any]) -> dict[str, Any]:
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
    retrieval = retrieve_for_question(question, chunks, top_k=top_k)
    if use_qwen:
        result = reason_question_with_qwen(question, retrieval, client=client)
    else:
        result = reason_question_dry_run(question, retrieval)
    # evidence.json 需要保留检索证据（去掉冗余 query_terms 以控制体积）
    result["retrieval"] = _compact_retrieval(retrieval)
    result["evidence"] = []  # 兼容 Task 1 字段：题级扁平证据列表（逐项证据在 retrieval 里）
    return result


def is_reusable_qwen_result(
    result: dict[str, Any], expected_qid: str | None = None
) -> tuple[bool, str]:
    """判断 reasoning sample 是否可用于续跑复用。"""
    if expected_qid is not None and str(result.get("qid", "")) != expected_qid:
        return False, f"qid mismatch: expected {expected_qid}, got {result.get('qid')!r}"
    if result.get("mode") != MODE_QWEN:
        return False, f"mode is {result.get('mode')!r}, not qwen"
    if int(result.get("prompt_tokens") or 0) <= 0 or int(result.get("total_tokens") or 0) <= 0:
        return False, "prompt_tokens/total_tokens must be > 0"
    if int(result.get("completion_tokens") or 0) < 0:
        return False, "completion_tokens must be >= 0"
    option_judgments = result.get("option_judgments")
    if not isinstance(option_judgments, dict) or not option_judgments:
        return False, "option_judgments missing"
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
    try:
        validate_answer_format(
            str(result.get("answer", "")),
            str(result.get("answer_format", "")),
            result.get("options", {}) if isinstance(result.get("options"), dict) else {},
        )
    except ValueError as exc:
        return False, f"invalid answer format: {exc}"
    return True, "ok"


def _load_reasoning_sample(qid: str) -> tuple[dict[str, Any] | None, str]:
    path = REASONING_SAMPLES_DIR / f"{qid}.json"
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
        }
    )
    return result


def run_questions(
    questions: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    use_qwen: bool,
    top_k: int,
    client: QwenClient | None = None,
    resume: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """批量运行题目。单题失败记录后继续处理后续题目。"""
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for index, question in enumerate(questions, start=1):
        qid = str(question.get("qid", ""))
        try:
            if resume and use_qwen:
                cached, load_status = _load_reasoning_sample(qid)
                if cached is not None:
                    reusable, reason = is_reusable_qwen_result(cached, expected_qid=qid)
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
            save_reasoning_sample({k: v for k, v in result.items() if k != "retrieval"})
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
) -> dict[str, Any]:
    low_confidence_qids = [r["qid"] for r in results if r.get("low_confidence")]
    total_prompt = sum(r["prompt_tokens"] for r in results)
    total_completion = sum(r["completion_tokens"] for r in results)
    total_tokens = sum(r["total_tokens"] for r in results)
    reused_qids = [r["qid"] for r in results if r.get("_reused_from_cache")]
    return {
        "run_started_at": run_started_at,
        "run_finished_at": _now_iso(),
        "mode": mode,
        "qid": qids[0] if len(qids) == 1 else None,
        "qids": qids,
        "requested_scope": requested_scope,
        "output_paths": {
            "answer_csv": str(ANSWER_CSV_PATH.relative_to(REPO_ROOT)),
            "evidence_json": str(EVIDENCE_JSON_PATH.relative_to(REPO_ROOT)),
            "run_manifest_json": str(RUN_MANIFEST_PATH.relative_to(REPO_ROOT)),
        },
        "success_count": len(results),
        "failure_count": len(failures),
        "failures": failures,
        "resume": resume,
        "reused_from_cache_count": len(reused_qids),
        "reused_from_cache_qids": reused_qids,
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
    raise ValueError("必须指定 --qid、--domain 或 --all")


def run_scope(args: argparse.Namespace) -> int:
    ensure_output_dirs()
    run_started_at = _now_iso()
    mode = MODE_QWEN if args.use_qwen else MODE_DRY_RUN
    resume = bool(getattr(args, "resume", False))

    if resume and not args.use_qwen:
        print("[error] --resume requires --use-qwen so cached real Qwen samples stay separate from dry-run", file=sys.stderr)
        return 1

    client: QwenClient | None = None
    if args.use_qwen:
        try:
            client = QwenClient()
        except MissingApiKeyError as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 1

    try:
        questions, requested_scope = _select_questions(args)
        chunks = load_chunks()
    except (KeyError, FileNotFoundError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    qids = [str(q.get("qid", "")) for q in questions]
    print(f"[scope] requested_scope={requested_scope} questions={len(questions)} top_k={args.top_k}")
    results, failures = run_questions(
        questions, chunks, args.use_qwen, top_k=args.top_k, client=client, resume=resume
    )

    answer_path = write_answer_csv(results)
    evidence_path = write_evidence_json(results)
    manifest = _build_manifest(
        run_started_at=run_started_at,
        mode=mode,
        requested_scope=requested_scope,
        qids=qids,
        results=results,
        failures=failures,
        resume=resume,
    )
    manifest_path = write_run_manifest(manifest)

    if mode == MODE_DRY_RUN:
        print(f"[mode] {MODE_DRY_RUN}（未调用 Qwen，fallback 占位答案，非正式推理结果）")
    else:
        print(f"[mode] {MODE_QWEN} model={client.model if client else '?'}")
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
    return 0 if not failures else 1


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
        help="续跑：复用已成功的 processed_data/reasoning_samples，只重跑缺失/出错/0 token 题",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        print("[error] --limit must be a positive integer", file=sys.stderr)
        return 1
    return run_scope(args)


if __name__ == "__main__":
    raise SystemExit(main())
