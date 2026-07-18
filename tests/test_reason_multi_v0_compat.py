from __future__ import annotations

from agent.reason_multi_v0_compat import (
    build_option_judgment_messages_v0,
    format_evidence_block_v0,
    reason_multi_with_v0_prompt,
)


class FakeClient:
    model = "qwen-plus"

    def __init__(self):
        self.calls = []

    def chat(self, messages, temperature, trace_context):
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "trace_context": trace_context,
            }
        )
        option = trace_context["option_key"]
        verdict = "support" if option in {"A", "C"} else "refute"
        return {
            "content": (
                '{"option":"%s","judgment":"%s","rationale":"ok",'
                '"evidence_refs":[1]}' % (option, verdict)
            ),
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "total_tokens": 12,
            "trace_call_id": f"call-{option}",
            "trace_run_id": "trace-1",
            "local_request_id": f"local-{option}",
            "provider_request_id": f"provider-{option}",
            "retry_count": 0,
        }


def _evidence(doc_id="d1"):
    return [
        {
            "chunk_id": f"demo:{doc_id}:1:0",
            "doc_id": doc_id,
            "source_type": "pdf",
            "source_path": f"{doc_id}.pdf",
            "page": 3,
            "section": "条款",
            "score": 1.0,
            "matched_terms": ["测试"],
            "text": "证据正文",
        }
    ]


def test_v0_evidence_location_keeps_parentheses():
    assert format_evidence_block_v0(_evidence()) == (
        "[证据1] (doc_id=d1 第3页 [条款])\n证据正文"
    )
    messages = build_option_judgment_messages_v0(
        {"question": "题干"}, "A", "选项", _evidence()
    )
    assert "[证据1] (doc_id=d1 第3页 [条款])" in messages[1]["content"]
    assert messages[1]["content"].startswith(
        "题目（仅供理解选项语境，不作为证据）：题干"
    )


def test_v0_reasoner_uses_four_calls_and_deterministic_normalization():
    question = {
        "qid": "demo_multi",
        "domain": "demo",
        "answer_format": "multi",
        "question": "题干",
        "options": {key: f"选项{key}" for key in "ABCD"},
        "doc_ids": ["d1", "d2"],
    }
    retrieval = {
        "options": {
            key: {"option_text": f"选项{key}", "evidence": _evidence(key)}
            for key in "ABCD"
        }
    }
    client = FakeClient()
    result = reason_multi_with_v0_prompt(
        question, retrieval, client=client, arm="treatment"
    )
    assert result["answer"] == "AC"
    assert result["total_tokens"] == 48
    assert result["trace_run_id"] == "trace-1"
    assert len(client.calls) == 4
    assert [call["trace_context"]["option_key"] for call in client.calls] == list("ABCD")
    assert {call["trace_context"]["stage"] for call in client.calls} == {
        "e006_treatment_v0_option_judgment"
    }
    assert {call["temperature"] for call in client.calls} == {0.0}


def test_control_and_treatment_share_identical_model_messages():
    question = {
        "qid": "demo_multi",
        "domain": "demo",
        "answer_format": "multi",
        "question": "题干",
        "options": {key: f"选项{key}" for key in "ABCD"},
        "doc_ids": ["d1", "d2"],
    }
    retrieval = {
        "options": {
            key: {"option_text": f"选项{key}", "evidence": _evidence(key)}
            for key in "ABCD"
        }
    }
    control_client = FakeClient()
    treatment_client = FakeClient()
    reason_multi_with_v0_prompt(
        question, retrieval, client=control_client, arm="control"
    )
    reason_multi_with_v0_prompt(
        question, retrieval, client=treatment_client, arm="treatment"
    )
    assert [item["messages"] for item in control_client.calls] == [
        item["messages"] for item in treatment_client.calls
    ]
