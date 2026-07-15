"""v2s1 tf direct-judgment tests. Fake client only; no real API calls."""

from __future__ import annotations

import json

from agent.reason_qwen import reason_tf_question_with_qwen
from agent.retrieve import retrieve_for_tf_question


TF_QUESTION = {
    "qid": "fc_a_013",
    "domain": "financial_contracts",
    "split": "A",
    "question": "两份文档均提及董事需对文件真实性承担责任。",
    "options": {"A": "正确", "B": "错误"},
    "answer_format": "tf",
    "doc_ids": ["text03", "text10"],
}

TF_RETRIEVAL = {
    "qid": "fc_a_013",
    "domain": "financial_contracts",
    "question": TF_QUESTION["question"],
    "answer_format": "tf",
    "doc_ids": ["text03", "text10"],
    "top_k": 5,
    "candidate_chunk_count": 2,
    "tf": {
        "query_terms": ["董事", "真实性"],
        "evidence": [
            {
                "chunk_id": "financial_contracts:text03:2:0",
                "doc_id": "text03",
                "source_type": "pdf",
                "source_path": "public_dataset_upload/raw/financial_contracts/text03.pdf",
                "page": 2,
                "section": "",
                "source_header": "【text03 · doc_id=text03 · 第2页】",
                "score": 10.0,
                "matched_terms": ["董事", "真实性"],
                "text": "发行人及其董事保证募集说明书信息披露的真实、准确、完整。",
            }
        ],
    },
}


class FakeQwenClient:
    model = "qwen-plus-fake"

    def __init__(self, contents: list[str]):
        self.contents = contents
        self.calls = 0

    def chat(self, messages, temperature=0.0, **kwargs):
        content = self.contents[self.calls]
        self.calls += 1
        return {
            "content": content,
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "model": self.model,
            "raw": {},
        }


def _tf_json(verdict: str, rationale: str = "证据支持该陈述。") -> str:
    return json.dumps(
        {
            "verdict": verdict,
            "fact_checks": [
                {"claim": "董事需负责真实性", "verdict": verdict, "evidence_refs": [1]}
            ],
            "rationale": rationale,
        },
        ensure_ascii=False,
    )


def test_tf_true_maps_to_a_with_single_call():
    client = FakeQwenClient([_tf_json("true")])

    result = reason_tf_question_with_qwen(TF_QUESTION, TF_RETRIEVAL, client=client)

    assert result["answer"] == "A"
    assert result["low_confidence"] is False
    assert result["tf_judgment"]["verdict"] == "true"
    assert result["option_judgments"]["A"]["judgment"] == "support"
    assert result["option_judgments"]["B"]["judgment"] == "refute"
    assert result["total_tokens"] == 120
    assert client.calls == 1


def test_tf_false_maps_to_b():
    client = FakeQwenClient([_tf_json("false", "证据明确否定该陈述。")])

    result = reason_tf_question_with_qwen(TF_QUESTION, TF_RETRIEVAL, client=client)

    assert result["answer"] == "B"
    assert result["low_confidence"] is False
    assert result["option_judgments"]["A"]["judgment"] == "refute"
    assert result["option_judgments"]["B"]["judgment"] == "support"


def test_tf_uncertain_reasks_once_then_fallback_low_confidence():
    client = FakeQwenClient(
        [
            _tf_json("uncertain", "证据不足。"),
            _tf_json("uncertain", "补充后仍证据不足。"),
        ]
    )

    result = reason_tf_question_with_qwen(
        TF_QUESTION, TF_RETRIEVAL, client=client, fallback_answer="A"
    )

    assert client.calls == 2
    assert result["answer"] == "A"
    assert result["low_confidence"] is True
    assert result["tf_judgment"]["verdict"] == "uncertain"
    assert any("fallback" in warning for warning in result["warnings"])
    assert result["total_tokens"] == 240


def test_tf_contradictory_rationale_is_not_silently_accepted():
    client = FakeQwenClient([_tf_json("false", "证据支持该命题为真。")])

    result = reason_tf_question_with_qwen(TF_QUESTION, TF_RETRIEVAL, client=client)

    assert result["answer"] == "A"
    assert result["low_confidence"] is True
    assert result["tf_judgment"]["verdict"] == "error"
    assert any("自洽" in warning for warning in result["warnings"])


def test_retrieve_for_tf_question_uses_question_level_doc_coverage():
    chunks = [
        {
            "chunk_id": "financial_contracts:text01:1:0",
            "domain": "financial_contracts",
            "doc_id": "text01",
            "source_type": "pdf",
            "source_path": "text01.pdf",
            "page": 1,
            "section": "",
            "text": "发行人承诺及时公平履行信息披露义务。",
        },
        {
            "chunk_id": "financial_contracts:text01:2:0",
            "domain": "financial_contracts",
            "doc_id": "text01",
            "source_type": "pdf",
            "source_path": "text01.pdf",
            "page": 2,
            "section": "",
            "text": "信息披露真实准确完整。",
        },
        {
            "chunk_id": "financial_contracts:text03:1:0",
            "domain": "financial_contracts",
            "doc_id": "text03",
            "source_type": "pdf",
            "source_path": "text03.pdf",
            "page": 1,
            "section": "",
            "text": "发行人将及时公平履行信息披露义务。",
        },
        {
            "chunk_id": "financial_contracts:text03:2:0",
            "domain": "financial_contracts",
            "doc_id": "text03",
            "source_type": "pdf",
            "source_path": "text03.pdf",
            "page": 2,
            "section": "",
            "text": "募集说明书信息披露真实准确完整。",
        },
    ]
    question = {
        "qid": "fc_a_003",
        "domain": "financial_contracts",
        "question": "两份文档均包含关于发行人及时公平履行信息披露义务的承诺。",
        "answer_format": "tf",
        "options": {"A": "正确", "B": "错误"},
        "doc_ids": ["text01", "text03"],
    }

    result = retrieve_for_tf_question(question, chunks, top_k=1)

    evidence = result["tf"]["evidence"]
    doc_counts = {doc_id: 0 for doc_id in question["doc_ids"]}
    for ev in evidence:
        doc_counts[ev["doc_id"]] += 1
    assert doc_counts == {"text01": 2, "text03": 2}
    assert "options" not in result
