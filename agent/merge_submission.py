"""按 qid 将冻结父版本与单变量重跑产物合成为候选提交。

空 rerun 集走快速路径，三份文件逐字节复制父版本，用于证明父版本可复用。
非空 rerun 集只替换指定 qid，并在 manifest 中写入完整 lineage。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.load_questions import load_all_questions
from agent.output_writer import ANSWER_CSV_COLUMNS
from agent.paths import REPO_ROOT, bundle_paths
from agent.trace_gate import (
    freeze_candidate,
    load_frozen_selection,
    resolve_recorded_path,
    sha256_file as trace_sha256_file,
    validate_trace_directory,
)
from agent.validate_submission import validate_submission_files

MERGE_TOOL_VERSION = "v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bundle_sha256(bundle_dir: Path) -> dict[str, str]:
    answer, evidence, manifest = bundle_paths(bundle_dir)
    return {
        "answer_csv": sha256_file(answer),
        "evidence_json": sha256_file(evidence),
        "run_manifest_json": sha256_file(manifest),
    }


def _read_answer_rows(path: Path) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows or rows[0].get("qid") != "summary":
        raise ValueError(f"answer.csv missing summary row: {path}")
    by_qid: dict[str, dict[str, str]] = {}
    for row in rows[1:]:
        qid = str(row.get("qid", ""))
        if not qid or qid in by_qid:
            raise ValueError(f"invalid or duplicate qid in {path}: {qid!r}")
        by_qid[qid] = row
    return rows[0], by_qid


def _read_evidence(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"evidence.json must be a list: {path}")
    by_qid: dict[str, dict[str, Any]] = {}
    for record in data:
        if not isinstance(record, dict):
            raise ValueError(f"non-object evidence record: {path}")
        qid = str(record.get("qid", ""))
        if not qid or qid in by_qid:
            raise ValueError(f"invalid or duplicate evidence qid in {path}: {qid!r}")
        by_qid[qid] = record
    return by_qid


def _relative_or_absolute(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _write_answer(path: Path, rows: list[dict[str, str]]) -> None:
    prompt = sum(int(row["prompt_tokens"]) for row in rows)
    completion = sum(int(row["completion_tokens"]) for row in rows)
    total = sum(int(row["total_tokens"]) for row in rows)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ANSWER_CSV_COLUMNS)
        writer.writeheader()
        writer.writerow(
            {
                "qid": "summary",
                "answer": "",
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": total,
            }
        )
        writer.writerows(rows)


def merge_submission_bundles(
    parent_dir: Path,
    rerun_dir: Path | None,
    output_dir: Path,
    rerun_qids: set[str],
    *,
    parent_version: str,
    experiment_id: str,
    experiment_pipeline_version: str,
    selection_path: Path | None = None,
) -> tuple[Path, Path, Path]:
    parent_dir = parent_dir.resolve()
    output_dir = output_dir.resolve()
    parent_paths = bundle_paths(parent_dir)
    for path in parent_paths:
        if not path.is_file():
            raise FileNotFoundError(f"parent artifact missing: {path}")
    parent_manifest = json.loads(parent_paths[2].read_text(encoding="utf-8"))
    declared_parent_version = str(
        parent_manifest.get("pipeline_version") or ""
    ).strip()
    if declared_parent_version and declared_parent_version != parent_version:
        raise ValueError("parent_version does not match frozen parent manifest")
    parent_version_provenance = (
        "parent_manifest" if declared_parent_version else "legacy_parent_version_claim"
    )
    legacy_parent_version_claim = (
        None
        if declared_parent_version
        else {
            "claimed_version": parent_version,
            "reason": "parent manifest predates the pipeline_version field",
        }
    )
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"candidate output directory must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = bundle_paths(output_dir)

    if not rerun_qids:
        for source, target in zip(parent_paths, output_paths):
            shutil.copyfile(source, target)
        report = validate_submission_files(*output_paths)
        if not report["ok"]:
            raise ValueError("parent-copy candidate validation failed: " + "; ".join(report["errors"]))
        freeze_candidate(
            output_dir,
            parent_dir=parent_dir,
            experiment_id=experiment_id,
            pipeline_version=experiment_pipeline_version,
            parent_version=parent_version,
            trace_dir=None,
            generation_mode="byte_identical_parent_copy",
        )
        return output_paths

    if rerun_dir is None:
        raise ValueError("non-empty rerun_qids requires rerun_dir")
    rerun_dir = rerun_dir.resolve()
    rerun_paths = bundle_paths(rerun_dir)
    for path in rerun_paths:
        if not path.is_file():
            raise FileNotFoundError(f"rerun artifact missing: {path}")

    official_qids = [str(q["qid"]) for q in load_all_questions()]
    official_set = set(official_qids)
    unknown = rerun_qids - official_set
    if unknown:
        raise ValueError(f"rerun_qids contains unknown qids: {sorted(unknown)}")

    _, parent_rows = _read_answer_rows(parent_paths[0])
    _, rerun_rows = _read_answer_rows(rerun_paths[0])
    parent_evidence = _read_evidence(parent_paths[1])
    rerun_evidence = _read_evidence(rerun_paths[1])
    if set(parent_rows) != official_set or set(parent_evidence) != official_set:
        raise ValueError("parent bundle qids do not equal official group_a qids")
    if not rerun_qids <= set(rerun_rows) or not rerun_qids <= set(rerun_evidence):
        raise ValueError("rerun bundle does not contain every requested rerun qid")

    merged_rows = [
        dict(rerun_rows[qid] if qid in rerun_qids else parent_rows[qid])
        for qid in official_qids
    ]
    merged_evidence = [
        rerun_evidence[qid] if qid in rerun_qids else parent_evidence[qid]
        for qid in official_qids
    ]
    rerun_manifest = json.loads(rerun_paths[2].read_text(encoding="utf-8"))
    if str(rerun_manifest.get("pipeline_version", "")) != experiment_pipeline_version:
        raise ValueError("rerun manifest pipeline_version does not match experiment version")
    trace_meta = rerun_manifest.get("agent_trace")
    if not isinstance(trace_meta, dict) or not trace_meta.get("trace_dir"):
        raise ValueError("rerun artifact is missing required agent_trace provenance")
    trace_dir = resolve_recorded_path(str(trace_meta["trace_dir"]))
    trace_report = validate_trace_directory(
        trace_dir,
        artifact_dir=rerun_dir,
        require_candidate_eligible=True,
        require_current_code_match=True,
    )
    if not trace_report["ok"]:
        raise ValueError("rerun agent trace is invalid: " + "; ".join(trace_report["errors"]))
    traced_qids = [
        str(value)
        for value in (trace_report.get("manifest", {}).get("config", {}).get("qids", []))
    ]
    if set(traced_qids) != rerun_qids or len(traced_qids) != len(rerun_qids):
        raise ValueError("rerun_qids do not exactly match traced derivation qids")
    if selection_path is None:
        raise ValueError("non-empty traced candidate requires --selection-file")
    selection_path = selection_path.resolve()
    selection = load_frozen_selection(selection_path)
    selection_qids = selection["qids"]
    if set(selection_qids) != rerun_qids:
        raise ValueError("blind selection qids do not exactly match rerun_qids")
    traced_config = trace_report["manifest"].get("config", {})
    if str(traced_config.get("experiment_id", "")) != experiment_id:
        raise ValueError("experiment_id does not match traced run config")
    if str(traced_config.get("pipeline_version", "")) != experiment_pipeline_version:
        raise ValueError("traced code/config pipeline_version does not match experiment version")
    if traced_config.get("selection_sha256") != trace_sha256_file(selection_path):
        raise ValueError("trace was not run from this frozen blind selection")
    mismatched_record_versions = sorted(
        qid
        for qid in rerun_qids
        if str(rerun_evidence[qid].get("pipeline_version", ""))
        != experiment_pipeline_version
    )
    if mismatched_record_versions:
        raise ValueError(
            "rerun evidence pipeline_version mismatch: "
            + ", ".join(mismatched_record_versions)
        )
    _write_answer(output_paths[0], merged_rows)
    output_paths[1].write_text(
        json.dumps(merged_evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    prompt = sum(int(row["prompt_tokens"]) for row in merged_rows)
    completion = sum(int(row["completion_tokens"]) for row in merged_rows)
    total = sum(int(row["total_tokens"]) for row in merged_rows)
    low_qids = [str(r["qid"]) for r in merged_evidence if r.get("low_confidence")]
    models = {str(r.get("model", "")) for r in merged_evidence if str(r.get("model", ""))}
    model = models.pop() if len(models) == 1 else "mixed"
    run_id = f"merge:{experiment_id}:{_now_iso()}"
    per_record_lineage = {
        qid: {
            "source_kind": "rerun" if qid in rerun_qids else "parent",
            "source_pipeline_version": (
                experiment_pipeline_version
                if qid in rerun_qids
                else declared_parent_version or parent_version
            ),
            "source_pipeline_version_provenance": (
                "rerun_manifest" if qid in rerun_qids else parent_version_provenance
            ),
            "source_run_id": (
                str(rerun_manifest.get("run_id") or rerun_manifest.get("run_started_at") or "rerun")
                if qid in rerun_qids
                else str(parent_manifest.get("run_id") or parent_manifest.get("run_started_at") or "parent")
            ),
        }
        for qid in official_qids
    }
    manifest = {
        "run_started_at": _now_iso(),
        "run_finished_at": _now_iso(),
        "run_id": run_id,
        "mode": "qwen",
        "model": model,
        "pipeline_version": experiment_pipeline_version,
        "submission_scope": "official_group_a",
        "qid": None,
        "qids": official_qids,
        "requested_scope": "all",
        "success_count": len(official_qids),
        "failure_count": 0,
        "failures": [],
        "low_confidence_count": len(low_qids),
        "low_confidence_qids": low_qids,
        "total_prompt_tokens": prompt,
        "total_completion_tokens": completion,
        "total_tokens": total,
        "average_total_tokens": round(total / len(official_qids), 2),
        "experiment_id": experiment_id,
        "experiment_pipeline_version": experiment_pipeline_version,
        "parent_version": parent_version,
        "legacy_parent_version_claim": legacy_parent_version_claim,
        "parent_artifact_dir": _relative_or_absolute(parent_dir),
        "parent_artifact_sha256": bundle_sha256(parent_dir),
        "rerun_artifact_dir": _relative_or_absolute(rerun_dir),
        "rerun_artifact_sha256": bundle_sha256(rerun_dir),
        "rerun_qids": sorted(rerun_qids),
        "merge_tool_version": MERGE_TOOL_VERSION,
        "per_record_lineage": per_record_lineage,
        "agent_trace_gate": {
            "schema_version": "agent-trace/v1",
            "status": "PASS",
            "trace_run_id": trace_report.get("trace_run_id"),
            "trace_dir": _relative_or_absolute(trace_dir),
            "fresh_traced_qids": traced_qids,
            "prospective_qids": selection["prospective_qids"],
            "known_before_freeze_qids": selection["known_before_freeze_qids"],
            "legacy_inherited_qids": [
                qid for qid in official_qids if qid not in rerun_qids
            ],
            "legacy_inheritance_reason": "frozen_parent_predates_agent_trace_gate",
            "blind_selection": _relative_or_absolute(selection_path),
            "blind_selection_sha256": trace_sha256_file(selection_path),
        },
        "output_paths": {
            "answer_csv": _relative_or_absolute(output_paths[0]),
            "evidence_json": _relative_or_absolute(output_paths[1]),
            "run_manifest_json": _relative_or_absolute(output_paths[2]),
        },
    }
    output_paths[2].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = validate_submission_files(*output_paths)
    if not report["ok"]:
        raise ValueError("candidate submission validation failed: " + "; ".join(report["errors"]))
    freeze_candidate(
        output_dir,
        parent_dir=parent_dir,
        experiment_id=experiment_id,
        pipeline_version=experiment_pipeline_version,
        parent_version=parent_version,
        trace_dir=trace_dir,
        generation_mode="traced_rerun_plus_frozen_parent",
        selection_path=selection_path,
        trace_artifact_dir=rerun_dir,
    )
    return output_paths


def _load_qids(path: Path | None) -> set[str]:
    if path is None:
        return set()
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return set()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        qids = data.get("rerun_qids")
        if not isinstance(qids, list):
            qids = data.get("qids")
        if isinstance(qids, list):
            return {str(item) for item in qids}
    if isinstance(data, list):
        return {str(item) for item in data}
    return {
        part.strip()
        for line in raw.splitlines()
        for part in line.split(",")
        if part.strip() and not part.strip().startswith("#")
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent.merge_submission")
    parser.add_argument("--parent-dir", required=True)
    parser.add_argument("--rerun-dir")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--rerun-qids")
    parser.add_argument("--parent-version", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--experiment-pipeline-version", required=True)
    parser.add_argument("--selection-file")
    args = parser.parse_args(argv)
    try:
        paths = merge_submission_bundles(
            Path(args.parent_dir),
            Path(args.rerun_dir) if args.rerun_dir else None,
            Path(args.output_dir),
            _load_qids(Path(args.rerun_qids)) if args.rerun_qids else set(),
            parent_version=args.parent_version,
            experiment_id=args.experiment_id,
            experiment_pipeline_version=args.experiment_pipeline_version,
            selection_path=Path(args.selection_file) if args.selection_file else None,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[error] {exc}")
        return 1
    print("[ok] merged artifacts")
    for path in paths:
        print(f"[ok] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
