"""Validate generated submission artifacts before uploading.

This guard is intentionally separate from answer generation: it does not change
answers, call models, or inspect raw documents. It only checks that the files
were produced by a real Qwen run and are internally consistent.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from agent.normalize_answer import validate_answer_format
from agent.output_writer import ANSWER_CSV_COLUMNS
from agent.load_questions import load_all_questions
from agent.paths import ANSWER_CSV_PATH, EVIDENCE_JSON_PATH, REPO_ROOT, RUN_MANIFEST_PATH


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _to_int(value: Any, label: str, errors: list[str]) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        errors.append(f"{label} must be an integer, got {value!r}")
        return 0


def _read_answer_csv(path: Path, errors: list[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ANSWER_CSV_COLUMNS:
            errors.append(
                f"answer.csv header mismatch: expected {ANSWER_CSV_COLUMNS}, got {reader.fieldnames}"
            )
            return []
        return list(reader)


def _check_file_exists(path: Path, errors: list[str], label: str) -> bool:
    if not path.exists():
        errors.append(f"{label} not found: {path}")
        return False
    if not path.is_file():
        errors.append(f"{label} is not a file: {path}")
        return False
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_manifest_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


def _contains_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return "dry-run 占位" in lowered or "dry_run_mock" in lowered or "mock 占位" in lowered
    if isinstance(value, dict):
        return any(_contains_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_placeholder(item) for item in value)
    return False


def validate_submission_files(
    answer_csv: Path | str = ANSWER_CSV_PATH,
    evidence_json: Path | str = EVIDENCE_JSON_PATH,
    manifest_json: Path | str = RUN_MANIFEST_PATH,
) -> dict[str, Any]:
    """Return a validation report for answer/evidence/manifest artifacts."""
    answer_csv = Path(answer_csv)
    evidence_json = Path(evidence_json)
    manifest_json = Path(manifest_json)
    errors: list[str] = []
    warnings: list[str] = []

    files_ok = all(
        [
            _check_file_exists(answer_csv, errors, "answer.csv"),
            _check_file_exists(evidence_json, errors, "evidence.json"),
            _check_file_exists(manifest_json, errors, "run_manifest.json"),
        ]
    )
    if not files_ok:
        return _report(False, errors, warnings, 0, 0)

    rows = _read_answer_csv(answer_csv, errors)
    try:
        evidence_records = _load_json(evidence_json)
    except json.JSONDecodeError as exc:
        errors.append(f"evidence.json is not valid JSON: {exc}")
        evidence_records = []
    try:
        manifest = _load_json(manifest_json)
    except json.JSONDecodeError as exc:
        errors.append(f"run_manifest.json is not valid JSON: {exc}")
        manifest = {}

    if not isinstance(evidence_records, list):
        errors.append("evidence.json must be a list of per-question records")
        evidence_records = []
    if not isinstance(manifest, dict):
        errors.append("run_manifest.json must be a JSON object")
        manifest = {}

    if not rows:
        errors.append("answer.csv has no data rows")
        return _report(False, errors, warnings, 0, 0)

    summary = rows[0]
    question_rows = rows[1:]
    if summary.get("qid") != "summary":
        errors.append("answer.csv first data row must have qid=summary")
    if summary.get("answer", "") not in ("", None):
        errors.append("answer.csv summary answer must be empty")

    manifest_mode = manifest.get("mode")
    if manifest_mode != "qwen":
        errors.append(f"run_manifest mode must be qwen before upload, got {manifest_mode!r}")
    if manifest_mode == "dry_run_mock":
        errors.append("dry_run_mock artifacts must never be uploaded")
    if _to_int(manifest.get("failure_count", 0), "run_manifest.failure_count", errors) != 0:
        errors.append("run_manifest failure_count must be 0 before upload")

    evidence_by_qid: dict[str, dict[str, Any]] = {}
    for record in evidence_records:
        if not isinstance(record, dict):
            errors.append("evidence.json contains a non-object record")
            continue
        qid = str(record.get("qid", ""))
        if not qid:
            errors.append("evidence.json contains a record without qid")
            continue
        if qid in evidence_by_qid:
            errors.append(f"evidence.json contains duplicate qid: {qid}")
        evidence_by_qid[qid] = record

    csv_qids = [row.get("qid", "") for row in question_rows]
    if len(set(csv_qids)) != len(csv_qids):
        errors.append("answer.csv contains duplicate question qids")
    if len(question_rows) != len(evidence_by_qid):
        errors.append(
            f"answer.csv question row count ({len(question_rows)}) does not match evidence records ({len(evidence_by_qid)})"
        )
    csv_qid_set = set(csv_qids)
    evidence_qid_set = set(evidence_by_qid)
    if csv_qid_set != evidence_qid_set:
        errors.append(
            "answer.csv and evidence.json qid sets differ: "
            f"csv_only={sorted(csv_qid_set - evidence_qid_set)} "
            f"evidence_only={sorted(evidence_qid_set - csv_qid_set)}"
        )
    manifest_qids_raw = manifest.get("qids", [])
    if not isinstance(manifest_qids_raw, list):
        errors.append("run_manifest.qids must be a list")
        manifest_qids: list[str] = []
    else:
        manifest_qids = [str(qid) for qid in manifest_qids_raw]
    if manifest_qids and set(manifest_qids) != csv_qid_set:
        errors.append("run_manifest.qids does not match answer.csv qids")

    requires_official = (
        manifest.get("submission_scope") == "official_group_a"
        or manifest.get("requested_scope") == "all"
    )
    if requires_official:
        official_qids = [str(q["qid"]) for q in load_all_questions()]
        official_set = set(official_qids)
        if csv_qid_set != official_set:
            errors.append(
                "artifact qids do not equal official group_a qids: "
                f"missing={sorted(official_set - csv_qid_set)} "
                f"unexpected={sorted(csv_qid_set - official_set)}"
            )
        if csv_qids != official_qids:
            errors.append("answer.csv qid order does not match official group_a order")
    success_count = _to_int(manifest.get("success_count", len(question_rows)), "run_manifest.success_count", errors)
    if success_count != len(question_rows):
        errors.append(
            f"run_manifest success_count ({success_count}) does not match answer.csv question rows ({len(question_rows)})"
        )

    row_prompt_sum = 0
    row_completion_sum = 0
    row_total_sum = 0
    for row in question_rows:
        qid = row.get("qid", "")
        record = evidence_by_qid.get(qid)
        if record is None:
            errors.append(f"answer.csv qid {qid!r} missing from evidence.json")
            continue
        answer = row.get("answer", "")
        if answer != str(record.get("answer", "")):
            errors.append(f"{qid}: answer.csv answer {answer!r} != evidence answer {record.get('answer')!r}")

        try:
            validate_answer_format(
                answer,
                str(record.get("answer_format", "")),
                record.get("options", {}) if isinstance(record.get("options"), dict) else {},
            )
        except ValueError as exc:
            errors.append(f"{qid}: invalid answer format: {exc}")

        row_prompt = _to_int(row.get("prompt_tokens"), f"{qid}.prompt_tokens", errors)
        row_completion = _to_int(row.get("completion_tokens"), f"{qid}.completion_tokens", errors)
        row_total = _to_int(row.get("total_tokens"), f"{qid}.total_tokens", errors)
        if row_prompt + row_completion != row_total:
            errors.append(
                f"{qid}: answer.csv prompt_tokens + completion_tokens must equal total_tokens"
            )
        row_prompt_sum += row_prompt
        row_completion_sum += row_completion
        row_total_sum += row_total

        record_prompt = _to_int(record.get("prompt_tokens"), f"{qid}.evidence.prompt_tokens", errors)
        record_completion = _to_int(record.get("completion_tokens"), f"{qid}.evidence.completion_tokens", errors)
        record_total = _to_int(record.get("total_tokens"), f"{qid}.evidence.total_tokens", errors)
        if record_prompt + record_completion != record_total:
            errors.append(
                f"{qid}: evidence prompt_tokens + completion_tokens must equal total_tokens"
            )
        if (row_prompt, row_completion, row_total) != (
            record_prompt,
            record_completion,
            record_total,
        ):
            errors.append(f"{qid}: token values differ between answer.csv and evidence.json")
        if row_prompt <= 0 or row_total <= 0:
            errors.append(f"{qid}: real Qwen submission requires prompt_tokens and total_tokens > 0")
        if row_completion < 0:
            errors.append(f"{qid}: completion_tokens must be non-negative")

        record_mode = record.get("mode")
        if record_mode != "qwen":
            errors.append(f"{qid}: evidence mode must be qwen before upload, got {record_mode!r}")
        if record_mode == "dry_run_mock":
            errors.append(f"{qid}: dry_run_mock record must never be uploaded")
        if _contains_placeholder(record):
            errors.append(f"{qid}: evidence record contains dry-run/mock placeholder content")

    summary_prompt = _to_int(summary.get("prompt_tokens"), "summary.prompt_tokens", errors)
    summary_completion = _to_int(summary.get("completion_tokens"), "summary.completion_tokens", errors)
    summary_total = _to_int(summary.get("total_tokens"), "summary.total_tokens", errors)
    if summary_prompt + summary_completion != summary_total:
        errors.append("summary prompt_tokens + completion_tokens must equal total_tokens")
    if (summary_prompt, summary_completion, summary_total) != (
        row_prompt_sum,
        row_completion_sum,
        row_total_sum,
    ):
        errors.append(
            "summary token values do not equal sum of question rows: "
            f"summary=({summary_prompt},{summary_completion},{summary_total}) "
            f"sum=({row_prompt_sum},{row_completion_sum},{row_total_sum})"
        )
    if summary_total <= 0:
        errors.append("summary total_tokens must be > 0 for a real Qwen submission")

    manifest_totals = (
        _to_int(manifest.get("total_prompt_tokens", 0), "run_manifest.total_prompt_tokens", errors),
        _to_int(manifest.get("total_completion_tokens", 0), "run_manifest.total_completion_tokens", errors),
        _to_int(manifest.get("total_tokens", 0), "run_manifest.total_tokens", errors),
    )
    if manifest_totals[0] + manifest_totals[1] != manifest_totals[2]:
        errors.append(
            "run_manifest total_prompt_tokens + total_completion_tokens must equal total_tokens"
        )
    if manifest_totals != (summary_prompt, summary_completion, summary_total):
        errors.append(
            f"run_manifest token totals {manifest_totals} do not match answer.csv summary "
            f"{(summary_prompt, summary_completion, summary_total)}"
        )

    record_models = {
        str(record.get("model", ""))
        for record in evidence_records
        if isinstance(record, dict) and str(record.get("model", ""))
    }
    manifest_model = str(manifest.get("model", ""))
    if manifest_model and manifest_model != "mixed" and record_models and record_models != {manifest_model}:
        errors.append(
            f"run_manifest model {manifest_model!r} does not match evidence models {sorted(record_models)}"
        )

    parent_version = manifest.get("parent_version")
    if parent_version is not None:
        required_lineage_fields = [
            "parent_artifact_dir",
            "parent_artifact_sha256",
            "rerun_artifact_dir",
            "rerun_artifact_sha256",
            "experiment_id",
            "experiment_pipeline_version",
            "rerun_qids",
            "merge_tool_version",
            "per_record_lineage",
        ]
        for field in required_lineage_fields:
            if field not in manifest:
                errors.append(f"run_manifest lineage missing field: {field}")
        rerun_raw = manifest.get("rerun_qids", [])
        rerun_set = {str(qid) for qid in rerun_raw} if isinstance(rerun_raw, list) else set()
        lineage = manifest.get("per_record_lineage", {})
        if not isinstance(lineage, dict) or set(lineage) != csv_qid_set:
            errors.append("per_record_lineage qids do not match artifact qids")
            lineage = {}
        for qid in csv_qids:
            item = lineage.get(qid, {}) if isinstance(lineage, dict) else {}
            expected_kind = "rerun" if qid in rerun_set else "parent"
            if not isinstance(item, dict) or item.get("source_kind") != expected_kind:
                errors.append(f"{qid}: lineage source_kind must be {expected_kind}")
                continue
            if not str(item.get("source_run_id", "")):
                errors.append(f"{qid}: lineage source_run_id is required")
            if qid in rerun_set:
                expected_version = str(manifest.get("experiment_pipeline_version", ""))
                if item.get("source_pipeline_version") != expected_version:
                    errors.append(f"{qid}: rerun lineage pipeline version mismatch")
            elif not str(item.get("source_pipeline_version", "")):
                errors.append(f"{qid}: parent lineage pipeline version is required")

        if manifest.get("pipeline_version") != manifest.get("experiment_pipeline_version"):
            errors.append("run_manifest pipeline_version must equal experiment_pipeline_version")

        parent_dir = _resolve_manifest_path(manifest.get("parent_artifact_dir"))
        expected_hashes = manifest.get("parent_artifact_sha256", {})
        if parent_dir is None or not parent_dir.is_dir():
            errors.append(f"parent_artifact_dir is unavailable: {parent_dir}")
        elif not isinstance(expected_hashes, dict):
            errors.append("parent_artifact_sha256 must be an object")
        else:
            parent_paths = {
                "answer_csv": parent_dir / "answer.csv",
                "evidence_json": parent_dir / "evidence.json",
                "run_manifest_json": parent_dir / "run_manifest.json",
            }
            for label, path in parent_paths.items():
                if not path.is_file():
                    errors.append(f"parent artifact missing: {path}")
                elif expected_hashes.get(label) != _sha256(path):
                    errors.append(f"parent artifact SHA256 mismatch: {label}")
            if all(path.is_file() for path in parent_paths.values()):
                parent_rows_all = _read_answer_csv(parent_paths["answer_csv"], errors)
                parent_rows = {row.get("qid", ""): row for row in parent_rows_all[1:]}
                parent_records_raw = _load_json(parent_paths["evidence_json"])
                parent_records = {
                    str(record.get("qid", "")): record
                    for record in parent_records_raw
                    if isinstance(record, dict)
                } if isinstance(parent_records_raw, list) else {}
                current_rows = {row.get("qid", ""): row for row in question_rows}
                for qid in csv_qid_set - rerun_set:
                    if current_rows.get(qid) != parent_rows.get(qid):
                        errors.append(f"{qid}: non-rerun answer/token row differs from parent")
                    if evidence_by_qid.get(qid) != parent_records.get(qid):
                        errors.append(f"{qid}: non-rerun evidence record differs from parent")

        rerun_dir = _resolve_manifest_path(manifest.get("rerun_artifact_dir"))
        rerun_hashes = manifest.get("rerun_artifact_sha256", {})
        if rerun_set and (rerun_dir is None or not rerun_dir.is_dir()):
            errors.append(f"rerun_artifact_dir is unavailable: {rerun_dir}")
        elif rerun_set and not isinstance(rerun_hashes, dict):
            errors.append("rerun_artifact_sha256 must be an object")
        elif rerun_set and rerun_dir is not None:
            rerun_paths = {
                "answer_csv": rerun_dir / "answer.csv",
                "evidence_json": rerun_dir / "evidence.json",
                "run_manifest_json": rerun_dir / "run_manifest.json",
            }
            for label, path in rerun_paths.items():
                if not path.is_file():
                    errors.append(f"rerun artifact missing: {path}")
                elif rerun_hashes.get(label) != _sha256(path):
                    errors.append(f"rerun artifact SHA256 mismatch: {label}")
            if all(path.is_file() for path in rerun_paths.values()):
                rerun_rows_all = _read_answer_csv(rerun_paths["answer_csv"], errors)
                rerun_rows = {row.get("qid", ""): row for row in rerun_rows_all[1:]}
                rerun_records_raw = _load_json(rerun_paths["evidence_json"])
                rerun_records = {
                    str(record.get("qid", "")): record
                    for record in rerun_records_raw
                    if isinstance(record, dict)
                } if isinstance(rerun_records_raw, list) else {}
                current_rows = {row.get("qid", ""): row for row in question_rows}
                for qid in rerun_set:
                    if current_rows.get(qid) != rerun_rows.get(qid):
                        errors.append(f"{qid}: rerun answer/token row differs from rerun artifact")
                    if evidence_by_qid.get(qid) != rerun_records.get(qid):
                        errors.append(f"{qid}: rerun evidence record differs from rerun artifact")

    return _report(len(errors) == 0, errors, warnings, len(question_rows), summary_total)


def _report(
    ok: bool,
    errors: list[str],
    warnings: list[str],
    question_count: int,
    total_tokens: int,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "question_count": question_count,
        "total_tokens": total_tokens,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agent.validate_submission",
        description="Validate answer.csv/evidence.json/run_manifest.json before upload.",
    )
    parser.add_argument("answer_csv", nargs="?", default=str(ANSWER_CSV_PATH))
    parser.add_argument("--evidence", default=str(EVIDENCE_JSON_PATH))
    parser.add_argument("--manifest", default=str(RUN_MANIFEST_PATH))
    args = parser.parse_args(argv)

    report = validate_submission_files(args.answer_csv, args.evidence, args.manifest)
    status = "VALID" if report["ok"] else "INVALID"
    print(f"[{status}] questions={report['question_count']} total_tokens={report['total_tokens']}")
    for warning in report["warnings"]:
        print(f"[warn] {warning}")
    for error in report["errors"]:
        print(f"[error] {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
