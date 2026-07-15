"""Offline rerun-list selection tests for v1-S1."""

from __future__ import annotations

from agent.build_rerun_list import select_rerun_qids


def test_select_rerun_qids_includes_low_jaccard_changes():
    questions = [
        {"qid": "q1", "domain": "regulatory", "doc_ids": ["d1"], "answer_format": "mcq"},
    ]
    baseline = {
        "q1": {"retrieval": {"A": {"evidence": [{"chunk_id": "old_1"}, {"chunk_id": "old_2"}]}}}
    }
    current = {
        "q1": {"options": {"A": {"evidence": [{"chunk_id": "new_1"}, {"chunk_id": "new_2"}]}}}
    }

    qids, reasons = select_rerun_qids(questions, baseline, current, jaccard_threshold=0.6)

    assert qids == ["q1"]
    assert any(reason.startswith("retrieval_jaccard=") for reason in reasons["q1"])


def test_select_rerun_qids_includes_s1_seed_and_multi_entity_questions():
    questions = [
        {"qid": "reg_a_006", "domain": "regulatory", "doc_ids": ["csrc_0009_att1"], "answer_format": "mcq"},
        {"qid": "ins_a_001", "domain": "insurance", "doc_ids": ["1", "2", "15", "16"], "answer_format": "mcq"},
        {"qid": "fc_a_001", "domain": "financial_contracts", "doc_ids": ["text01", "text02"], "answer_format": "multi"},
    ]

    qids, reasons = select_rerun_qids(questions, {}, {}, jaccard_threshold=0.6)

    assert qids == ["ins_a_001", "reg_a_006"]
    assert reasons["reg_a_006"] == ["s1_seed"]
    assert reasons["ins_a_001"] == ["multi_entity_doc_coverage"]
