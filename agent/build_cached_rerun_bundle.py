"""从已完成的 Qwen reasoning cache 重建可合并的 rerun 三件套。

本工具是 cache-only 的：它不创建 Qwen 客户端，也没有网络调用路径。任何缓存
缺失、版本不符、题面不一致或 Token 非法都会 fail closed。检索证据会用当前冻结
的本地 chunks 重新附加，并在 manifest 中显式记录这一事实与每个缓存文件的哈希。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.load_questions import load_all_questions
from agent.output_writer import write_answer_csv, write_evidence_json, write_run_manifest
from agent.paths import REPO_ROOT, bundle_paths
from agent.run_submission import _attach_retrieval_to_cached_result, is_reusable_qwen_result
from agent.retrieve import load_chunks


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def load_qids(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError("qid file is empty")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        parsed = parsed.get("rerun_qids")
    if isinstance(parsed, list):
        qids = [str(value).strip() for value in parsed if str(value).strip()]
    else:
        qids = [
            value.strip()
            for line in raw.splitlines()
            for value in line.split(",")
            if value.strip() and not value.strip().startswith("#")
        ]
    if not qids:
        raise ValueError("qid file contains no qids")
    if len(qids) != len(set(qids)):
        raise ValueError("qid file contains duplicate qids")
    return qids


def _assert_question_identity(cached: dict[str, Any], question: dict[str, Any]) -> None:
    exact_fields = ("qid", "domain", "answer_format", "question", "options", "doc_ids")
    mismatched = [field for field in exact_fields if cached.get(field) != question.get(field)]
    if mismatched:
        raise ValueError(
            f"{question['qid']}: cache does not match frozen question fields: "
            + ", ".join(mismatched)
        )


def build_cached_rerun_bundle(
    *,
    qids_file: Path,
    cache_dir: Path,
    output_dir: Path,
    pipeline_version: str,
    experiment_id: str,
    top_k: int = 5,
) -> tuple[Path, Path, Path]:
    qids_file = qids_file.resolve()
    cache_dir = cache_dir.resolve()
    output_dir = output_dir.resolve()
    if not qids_file.is_file():
        raise FileNotFoundError(f"qid file not found: {qids_file}")
    if not cache_dir.is_dir():
        raise FileNotFoundError(f"cache directory not found: {cache_dir}")
    if not pipeline_version.strip() or not experiment_id.strip():
        raise ValueError("pipeline_version and experiment_id are required")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output_dir}")

    requested_qids = load_qids(qids_file)
    official_questions = load_all_questions()
    by_qid = {str(question["qid"]): question for question in official_questions}
    unknown = set(requested_qids) - set(by_qid)
    if unknown:
        raise ValueError(f"unknown qids: {sorted(unknown)}")
    selected_set = set(requested_qids)
    questions = [q for q in official_questions if str(q["qid"]) in selected_set]
    if len(questions) != len(requested_qids):
        raise ValueError("selected qid count mismatch")

    chunks = load_chunks()
    results: list[dict[str, Any]] = []
    cache_hashes: dict[str, str] = {}
    for question in questions:
        qid = str(question["qid"])
        cache_path = cache_dir / f"{qid}.json"
        if not cache_path.is_file():
            raise FileNotFoundError(f"{qid}: cache missing: {cache_path}")
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{qid}: cache is invalid JSON: {exc}") from exc
        if not isinstance(cached, dict):
            raise ValueError(f"{qid}: cache must be a JSON object")
        reusable, reason = is_reusable_qwen_result(
            cached,
            expected_qid=qid,
            expected_pipeline_version=pipeline_version,
        )
        if not reusable:
            raise ValueError(f"{qid}: cache is not reusable: {reason}")
        _assert_question_identity(cached, question)
        result = _attach_retrieval_to_cached_result(cached, question, chunks, top_k)
        tf_evidence = result.get("retrieval", {}).get("tf", {}).get("evidence", [])
        if question.get("answer_format") == "tf" and not tf_evidence:
            raise ValueError(f"{qid}: reconstructed TF retrieval has no evidence")
        result.update(
            {
                "source_kind": "validated_cache",
                "source_pipeline_version": pipeline_version,
                "source_run_id": f"cache:{pipeline_version}:{qid}:{_sha256(cache_path)[:16]}",
            }
        )
        results.append(result)
        cache_hashes[qid] = _sha256(cache_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    answer_path, evidence_path, manifest_path = bundle_paths(output_dir)
    write_answer_csv(results, answer_path)
    write_evidence_json(results, evidence_path)
    started_at = _now_iso()
    prompt = sum(int(result["prompt_tokens"]) for result in results)
    completion = sum(int(result["completion_tokens"]) for result in results)
    total = sum(int(result["total_tokens"]) for result in results)
    models = {str(result.get("model", "")) for result in results if result.get("model")}
    low_qids = [str(result["qid"]) for result in results if result.get("low_confidence")]
    manifest = {
        "run_started_at": started_at,
        "run_finished_at": _now_iso(),
        "run_id": f"cache-bundle:{experiment_id}:{started_at}",
        "mode": "qwen",
        "model": next(iter(models)) if len(models) == 1 else "mixed",
        "pipeline_version": pipeline_version,
        "submission_scope": "experiment_rerun_bundle",
        "requested_scope": "cache_only_rerun_qids",
        "qids": [str(result["qid"]) for result in results],
        "success_count": len(results),
        "failure_count": 0,
        "failures": [],
        "low_confidence_count": len(low_qids),
        "low_confidence_qids": low_qids,
        "total_prompt_tokens": prompt,
        "total_completion_tokens": completion,
        "total_tokens": total,
        "average_total_tokens": round(total / len(results), 2),
        "experiment_id": experiment_id,
        "cache_only": True,
        "execution_mode": "cache_only_repack",
        "api_calls": 0,
        "network_calls": 0,
        "resume": True,
        "reused_from_cache_count": len(results),
        "reused_from_cache_qids": [str(result["qid"]) for result in results],
        "reused_pipeline_versions": {pipeline_version: len(results)},
        "cache_source_dir": _display_path(cache_dir),
        "cache_file_sha256": cache_hashes,
        "qids_file": _display_path(qids_file),
        "qids_file_sha256": _sha256(qids_file),
        "retrieval_reconstructed_from_current_frozen_chunks": True,
        "retrieval_provenance_sha256": {
            "processed_data/chunks.jsonl": _sha256(REPO_ROOT / "processed_data" / "chunks.jsonl"),
            "agent/retrieve.py": _sha256(REPO_ROOT / "agent" / "retrieve.py"),
            "agent/query_terms.py": _sha256(REPO_ROOT / "agent" / "query_terms.py"),
        },
        "top_k": top_k,
        "output_paths": {
            "answer_csv": _display_path(answer_path),
            "evidence_json": _display_path(evidence_path),
            "run_manifest_json": _display_path(manifest_path),
        },
    }
    write_run_manifest(manifest, manifest_path)
    return answer_path, evidence_path, manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent.build_cached_rerun_bundle")
    parser.add_argument("--qids", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--pipeline-version", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        paths = build_cached_rerun_bundle(
            qids_file=Path(args.qids),
            cache_dir=Path(args.cache_dir),
            output_dir=Path(args.output_dir),
            pipeline_version=args.pipeline_version,
            experiment_id=args.experiment_id,
            top_k=args.top_k,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[error] {exc}")
        return 1
    print("[ok] cache-only rerun bundle built; network_calls=0")
    for path in paths:
        print(f"[ok] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
