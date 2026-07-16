"""v2s2 M1 MCQ global-comparison tests. Fake client only; no API calls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.prompts import build_mcq_global_comparison_messages
from agent.output_writer import write_evidence_json
from agent.reason_qwen import (
    MCQ_GLOBAL_METHOD,
    PIPELINE_VERSION,
    parse_mcq_global_comparison_response,
    reason_mcq_question_with_qwen,
)


QUESTION = {
    "qid": "mcq_test_001",
    "domain": "insurance",
    "question": "四个选项中哪一项正确？",
    "options": {"A": "甲", "B": "乙", "C": "丙", "D": "丁"},
    "answer_format": "mcq",
    "doc_ids": ["doc"],
}


def _evidence(option: str) -> list[dict]:
    return [
        {
            "chunk_id": f"doc:{option}:1",
            "doc_id": "doc",
            "source_type": "txt",
            "source_path": "doc.txt",
            "page": 1,
            "section": "",
            "source_header": f"【doc · {option}】",
            "score": 1.0,
            "matched_terms": [option],
            "text": f"这是选项 {option} 的唯一证据文本。",
        }
    ]


RETRIEVAL = {
    "qid": QUESTION["qid"],
    "options": {
        key: {
            "option_text": text,
            "query_terms": [],
            "evidence": _evidence(key),
        }
        for key, text in QUESTION["options"].items()
    },
}


def _option_response(option: str, judgment: str) -> str:
    return json.dumps(
        {
            "option": option,
            "judgment": judgment,
            "rationale": f"参考判断 {option}",
            "evidence_refs": [1],
        },
        ensure_ascii=False,
    )


def _comparison_response(answer: str = "B") -> str:
    return json.dumps(
        {
            "answer": answer,
            "eliminated": {
                key: f"排除 {key}"
                for key in QUESTION["options"]
                if key != answer
            },
            "calculations": [],
            "confidence": "high",
            "rationale": f"横向比较后选择 {answer}",
        },
        ensure_ascii=False,
    )


class FakeClient:
    model = "qwen-plus-fake"

    def __init__(self, contents: list[str]):
        self.contents = contents
        self.calls: list[dict] = []

    def chat(self, messages, temperature=0.0, **kwargs):
        index = len(self.calls)
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                **kwargs,
            }
        )
        return {
            "content": self.contents[index],
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "model": self.model,
            "raw": {},
        }


def _valid_contents(global_content: str | None = None) -> list[str]:
    return [
        _option_response("A", "support"),
        _option_response("B", "refute"),
        _option_response("C", "refute"),
        _option_response("D", "refute"),
        global_content if global_content is not None else _comparison_response("B"),
    ]


def test_m1_uses_four_reference_calls_then_global_and_global_answer_wins():
    client = FakeClient(_valid_contents())

    result = reason_mcq_question_with_qwen(QUESTION, RETRIEVAL, client=client)

    assert len(client.calls) == 5
    assert [
        call["trace_context"]["stage"] for call in client.calls
    ] == [
        "option_independent_judgment",
        "option_independent_judgment",
        "option_independent_judgment",
        "option_independent_judgment",
        "mcq_global_comparison",
    ]
    assert [
        call["trace_context"].get("option_key") for call in client.calls[:4]
    ] == ["A", "B", "C", "D"]
    assert result["option_judgments"]["A"]["judgment"] == "support"
    assert result["answer"] == "B"  # 不再采用旧逐项链路会得到的 A
    assert result["mcq_comparison"]["answer"] == "B"
    assert result["answer_derivation"]["method"] == MCQ_GLOBAL_METHOD
    assert result["answer_derivation"]["fallback_used"] is False
    assert result["pipeline_version"] == "v2s2" == PIPELINE_VERSION
    assert result["prompt_tokens"] == 500
    assert result["completion_tokens"] == 100
    assert result["total_tokens"] == 600


def test_global_prompt_contains_all_options_and_all_original_evidence_only():
    messages = build_mcq_global_comparison_messages(QUESTION, RETRIEVAL)
    content = messages[1]["content"]

    for key, text in QUESTION["options"].items():
        assert f"选项 {key}：{text}" in content
        assert _evidence(key)[0]["text"] in content
        assert f"证据 {key}-1" in content
    assert "参考判断 A" not in content


@pytest.mark.parametrize(
    "invalid_content",
    [
        "不是 JSON",
        "说明如下：" + _comparison_response("B"),
        _comparison_response("B").replace('"answer": "B"', '"answer": "b"'),
        '{"answer":"B","answer":"C","eliminated":{"A":"x","C":"x","D":"x"},"calculations":[],"confidence":"high","rationale":"x"}',
        '{"answer":"B","eliminated":{"A":"x","B":"x","D":"x"},"calculations":[],"confidence":"high","rationale":"x"}',
        '{"answer":"B","eliminated":{"A":"x","C":"x","D":"x"},"calculations":[],"confidence":NaN,"rationale":"x"}',
    ],
)
def test_invalid_global_output_falls_back_and_is_low_confidence(invalid_content: str):
    client = FakeClient(_valid_contents(invalid_content))

    result = reason_mcq_question_with_qwen(QUESTION, RETRIEVAL, client=client)

    assert len(client.calls) == 5
    assert result["answer"] == "A"
    assert result["low_confidence"] is True
    assert result["answer_derivation"]["fallback_used"] is True
    assert result["answer_derivation"]["parse_error"]


def test_parser_requires_exact_three_non_answer_eliminations_and_nonempty_reasons():
    valid, error = parse_mcq_global_comparison_response(
        _comparison_response("C"), ["A", "B", "C", "D"]
    )
    assert error is None
    assert valid["answer"] == "C"

    missing = json.loads(_comparison_response("C"))
    del missing["eliminated"]["D"]
    _, missing_error = parse_mcq_global_comparison_response(
        json.dumps(missing), ["A", "B", "C", "D"]
    )
    assert missing_error

    empty_reason = json.loads(_comparison_response("C"))
    empty_reason["eliminated"]["A"] = ""
    _, reason_error = parse_mcq_global_comparison_response(
        json.dumps(empty_reason), ["A", "B", "C", "D"]
    )
    assert reason_error


def test_invalid_retrieval_fails_before_any_api_call():
    client = FakeClient(_valid_contents())
    bad_retrieval = {
        **RETRIEVAL,
        "options": {key: value for key, value in RETRIEVAL["options"].items() if key != "D"},
    }

    with pytest.raises(ValueError, match="exactly A/B/C/D"):
        reason_mcq_question_with_qwen(QUESTION, bad_retrieval, client=client)

    assert client.calls == []


def test_evidence_artifact_persists_global_comparison(tmp_path: Path):
    result = reason_mcq_question_with_qwen(
        QUESTION, RETRIEVAL, client=FakeClient(_valid_contents())
    )
    result["retrieval"] = {
        key: {"option_text": value["option_text"], "evidence": value["evidence"]}
        for key, value in RETRIEVAL["options"].items()
    }
    result["evidence"] = []
    path = write_evidence_json([result], tmp_path / "evidence.json")

    record = json.loads(path.read_text(encoding="utf-8"))[0]
    assert record["mcq_comparison"]["answer"] == "B"
    assert record["answer_derivation"]["input_comparison"]["answer"] == "B"
