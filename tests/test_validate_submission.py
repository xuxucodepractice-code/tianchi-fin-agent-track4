"""Submission safety validator tests."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from agent.validate_submission import validate_submission_files


def _write_csv(path: Path, rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["qid", "answer", "prompt_tokens", "completion_tokens", "total_tokens"])
        for row in rows:
            writer.writerow(row)


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _valid_record(qid: str = "ins_a_007") -> dict:
    return {
        "qid": qid,
        "domain": "insurance",
        "question": "关于保单贷款，以下哪些说法正确？",
        "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
        "answer_format": "multi",
        "doc_ids": ["1", "2", "16"],
        "answer": "BC",
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "mode": "qwen",
        "model": "qwen-plus",
        "evidence": [],
        "retrieval": {},
        "option_judgments": {},
        "warnings": [],
        "low_confidence": False,
    }


def _write_valid_bundle(tmp_path: Path) -> tuple[Path, Path, Path]:
    answer_csv = tmp_path / "answer.csv"
    evidence_json = tmp_path / "evidence.json"
    manifest_json = tmp_path / "run_manifest.json"
    _write_csv(answer_csv, [["summary", "", 100, 20, 120], ["ins_a_007", "BC", 100, 20, 120]])
    _write_json(evidence_json, [_valid_record()])
    _write_json(
        manifest_json,
        {
            "mode": "qwen",
            "requested_scope": "single_question:ins_a_007",
            "success_count": 1,
            "failure_count": 0,
            "total_prompt_tokens": 100,
            "total_completion_tokens": 20,
            "total_tokens": 120,
        },
    )
    return answer_csv, evidence_json, manifest_json


def test_valid_qwen_submission_passes(tmp_path: Path):
    answer_csv, evidence_json, manifest_json = _write_valid_bundle(tmp_path)

    report = validate_submission_files(answer_csv, evidence_json, manifest_json)

    assert report["ok"] is True
    assert report["errors"] == []
    assert report["question_count"] == 1
    assert report["total_tokens"] == 120


def test_dry_run_submission_is_rejected(tmp_path: Path):
    answer_csv, evidence_json, manifest_json = _write_valid_bundle(tmp_path)
    records = json.loads(evidence_json.read_text(encoding="utf-8"))
    records[0]["mode"] = "dry_run_mock"
    records[0]["prompt_tokens"] = records[0]["completion_tokens"] = records[0]["total_tokens"] = 0
    _write_json(evidence_json, records)
    _write_json(
        manifest_json,
        {
            "mode": "dry_run_mock",
            "success_count": 1,
            "failure_count": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
        },
    )

    report = validate_submission_files(answer_csv, evidence_json, manifest_json)

    assert report["ok"] is False
    assert any("dry_run_mock" in error for error in report["errors"])
    assert any("token" in error.lower() or "Token" in error for error in report["errors"])


def test_summary_token_mismatch_is_rejected(tmp_path: Path):
    answer_csv, evidence_json, manifest_json = _write_valid_bundle(tmp_path)
    _write_csv(answer_csv, [["summary", "", 999, 20, 1019], ["ins_a_007", "BC", 100, 20, 120]])

    report = validate_submission_files(answer_csv, evidence_json, manifest_json)

    assert report["ok"] is False
    assert any("summary" in error for error in report["errors"])


def test_per_question_token_arithmetic_is_rejected(tmp_path: Path):
    answer_csv, evidence_json, manifest_json = _write_valid_bundle(tmp_path)
    _write_csv(answer_csv, [["summary", "", 100, 20, 120], ["ins_a_007", "BC", 100, 20, 121]])
    records = json.loads(evidence_json.read_text(encoding="utf-8"))
    records[0]["total_tokens"] = 121
    _write_json(evidence_json, records)

    report = validate_submission_files(answer_csv, evidence_json, manifest_json)

    assert report["ok"] is False
    assert any("prompt_tokens + completion_tokens" in error for error in report["errors"])


def test_manifest_token_arithmetic_is_rejected(tmp_path: Path):
    answer_csv, evidence_json, manifest_json = _write_valid_bundle(tmp_path)
    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    manifest["total_tokens"] = 121
    _write_json(manifest_json, manifest)

    report = validate_submission_files(answer_csv, evidence_json, manifest_json)

    assert report["ok"] is False
    assert any("run_manifest total_prompt_tokens" in error for error in report["errors"])


def test_invalid_answer_format_is_rejected(tmp_path: Path):
    answer_csv, evidence_json, manifest_json = _write_valid_bundle(tmp_path)
    _write_csv(answer_csv, [["summary", "", 100, 20, 120], ["ins_a_007", "B,C", 100, 20, 120]])

    report = validate_submission_files(answer_csv, evidence_json, manifest_json)

    assert report["ok"] is False
    assert any("answer" in error.lower() or "答案" in error for error in report["errors"])


def test_missing_evidence_record_is_rejected(tmp_path: Path):
    answer_csv, evidence_json, manifest_json = _write_valid_bundle(tmp_path)
    _write_json(evidence_json, [])

    report = validate_submission_files(answer_csv, evidence_json, manifest_json)

    assert report["ok"] is False
    assert any("evidence" in error.lower() or "ins_a_007" in error for error in report["errors"])


def test_official_scope_rejects_bundle_that_omits_official_qids(tmp_path: Path):
    answer_csv, evidence_json, manifest_json = _write_valid_bundle(tmp_path)
    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    manifest["submission_scope"] = "official_group_a"
    manifest["qids"] = ["ins_a_007"]
    _write_json(manifest_json, manifest)

    report = validate_submission_files(answer_csv, evidence_json, manifest_json)

    assert report["ok"] is False
    assert any("official group_a" in error for error in report["errors"])


def test_manifest_qids_must_match_csv(tmp_path: Path):
    answer_csv, evidence_json, manifest_json = _write_valid_bundle(tmp_path)
    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    manifest["qids"] = ["wrong_qid"]
    _write_json(manifest_json, manifest)

    report = validate_submission_files(answer_csv, evidence_json, manifest_json)

    assert report["ok"] is False
    assert any("run_manifest.qids" in error for error in report["errors"])


def test_placeholder_rationale_is_rejected(tmp_path: Path):
    answer_csv, evidence_json, manifest_json = _write_valid_bundle(tmp_path)
    records = json.loads(evidence_json.read_text(encoding="utf-8"))
    records[0]["option_judgments"] = {
        "A": {"judgment": "insufficient", "rationale": "dry-run 占位：未调用 Qwen"}
    }
    _write_json(evidence_json, records)

    report = validate_submission_files(answer_csv, evidence_json, manifest_json)

    assert report["ok"] is False
    assert any("placeholder" in error for error in report["errors"])


def test_cli_exits_nonzero_for_invalid_submission(tmp_path: Path):
    answer_csv, evidence_json, manifest_json = _write_valid_bundle(tmp_path)
    _write_json(manifest_json, {"mode": "dry_run_mock", "success_count": 1, "failure_count": 0})

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent.validate_submission",
            str(answer_csv),
            "--evidence",
            str(evidence_json),
            "--manifest",
            str(manifest_json),
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "INVALID" in result.stdout
