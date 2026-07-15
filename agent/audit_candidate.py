"""对产物级合成候选执行实验专属的确定性审计。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from agent.build_cached_rerun_bundle import load_qids
from agent.load_questions import load_all_questions
from agent.paths import bundle_paths
from agent.validate_submission import validate_submission_files


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _answer_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {str(row["qid"]): row for row in rows if row.get("qid") != "summary"}


def _evidence(path: Path) -> dict[str, dict[str, Any]]:
    records = json.loads(path.read_text(encoding="utf-8"))
    return {str(record["qid"]): record for record in records}


def _expected_diff(path: Path) -> dict[str, tuple[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("answer_diff", []) if isinstance(data, dict) else []
    expected: dict[str, tuple[str, str]] = {}
    for item in items:
        qid = str(item["qid"])
        if qid in expected:
            raise ValueError(f"duplicate expected answer diff qid: {qid}")
        expected[qid] = (str(item["from"]), str(item["to"]))
    return expected


def audit_candidate(
    *,
    parent_dir: Path,
    candidate_dir: Path,
    rerun_dir: Path,
    qids_file: Path,
    expected_diff_file: Path,
    pipeline_version: str,
    model: str,
    rerun_answer_format: str,
) -> dict[str, Any]:
    parent_dir = parent_dir.resolve()
    candidate_dir = candidate_dir.resolve()
    rerun_dir = rerun_dir.resolve()
    parent_paths = bundle_paths(parent_dir)
    candidate_paths = bundle_paths(candidate_dir)
    rerun_paths = bundle_paths(rerun_dir)
    for path in (*parent_paths, *candidate_paths, *rerun_paths, qids_file, expected_diff_file):
        if not Path(path).is_file():
            raise FileNotFoundError(path)

    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    def check(name: str, condition: bool, detail: Any) -> None:
        checks.append({"name": name, "passed": bool(condition), "detail": detail})
        if not condition:
            errors.append(f"{name}: {detail}")

    base_report = validate_submission_files(*candidate_paths)
    check("general_submission_validator", base_report["ok"], base_report)

    official = {str(q["qid"]): q for q in load_all_questions()}
    parent_rows = _answer_rows(parent_paths[0])
    candidate_rows = _answer_rows(candidate_paths[0])
    rerun_rows = _answer_rows(rerun_paths[0])
    parent_records = _evidence(parent_paths[1])
    candidate_records = _evidence(candidate_paths[1])
    rerun_records = _evidence(rerun_paths[1])
    candidate_manifest = json.loads(candidate_paths[2].read_text(encoding="utf-8"))
    rerun_manifest = json.loads(rerun_paths[2].read_text(encoding="utf-8"))

    registered_qids = load_qids(qids_file)
    registered_set = set(registered_qids)
    manifest_qids = candidate_manifest.get("rerun_qids", [])
    check(
        "registered_rerun_qids_exact",
        len(registered_qids) == len(registered_set)
        and set(manifest_qids) == registered_set
        and len(manifest_qids) == len(registered_qids),
        {"registered": registered_qids, "manifest": manifest_qids},
    )
    check(
        "rerun_bundle_qids_exact",
        set(rerun_rows) == set(rerun_records) == registered_set
        and set(rerun_manifest.get("qids", [])) == registered_set,
        {
            "rows": sorted(rerun_rows),
            "records": sorted(rerun_records),
            "manifest": sorted(rerun_manifest.get("qids", [])),
        },
    )

    expected = _expected_diff(expected_diff_file)
    actual = {
        qid: (parent_rows[qid]["answer"], candidate_rows[qid]["answer"])
        for qid in parent_rows
        if parent_rows[qid]["answer"] != candidate_rows[qid]["answer"]
    }
    check("answer_diff_exact", actual == expected, {"expected": expected, "actual": actual})
    check(
        "all_other_answers_unchanged",
        len(parent_rows) == 100 and len(parent_rows) - len(actual) == 98,
        {"question_count": len(parent_rows), "unchanged": len(parent_rows) - len(actual)},
    )

    non_rerun = set(parent_rows) - registered_set
    non_rerun_exact = all(
        parent_rows[qid] == candidate_rows[qid]
        and parent_records[qid] == candidate_records[qid]
        for qid in non_rerun
    )
    check("non_rerun_records_exact_parent", non_rerun_exact, {"count": len(non_rerun)})
    rerun_exact = all(
        rerun_rows[qid] == candidate_rows[qid]
        and rerun_records[qid] == candidate_records[qid]
        for qid in registered_set
    )
    check("rerun_records_exact_bundle", rerun_exact, {"count": len(registered_set)})

    metadata_errors: list[str] = []
    token_errors: list[str] = []
    ref_errors: list[str] = []
    for qid, record in candidate_records.items():
        question = official[qid]
        for field in ("domain", "question", "options", "answer_format", "doc_ids"):
            if record.get(field) != question.get(field):
                metadata_errors.append(f"{qid}:{field}")
        prompt = int(record.get("prompt_tokens", 0))
        completion = int(record.get("completion_tokens", 0))
        total = int(record.get("total_tokens", 0))
        if prompt + completion != total:
            token_errors.append(qid)
    for qid in registered_set:
        record = candidate_records[qid]
        if (
            record.get("mode") != "qwen"
            or record.get("model") != model
            or record.get("pipeline_version") != pipeline_version
            or record.get("answer_format") != rerun_answer_format
        ):
            metadata_errors.append(f"{qid}:rerun_identity")
        evidence = record.get("retrieval", {}).get("tf", {}).get("evidence", [])
        if rerun_answer_format == "tf" and not evidence:
            metadata_errors.append(f"{qid}:missing_retrieval")
        refs = record.get("tf_judgment", {}).get("fact_checks", [])
        for fact in refs if isinstance(refs, list) else []:
            for ref in fact.get("evidence_refs", []) if isinstance(fact, dict) else []:
                if not isinstance(ref, int) or ref < 1 or ref > len(evidence):
                    ref_errors.append(f"{qid}:{ref}/{len(evidence)}")
    check("canonical_question_metadata", not metadata_errors, metadata_errors)
    check("per_record_token_arithmetic", not token_errors, token_errors)
    check("evidence_refs_in_range", not ref_errors, ref_errors)

    check(
        "candidate_pipeline_identity",
        candidate_manifest.get("pipeline_version") == pipeline_version
        and candidate_manifest.get("mode") == "qwen"
        and candidate_manifest.get("model") == model,
        {
            "pipeline_version": candidate_manifest.get("pipeline_version"),
            "mode": candidate_manifest.get("mode"),
            "model": candidate_manifest.get("model"),
        },
    )
    check(
        "cache_only_repack_no_api",
        rerun_manifest.get("cache_only") is True
        and rerun_manifest.get("api_calls") == 0
        and rerun_manifest.get("network_calls") == 0
        and rerun_manifest.get("reused_from_cache_count") == len(registered_set),
        {
            "cache_only": rerun_manifest.get("cache_only"),
            "api_calls": rerun_manifest.get("api_calls"),
            "network_calls": rerun_manifest.get("network_calls"),
            "reused": rerun_manifest.get("reused_from_cache_count"),
        },
    )

    return {
        "ok": not errors,
        "errors": errors,
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(1 for item in checks if item["passed"]),
            "question_count": len(candidate_rows),
            "rerun_count": len(registered_set),
            "answer_diff_count": len(actual),
            "unchanged_answer_count": len(parent_rows) - len(actual),
            "candidate_total_tokens": candidate_manifest.get("total_tokens"),
        },
        "answer_diff": [
            {"qid": qid, "from": values[0], "to": values[1]}
            for qid, values in actual.items()
        ],
        "candidate_sha256": {
            "answer.csv": _sha256(candidate_paths[0]),
            "evidence.json": _sha256(candidate_paths[1]),
            "run_manifest.json": _sha256(candidate_paths[2]),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent.audit_candidate")
    parser.add_argument("--parent-dir", required=True)
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--rerun-dir", required=True)
    parser.add_argument("--qids", required=True)
    parser.add_argument("--expected-diff", required=True)
    parser.add_argument("--pipeline-version", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--rerun-answer-format", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        report = audit_candidate(
            parent_dir=Path(args.parent_dir),
            candidate_dir=Path(args.candidate_dir),
            rerun_dir=Path(args.rerun_dir),
            qids_file=Path(args.qids),
            expected_diff_file=Path(args.expected_diff),
            pipeline_version=args.pipeline_version,
            model=args.model,
            rerun_answer_format=args.rerun_answer_format,
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[error] {exc}")
        return 1
    status = "PASS" if report["ok"] else "FAIL"
    print(
        f"[{status}] checks={report['summary']['passed_count']}/{report['summary']['check_count']} "
        f"questions={report['summary']['question_count']} "
        f"answer_diff={report['summary']['answer_diff_count']}"
    )
    for error in report["errors"]:
        print(f"[error] {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
