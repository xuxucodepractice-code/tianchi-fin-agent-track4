"""Batch run tests for Task 6."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agent.load_questions import load_questions_by_domain
from agent.run_submission import is_reusable_qwen_result, run_questions


def test_load_questions_by_domain_returns_insurance_questions_in_order():
    questions = load_questions_by_domain("insurance")

    assert len(questions) == 20
    assert questions[0]["qid"] == "ins_a_001"
    assert questions[-1]["qid"] == "ins_a_020"
    assert {q["domain"] for q in questions} == {"insurance"}


def test_domain_limit_dry_run_cli_writes_two_question_outputs():
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
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "requested_scope=domain:insurance limit=2" in result.stdout
    answer_csv = Path("submission/answer.csv").read_text(encoding="utf-8")
    assert "ins_a_001" in answer_csv
    assert "ins_a_002" in answer_csv
    assert "ins_a_003" not in answer_csv
    manifest = json.loads(Path("submission/run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["requested_scope"] == "domain:insurance limit=2"
    assert manifest["success_count"] == 2
    assert manifest["failure_count"] == 0
    assert manifest["low_confidence_count"] == 2
    assert manifest["mode"] == "dry_run_mock"


def test_unknown_domain_cli_returns_nonzero():
    result = subprocess.run(
        [sys.executable, "-m", "agent.run_submission", "--domain", "no_such_domain", "--dry-run"],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "no_such_domain" in result.stderr


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
    monkeypatch.setattr("agent.run_submission.save_reasoning_sample", lambda result: tmp_path / f"{result['qid']}.json")

    results, failures = run_questions(
        questions, chunks=[], use_qwen=True, top_k=5, client=None, resume=True
    )

    assert failures == []
    assert [r["qid"] for r in results] == ["q1", "q2"]
    assert solved == ["q2"]
    assert results[0]["_reused_from_cache"] is True
    assert results[0]["retrieval"]["A"]["evidence"] == [{"chunk_id": "c1"}]
