from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.evaluate_e010_prospective_scored import token_factor
from agent.load_questions import load_all_questions
from agent.reason_e007_reference_integrity import build_option_messages
from agent.run_e010_prospective_arm import (
    PROSPECTIVE_QIDS,
    PROSPECTIVE_SELECTION_PATH,
    _load_selection,
    _verify_frozen_inputs,
)


def test_e010_selection_is_fresh_hash_bound_and_has_explicit_coverage_gap():
    selection = _load_selection(PROSPECTIVE_SELECTION_PATH)
    assert tuple(selection["qids"]) == PROSPECTIVE_QIDS
    assert selection["domain_counts"] == {
        "financial_contracts": 4,
        "financial_reports": 4,
        "insurance": 0,
        "regulatory": 4,
        "research": 3,
    }
    assert selection["eligibility"]["excluded_e009_selection"] is True
    assert selection["eligibility"]["known_before_freeze_qids"] == []
    assert all(item["sha256"] for item in _verify_frozen_inputs(PROSPECTIVE_SELECTION_PATH).values())


def test_trace_prompt_replay_uses_model_evidence_not_context_evidence():
    call = {
        "context": {
            "qid": "q1",
            "option_key": "A",
            "option_text": "选项",
        },
        "model_evidence": [{"doc_id": "d1", "chunk_id": "c1", "text": "证据"}],
    }
    question = {"qid": "q1", "question": "题目", "doc_ids": ["d1"]}
    actual = build_option_messages(
        question, "A", "选项", call["model_evidence"], arm="treatment"
    )
    old = build_option_messages(
        question,
        "A",
        "选项",
        list(call["context"].get("evidence") or []),
        arm="treatment",
    )
    assert old != actual
    assert build_option_messages(
        question,
        "A",
        "选项",
        list(call.get("model_evidence") or []),
        arm="treatment",
    ) == actual


def test_immutable_e009_trace_replays_60_of_60_with_new_binding():
    root = Path("outputs/experiments/E009_multi_document_order_binding/prospective_primary_01")
    observations_path = root / "observations.json"
    if not observations_path.is_file():
        pytest.skip("immutable E009 runtime artifacts are not present in this checkout")
    observations = json.loads(observations_path.read_text(encoding="utf-8"))
    trace_dir = Path(observations["agent_trace"]["trace_dir"])
    calls = [
        json.loads(line)
        for line in (trace_dir / "calls.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    questions = {str(q["qid"]): q for q in load_all_questions()}
    old_pass = 0
    new_pass = 0
    for call in calls:
        context = call["context"]
        args = (questions[context["qid"]], context["option_key"], context["option_text"])
        old = build_option_messages(
            *args, list(context.get("evidence") or []), arm="treatment"
        )
        new = build_option_messages(
            *args, list(call.get("model_evidence") or []), arm="treatment"
        )
        old_pass += old == call["request_payload"]["messages"]
        new_pass += new == call["request_payload"]["messages"]
    assert len(calls) == 60
    assert old_pass == 0
    assert new_pass == 60


def test_score_formula_still_reproduces_governed_parent_anchor():
    assert round(70 * token_factor(1_168_763), 4) == 65.0912
