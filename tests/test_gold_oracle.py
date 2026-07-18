import pytest

from agent.gold_oracle import (
    build_gold_retrieval,
    canonical_answer,
    classify_case,
    classify_cases,
    render_gold_evidence,
)


def complete_case(**overrides):
    case = {
        "qid": "q1",
        "gold_answer": "AC",
        "raw_source_contains_all_required_facts": True,
        "chunks_contain_all_required_facts": True,
        "current_retrieval_contains_all_required_facts": True,
        "current_evidence_rendering_preserves_all_required_facts": True,
        "gold_evidence_answer": "AC",
        "current_reasoning_answer": "AC",
        "current_final_answer": "AC",
    }
    case.update(overrides)
    return case


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"raw_source_contains_all_required_facts": False}, "data_or_question"),
        ({"chunks_contain_all_required_facts": False}, "parsing"),
        (
            {
                "current_retrieval_contains_all_required_facts": False,
                "current_reasoning_answer": "B",
                "current_final_answer": "B",
            },
            "retrieval",
        ),
        (
            {
                "current_evidence_rendering_preserves_all_required_facts": False,
                "current_reasoning_answer": "B",
                "current_final_answer": "B",
            },
            "evidence_organization",
        ),
        ({"gold_evidence_answer": "B"}, "reasoning_or_prompt"),
        (
            {"current_reasoning_answer": "B", "current_final_answer": "B"},
            "reasoning_or_prompt",
        ),
        ({"current_final_answer": "B"}, "answer_synthesis"),
        ({}, "no_failure"),
    ],
)
def test_classification_decision_tree(overrides, expected):
    assert classify_case(complete_case(**overrides))["primary_failure"] == expected


def test_incomplete_case_is_not_silently_classified():
    result = classify_case(complete_case(gold_evidence_answer=None))
    assert result["oracle_status"] == "incomplete"
    assert result["primary_failure"] is None
    assert "gold_evidence_answer" in result["missing_fields"]


def test_gold_evidence_failure_takes_priority_over_current_rendering_gap():
    result = classify_case(
        complete_case(
            gold_evidence_answer="B",
            current_evidence_rendering_preserves_all_required_facts=False,
            current_reasoning_answer="B",
            current_final_answer="B",
        )
    )
    assert result["primary_failure"] == "reasoning_or_prompt"
    assert result["risk_flags"] == ["evidence_organization", "reasoning_or_prompt"]


def test_correct_answer_with_evidence_gap_is_no_failure_with_risk_flag():
    result = classify_case(
        complete_case(current_evidence_rendering_preserves_all_required_facts=False)
    )
    assert result["primary_failure"] == "no_failure"
    assert result["risk_flags"] == ["evidence_organization"]


def test_multi_answers_are_canonicalized_and_duplicate_qids_rejected():
    assert canonical_answer("caac") == "AC"
    summary = classify_cases([complete_case(gold_answer="CA", qid="q1")])
    assert summary["complete_count"] == 1
    assert summary["failure_counts"]["no_failure"] == 1

    with pytest.raises(ValueError, match="duplicate qid"):
        classify_cases([complete_case(qid="q1"), complete_case(qid="q1")])


def test_gold_evidence_uses_production_format_and_retrieval_shape():
    chunks = [
        {
            "chunk_id": "doc:1",
            "domain": "test",
            "doc_id": "doc",
            "source_path": "raw/test/doc.pdf",
            "page": 7,
            "section": "Section",
            "text": "Decisive fact",
        }
    ]
    doc_meta = {
        "test": {
            "doc": {
                "title": "Named source document",
                "entity": "Named source document",
                "source_path": "raw/test/doc.pdf",
            }
        }
    }
    rendered = render_gold_evidence(["doc:1"], chunks, doc_meta=doc_meta)
    assert rendered == (
        "[证据1] 【Named source document · doc_id=doc · 第7页 · Section】\n"
        "Decisive fact"
    )

    tf = build_gold_retrieval(
        {"qid": "tf", "answer_format": "tf", "options": {"A": "yes", "B": "no"}},
        ["doc:1"],
        chunks,
        doc_meta=doc_meta,
    )
    assert tf["tf"]["evidence"][0]["chunk_id"] == "doc:1"
    assert "Named source document" in tf["tf"]["evidence"][0]["source_header"]

    mcq = build_gold_retrieval(
        {"qid": "mcq", "answer_format": "mcq", "options": {"A": "one", "B": "two"}},
        ["doc:1"],
        chunks,
        doc_meta=doc_meta,
    )
    assert set(mcq["options"]) == {"A", "B"}
    assert mcq["options"]["A"]["evidence"] == mcq["options"]["B"]["evidence"]

    with pytest.raises(ValueError, match="Gold chunk ids not found"):
        render_gold_evidence(["missing"], chunks)
