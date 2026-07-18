from __future__ import annotations

from agent.evaluate_e009_prospective_churn import evaluate_churn
from agent.evaluate_e009_prospective_scored import evaluate_scored, token_factor
from agent.run_e009_prospective_arm import (
    PROSPECTIVE_QIDS,
    PROSPECTIVE_SELECTION_PATH,
    _load_selection,
    _verify_frozen_inputs,
)


def _row(qid: str, answer: str = "A") -> dict:
    return {
        "qid": qid,
        "answer": answer,
        "option_judgments": {
            option: {"judgment": "support" if option in answer else "refute"}
            for option in "ABCD"
        },
        "retrieval": {
            option: {"evidence": [{"doc_id": "d", "chunk_id": f"{qid}-{option}", "text": "x"}]}
            for option in "ABCD"
        },
    }


def _bundle(attempt: str) -> dict:
    return {
        "rows": [_row(qid) for qid in PROSPECTIVE_QIDS],
        "observations": {"total_tokens": 100},
        "receipt": {
            "primary_claim_sha256": "p",
            "primary_anchor": None if attempt == "primary" else {"bound": True},
            "repeat_claim_sha256": None if attempt == "primary" else "r",
            "code_sha256": "code",
            "model_sha256": "model",
            "input_artifacts_sha256": "inputs",
            "run_freeze_sha256": "freeze",
        },
        "served_models": ["qwen-plus"],
        "manifest": {
            "started_at": "2026-07-18T10:00:00+08:00" if attempt == "primary" else "2026-07-18T10:30:00+08:00",
            "finished_at": "2026-07-18T10:20:00+08:00" if attempt == "primary" else "2026-07-18T10:50:00+08:00",
            "config": {
                "attempt": attempt,
                "attempt_nonce": attempt,
                "output_dir": attempt,
                "primary_anchor": None if attempt == "primary" else {"bound": True},
                "repeat_claim_sha256": None if attempt == "primary" else "r",
                "frozen": True,
            },
        },
    }


def test_selection_is_frozen_fresh_authorized_and_hash_bound():
    selection = _load_selection(PROSPECTIVE_SELECTION_PATH)
    assert tuple(selection["qids"]) == PROSPECTIVE_QIDS
    assert selection["domain_counts"] == {
        "financial_contracts": 4,
        "financial_reports": 4,
        "insurance": 1,
        "regulatory": 3,
        "research": 3,
    }
    assert selection["eligibility"]["known_before_freeze_qids"] == []
    snapshots = _verify_frozen_inputs(PROSPECTIVE_SELECTION_PATH)
    assert all(item["sha256"] for item in snapshots.values())


def test_label_free_churn_keeps_primary_as_only_scoring_arm():
    report = evaluate_churn(_bundle("primary"), _bundle("repeat"))
    assert report["status"] == "PASS"
    assert report["scoring_arm"] == "primary"
    assert report["repeat_non_scoring"] is True
    assert report["primary_repeat_answer_churn_C"] == 0


def test_score_formula_reproduces_65_0912_anchor():
    assert round(70 * token_factor(1_168_763), 4) == 65.0912


def test_scored_gate_requires_both_net_over_churn_and_score_gain():
    parent = {qid: "A" for qid in PROSPECTIVE_QIDS}
    gold = {qid: "A" for qid in PROSPECTIVE_QIDS}
    primary = dict(parent)
    primary[PROSPECTIVE_QIDS[0]] = "B"
    report = evaluate_scored(
        primary_answers=primary,
        parent_answers=parent,
        gold_answers=gold,
        churn_c=0,
        primary_tokens=180_000,
    )
    assert report["N_minus_M"] == -1
    assert report["allow_full_65_multi_expansion"] is False

    gold[PROSPECTIVE_QIDS[0]] = "B"
    gold[PROSPECTIVE_QIDS[1]] = "B"
    primary[PROSPECTIVE_QIDS[1]] = "B"
    report = evaluate_scored(
        primary_answers=primary,
        parent_answers=parent,
        gold_answers=gold,
        churn_c=1,
        primary_tokens=180_000,
    )
    assert report["N_minus_M"] == 2
    assert report["checks"]["N_minus_M_greater_than_C"] is True
    assert report["allow_full_65_multi_expansion"] is True
