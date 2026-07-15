"""Batch run tests for Task 6."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agent.load_questions import load_questions_by_domain
from agent.run_submission import (
    CURRENT_PIPELINE_VERSION,
    _build_manifest,
    is_reusable_qwen_result,
    run_questions,
)


def test_load_questions_by_domain_returns_insurance_questions_in_order():
    questions = load_questions_by_domain("insurance")

    assert len(questions) == 20
    assert questions[0]["qid"] == "ins_a_001"
    assert questions[-1]["qid"] == "ins_a_020"
    assert {q["domain"] for q in questions} == {"insurance"}


def test_domain_limit_dry_run_cli_writes_two_question_outputs(tmp_path: Path):
    output_dir = tmp_path / "dry-run"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent.run_submission",
            "--domain",
            "insurance",
            "--limit",
            "2",
            "--dry-run",
            "--output-dir",
            str(output_dir),
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "requested_scope=domain:insurance limit=2" in result.stdout
    answer_csv = (output_dir / "answer.csv").read_text(encoding="utf-8")
    assert "ins_a_001" in answer_csv
    assert "ins_a_002" in answer_csv
    assert "ins_a_003" not in answer_csv
    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["requested_scope"] == "domain:insurance limit=2"
    assert manifest["success_count"] == 2
    assert manifest["failure_count"] == 0
    assert manifest["low_confidence_count"] == 2
    assert manifest["mode"] == "dry_run_mock"


def test_hide_doc_ids_cli_uses_card_retrieval_and_records_manifest(tmp_path: Path):
    output_dir = tmp_path / "b-mode"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent.run_submission",
            "--qid",
            "ins_a_001",
            "--dry-run",
            "--hide-doc-ids",
            "--output-dir",
            str(output_dir),
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    evidence = json.loads((output_dir / "evidence.json").read_text(encoding="utf-8"))
    assert manifest["requested_scope"] == "single_question:ins_a_001 hide_doc_ids"
    assert manifest["document_selection_mode"] == "card_retrieval_k12"
    assert manifest["hide_doc_ids_simulation"] is True
    assert evidence[0]["doc_ids"] == []
    assert any(
        option["evidence"]
        for option in evidence[0]["retrieval"].values()
    )


def test_unknown_domain_cli_returns_nonzero():
    result = subprocess.run(
        [sys.executable, "-m", "agent.run_submission", "--domain", "no_such_domain", "--dry-run"],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "no_such_domain" in result.stderr


def test_official_output_rejects_partial_or_dry_run_scope():
    dry = subprocess.run(
        [sys.executable, "-m", "agent.run_submission", "--all", "--dry-run", "--official-output"],
        text=True,
        capture_output=True,
    )
    partial = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent.run_submission",
            "--qid",
            "ins_a_007",
            "--use-qwen",
            "--official-output",
            "--experiment-id",
            "E-test",
        ],
        text=True,
        capture_output=True,
    )

    assert dry.returncode == 1
    assert "requires --use-qwen" in dry.stderr
    assert partial.returncode == 1
    assert "unbounded --all" in partial.stderr


def test_run_questions_continues_after_single_question_failure(monkeypatch):
    questions = [
        {"qid": "q1", "domain": "insurance", "options": {"A": "a"}, "answer_format": "mcq"},
        {"qid": "q2", "domain": "insurance", "options": {"A": "a"}, "answer_format": "mcq"},
    ]

    def fake_solve(question, chunks, use_qwen, top_k=5, client=None):
        if question["qid"] == "q1":
            raise ValueError("boom")
        return {
            "qid": question["qid"],
            "domain": question["domain"],
            "answer_format": question["answer_format"],
            "mode": "dry_run_mock",
            "model": "none",
            "question": "",
            "options": question["options"],
            "doc_ids": [],
            "option_judgments": {"A": {"judgment": "support", "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}},
            "answer": "A",
            "warnings": [],
            "low_confidence": False,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "evidence": [],
            "retrieval": {},
        }

    monkeypatch.setattr("agent.run_submission.solve_question", fake_solve)

    results, failures = run_questions(questions, chunks=[], use_qwen=False, top_k=5, client=None)

    assert [r["qid"] for r in results] == ["q2"]
    assert len(failures) == 1
    assert failures[0]["qid"] == "q1"
    assert "boom" in failures[0]["error"]


def _qwen_result(qid: str, *, tokens: int = 120, judgment: str = "support", error: str | None = None) -> dict:
    return {
        "qid": qid,
        "domain": "insurance",
        "answer_format": "mcq",
        "mode": "qwen",
        "model": "qwen-plus",
        "pipeline_version": CURRENT_PIPELINE_VERSION,
        "question": "question",
        "options": {"A": "a"},
        "doc_ids": [],
        "option_judgments": {
            "A": {
                "judgment": judgment,
                "rationale": "",
                "evidence_refs": [],
                "prompt_tokens": tokens,
                "completion_tokens": 1 if tokens else 0,
                "total_tokens": tokens,
                "error": error,
            }
        },
        "answer": "A",
        "warnings": [],
        "low_confidence": False,
        "prompt_tokens": tokens,
        "completion_tokens": 1 if tokens else 0,
        "total_tokens": tokens,
        "evidence": [],
        "retrieval": {},
    }


def test_is_reusable_qwen_result_rejects_zero_token_and_error_judgments():
    assert is_reusable_qwen_result(_qwen_result("q1"), expected_qid="q1")[0] is True
    assert is_reusable_qwen_result(_qwen_result("q1", tokens=0), expected_qid="q1")[0] is False
    assert (
        is_reusable_qwen_result(
            _qwen_result("q1", judgment="error", error="Qwen 调用失败: AccessDenied"),
            expected_qid="q1",
        )[0]
        is False
    )
    assert is_reusable_qwen_result({**_qwen_result("q1"), "mode": "dry_run_mock"}, expected_qid="q1")[0] is False


def test_is_reusable_qwen_result_rejects_mismatched_pipeline_version():
    sample = {**_qwen_result("q1"), "pipeline_version": "v0"}

    reusable, reason = is_reusable_qwen_result(sample, expected_qid="q1")

    assert reusable is False
    assert "pipeline_version" in reason


def test_run_questions_resume_reuses_valid_samples_and_reruns_bad_samples(tmp_path, monkeypatch):
    questions = [
        {"qid": "q1", "domain": "insurance", "options": {"A": "a"}, "answer_format": "mcq"},
        {"qid": "q2", "domain": "insurance", "options": {"A": "a"}, "answer_format": "mcq"},
    ]
    (tmp_path / "q1.json").write_text(json.dumps(_qwen_result("q1"), ensure_ascii=False), encoding="utf-8")
    (tmp_path / "q2.json").write_text(
        json.dumps(_qwen_result("q2", tokens=0, judgment="error", error="AccessDenied"), ensure_ascii=False),
        encoding="utf-8",
    )
    solved: list[str] = []

    def fake_retrieve(question, chunks, top_k=5):
        return {"options": {"A": {"option_text": "a", "evidence": [{"chunk_id": "c1"}]}}}

    def fake_solve(question, chunks, use_qwen, top_k=5, client=None):
        solved.append(question["qid"])
        return _qwen_result(question["qid"], tokens=99)

    monkeypatch.setattr("agent.run_submission.REASONING_SAMPLES_DIR", tmp_path)
    monkeypatch.setattr("agent.run_submission.retrieve_for_question", fake_retrieve)
    monkeypatch.setattr("agent.run_submission.solve_question", fake_solve)
    monkeypatch.setattr("agent.run_submission.save_reasoning_sample", lambda result, path=None: tmp_path / f"{result['qid']}.json")

    results, failures = run_questions(
        questions, chunks=[], use_qwen=True, top_k=5, client=None, resume=True
    )

    assert failures == []
    assert [r["qid"] for r in results] == ["q1", "q2"]
    assert solved == ["q2"]
    assert results[0]["_reused_from_cache"] is True
    assert results[0]["retrieval"]["A"]["evidence"] == [{"chunk_id": "c1"}]


def test_run_questions_rerun_qids_force_rerun_even_when_cache_is_reusable(tmp_path, monkeypatch):
    questions = [
        {"qid": "q1", "domain": "insurance", "options": {"A": "a"}, "answer_format": "mcq"},
        {"qid": "q2", "domain": "insurance", "options": {"A": "a"}, "answer_format": "mcq"},
    ]
    (tmp_path / "q1.json").write_text(json.dumps(_qwen_result("q1"), ensure_ascii=False), encoding="utf-8")
    (tmp_path / "q2.json").write_text(json.dumps(_qwen_result("q2"), ensure_ascii=False), encoding="utf-8")
    solved: list[str] = []

    def fake_retrieve(question, chunks, top_k=5):
        return {"options": {"A": {"option_text": "a", "evidence": [{"chunk_id": "c1"}]}}}

    def fake_solve(question, chunks, use_qwen, top_k=5, client=None):
        solved.append(question["qid"])
        return _qwen_result(question["qid"], tokens=99)

    monkeypatch.setattr("agent.run_submission.REASONING_SAMPLES_DIR", tmp_path)
    monkeypatch.setattr("agent.run_submission.retrieve_for_question", fake_retrieve)
    monkeypatch.setattr("agent.run_submission.solve_question", fake_solve)
    monkeypatch.setattr("agent.run_submission.save_reasoning_sample", lambda result, path=None: tmp_path / f"{result['qid']}.json")

    results, failures = run_questions(
        questions,
        chunks=[],
        use_qwen=True,
        top_k=5,
        client=None,
        resume=True,
        rerun_qids={"q2"},
    )

    assert failures == []
    assert solved == ["q2"]
    assert results[0]["_reused_from_cache"] is True
    assert "_reused_from_cache" not in results[1]


def test_manifest_records_reused_pipeline_versions():
    reused = {**_qwen_result("q1"), "_reused_from_cache": True, "_reused_pipeline_version": "v0"}
    fresh = _qwen_result("q2")

    manifest = _build_manifest(
        run_started_at="2026-07-05T00:00:00+08:00",
        mode="qwen",
        requested_scope="all",
        qids=["q1", "q2"],
        results=[reused, fresh],
        failures=[],
        resume=True,
    )

    assert manifest["pipeline_version"] == CURRENT_PIPELINE_VERSION
    assert manifest["reused_pipeline_versions"] == {"v0": 1}
