"""答案规范化测试（Task 5）。运行：python -m pytest tests/test_normalize_answer.py -q"""

from __future__ import annotations

import pytest

from agent.normalize_answer import (
    normalize_answer,
    normalize_mcq_global_choice,
    normalize_tf_verdict,
    validate_answer_format,
)

OPTIONS_4 = {"A": "a", "B": "b", "C": "c", "D": "d"}
OPTIONS_TF = {"A": "对", "B": "错"}


def _j(judgment: str, refs: list[int] | None = None) -> dict:
    return {"judgment": judgment, "rationale": "", "evidence_refs": refs or []}


# ------------------------------------------------- multi


def test_multi_support_ac():
    r = normalize_answer(
        "multi",
        {"A": _j("support"), "B": _j("refute"), "C": _j("support"), "D": _j("insufficient")},
        OPTIONS_4,
    )
    assert r["answer"] == "AC"
    assert r["low_confidence"] is False


def test_multi_no_support_fallback_low_confidence():
    r = normalize_answer(
        "multi",
        {k: _j("insufficient") for k in OPTIONS_4},
        OPTIONS_4,
    )
    validate_answer_format(r["answer"], "multi", OPTIONS_4)  # 合法
    assert r["low_confidence"] is True
    assert r["warnings"]


def test_multi_sorted_output():
    r = normalize_answer(
        "multi",
        {"D": _j("support"), "B": _j("support"), "A": _j("refute"), "C": _j("support")},
        OPTIONS_4,
    )
    assert r["answer"] == "BCD"  # 排序、无分隔符


# ------------------------------------------------- mcq


def test_mcq_single_support():
    r = normalize_answer(
        "mcq",
        {"A": _j("refute"), "B": _j("support"), "C": _j("insufficient"), "D": _j("refute")},
        OPTIONS_4,
    )
    assert r["answer"] == "B"
    assert r["low_confidence"] is False


def test_mcq_multiple_support_picks_most_evidence_refs():
    r = normalize_answer(
        "mcq",
        {
            "A": _j("support", [1]),
            "B": _j("support", [1, 2, 3]),
            "C": _j("refute"),
            "D": _j("insufficient"),
        },
        OPTIONS_4,
    )
    assert r["answer"] == "B"
    assert r["low_confidence"] is True  # 多 support 属于低置信


def test_mcq_no_support_fallback():
    r = normalize_answer("mcq", {k: _j("refute") for k in OPTIONS_4}, OPTIONS_4)
    assert r["answer"] == "A"
    assert r["low_confidence"] is True


def test_mcq_global_choice_is_direct_and_invalid_choice_is_explicit_fallback():
    direct = normalize_mcq_global_choice("C", OPTIONS_4)
    assert direct == {
        "answer": "C",
        "warnings": [],
        "low_confidence": False,
        "fallback_used": False,
    }

    fallback = normalize_mcq_global_choice("BC", OPTIONS_4, fallback_answer="A")
    assert fallback["answer"] == "A"
    assert fallback["low_confidence"] is True
    assert fallback["fallback_used"] is True


# ------------------------------------------------- tf


def test_tf_a_support():
    r = normalize_answer("tf", {"A": _j("support"), "B": _j("refute")}, OPTIONS_TF)
    assert r["answer"] == "A"
    assert r["low_confidence"] is False


def test_tf_b_support():
    r = normalize_answer("tf", {"A": _j("insufficient"), "B": _j("support")}, OPTIONS_TF)
    assert r["answer"] == "B"
    assert r["low_confidence"] is False


def test_tf_verdict_true_false_uncertain_paths():
    true_result = normalize_tf_verdict("true", OPTIONS_TF)
    false_result = normalize_tf_verdict("false", OPTIONS_TF)
    uncertain_result = normalize_tf_verdict("uncertain", OPTIONS_TF, fallback_answer="A")

    assert true_result["answer"] == "A"
    assert true_result["low_confidence"] is False
    assert false_result["answer"] == "B"
    assert false_result["low_confidence"] is False
    assert uncertain_result["answer"] == "A"
    assert uncertain_result["low_confidence"] is True
    assert uncertain_result["warnings"]


# ------------------------------------------------- validate


def test_validate_rejects_illegal_chars():
    with pytest.raises(ValueError):
        validate_answer_format("对", "tf", OPTIONS_TF)
    with pytest.raises(ValueError):
        validate_answer_format("E", "mcq", OPTIONS_4)
    with pytest.raises(ValueError):
        validate_answer_format("", "mcq", OPTIONS_4)


def test_validate_rejects_multi_with_separator():
    with pytest.raises(ValueError):
        validate_answer_format("A,B", "multi", OPTIONS_4)
    with pytest.raises(ValueError):
        validate_answer_format("A B", "multi", OPTIONS_4)
    with pytest.raises(ValueError):
        validate_answer_format("BA", "multi", OPTIONS_4)  # 未排序
    with pytest.raises(ValueError):
        validate_answer_format("AAB", "multi", OPTIONS_4)  # 重复
