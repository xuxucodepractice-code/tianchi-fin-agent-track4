from __future__ import annotations

from copy import deepcopy

import pytest

import agent.retrieve_v0_compat as compat
from agent.doc_meta import load_doc_meta
from agent.evaluate_e006_retrieval import evaluate
from agent.load_questions import find_question_by_qid
from agent.retrieve import load_chunks


def _compact(retrieval):
    return {
        key: {"option_text": value["option_text"], "evidence": value["evidence"]}
        for key, value in retrieval["options"].items()
    }


def test_e006_control_reproduces_frozen_v2s1_and_recall_gate_passes():
    report = evaluate()
    assert report["status"] == "PASS"
    assert report["control_reproduction"] == {
        "multi_question_count": 65,
        "option_pack_count": 260,
        "computed_canonical_sha256": (
            "274652fc800589a61eb964717f75ec5e16cd8f248f8382f0dea08ba4abff1740"
        ),
        "expected_canonical_sha256": (
            "274652fc800589a61eb964717f75ec5e16cd8f248f8382f0dea08ba4abff1740"
        ),
        "exact_match": True,
    }
    assert report["canonical_recall"]["control_hits"] == 30
    assert report["canonical_recall"]["treatment_hits"] == 34
    assert report["canonical_recall"]["control_complete_options"] == 22
    assert report["canonical_recall"]["treatment_complete_options"] == 26
    assert report["lost_required_chunks"] == []
    assert report["gained_required_chunks"] == [
        "ins_a_010:C:insurance:4:9:0",
        "ins_a_019:A:insurance:1:11:0",
        "ins_a_019:C:insurance:4:9:0",
        "ins_a_019:D:insurance:16:4:0",
    ]


def test_fallback_is_byte_identical_to_control():
    question = find_question_by_qid("fc_a_016")
    chunks = load_chunks()
    control = compat.retrieve_multi_v0_compatible(
        question, chunks, enable_option_document_route=False
    )
    diagnostics = {}
    treatment = compat.retrieve_multi_v0_compatible(
        question,
        chunks,
        enable_option_document_route=True,
        doc_meta=load_doc_meta(),
        diagnostics_out=diagnostics,
    )
    assert diagnostics["options"]["A"]["decision"] == "fallback"
    assert treatment["options"]["A"] == control["options"]["A"]
    assert diagnostics["options"]["D"]["decision"] == "fallback"
    assert treatment["options"]["D"] == control["options"]["D"]


def test_routed_hits_use_one_document_and_full_index_scores():
    question = find_question_by_qid("ins_a_019")
    chunks = load_chunks()
    control = compat.retrieve_multi_v0_compatible(
        question, chunks, enable_option_document_route=False
    )
    diagnostics = {}
    treatment = compat.retrieve_multi_v0_compatible(
        question,
        chunks,
        enable_option_document_route=True,
        doc_meta=load_doc_meta(),
        diagnostics_out=diagnostics,
    )
    expected_docs = {"A": "1", "B": "2", "C": "4", "D": "16"}
    for option_key, doc_id in expected_docs.items():
        route = diagnostics["options"][option_key]
        assert route["decision"] == "route"
        assert route["target_doc_id"] == doc_id
        assert len(treatment["options"][option_key]["evidence"]) == 5
        assert {
            str(item["doc_id"])
            for item in treatment["options"][option_key]["evidence"]
        } == {doc_id}
        # Query construction and evidence schema remain the v0 contract.
        assert treatment["options"][option_key]["query_terms"] == control["options"][option_key]["query_terms"]
        assert all("merged_chunk_ids" not in item for item in treatment["options"][option_key]["evidence"])
        assert all("source_header" not in item for item in treatment["options"][option_key]["evidence"])


@pytest.mark.parametrize(
    ("top", "second", "expected_reason"),
    [
        ((11, 6), (0, 0), "title_score_below_threshold"),
        ((12, 3), (0, 0), "longest_match_below_threshold"),
        ((12, 6), (5, 5), "score_ratio_below_threshold"),
        ((12, 6), (12, 6), "score_ratio_below_threshold"),
    ],
)
def test_route_thresholds_fail_safe(monkeypatch, top, second, expected_reason):
    scores = {
        "top": {"score": top[0], "longest_match": top[1], "matched_terms": ["核心实体"]},
        "second": {
            "score": second[0],
            "longest_match": second[1],
            "matched_terms": ["其他实体"] if second[0] else [],
        },
    }

    def fake_score(_option_text, title):
        return deepcopy(scores[title])

    monkeypatch.setattr(compat, "_score_option_against_title", fake_score)
    question = {
        "answer_format": "multi",
        "domain": "demo",
        "doc_ids": ["a", "b"],
    }
    meta = {
        "demo": {
            "a": {"title": "top"},
            "b": {"title": "second"},
        }
    }
    decision = compat.decide_option_document_route(question, "A", "x", meta)
    assert decision["decision"] == "fallback"
    assert decision["reason"] == expected_reason


def test_route_margin_boundary_is_enforced(monkeypatch):
    scores = {
        "top": {"score": 12, "longest_match": 6, "matched_terms": ["核心实体"]},
        "second": {"score": 4, "longest_match": 4, "matched_terms": ["其他实体"]},
    }
    monkeypatch.setattr(
        compat,
        "_score_option_against_title",
        lambda _text, title: deepcopy(scores[title]),
    )
    monkeypatch.setattr(compat, "ROUTE_MIN_SCORE_MARGIN", 9)
    decision = compat.decide_option_document_route(
        {"answer_format": "multi", "domain": "demo", "doc_ids": ["a", "b"]},
        "A",
        "x",
        {"demo": {"a": {"title": "top"}, "b": {"title": "second"}}},
    )
    assert decision["decision"] == "fallback"
    assert decision["reason"] == "score_margin_below_threshold"


def test_missing_metadata_and_non_multi_are_safe():
    question = {
        "answer_format": "multi",
        "domain": "demo",
        "doc_ids": ["a", "b"],
    }
    decision = compat.decide_option_document_route(
        question, "A", "核心实体", {"demo": {"a": {"title": "核心实体"}}}
    )
    assert decision["reason"] == "missing_document_metadata"

    non_multi = {**question, "answer_format": "mcq"}
    assert compat.decide_option_document_route(
        non_multi, "A", "核心实体", {}
    )["reason"] == "non_multi"
    with pytest.raises(ValueError, match="Multi-only"):
        compat.retrieve_multi_v0_compatible(
            non_multi, [], enable_option_document_route=False
        )
