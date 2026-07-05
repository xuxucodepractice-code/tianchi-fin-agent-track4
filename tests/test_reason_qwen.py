"""Qwen 推理链测试（Task 5）。使用 fake client，不调用真实 API。

运行：python -m pytest tests/test_reason_qwen.py -q
"""

from __future__ import annotations

import json

from agent.reason_qwen import (
    MODE_DRY_RUN,
    MODE_QWEN,
    extract_json_from_text,
    judge_option_with_qwen,
    reason_question_dry_run,
    reason_question_with_qwen,
)

QUESTION = {
    "qid": "test_q_001",
    "domain": "insurance",
    "split": "A",
    "question": "关于保单贷款，以下哪些说法正确？",
    "options": {"A": "选项A文本", "B": "选项B文本", "C": "选项C文本", "D": "选项D文本"},
    "answer_format": "multi",
    "doc_ids": ["1"],
}

EVIDENCE = [
    {
        "chunk_id": "insurance:1:9:0",
        "doc_id": "1",
        "source_type": "pdf",
        "source_path": "public_dataset_upload/raw/insurance/1.pdf",
        "page": 9,
        "section": "",
        "score": 10.0,
        "matched_terms": ["保单贷款"],
        "text": "贷款金额不得超过现金价值的80%。",
    }
]

RETRIEVAL = {
    "qid": "test_q_001",
    "options": {
        k: {"option_text": v, "query_terms": ["保单贷款"], "evidence": EVIDENCE}
        for k, v in QUESTION["options"].items()
    },
}


class FakeQwenClient:
    """按选项顺序返回预置响应，并记录调用次数。"""

    model = "qwen-plus-fake"

    def __init__(self, contents: list[str]):
        self.contents = contents
        self.calls = 0

    def chat(self, messages, temperature=0.0, **kwargs):
        content = self.contents[self.calls % len(self.contents)]
        self.calls += 1
        return {
            "content": content,
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "model": self.model,
            "raw": {},
        }


def _judgment_json(option: str, judgment: str, refs=None) -> str:
    return json.dumps(
        {"option": option, "judgment": judgment, "rationale": "理由", "evidence_refs": refs or [1]},
        ensure_ascii=False,
    )


# ------------------------------------------------- 1. 合法 JSON 解析


def test_fake_client_valid_judgments_parsed():
    client = FakeQwenClient(
        [
            _judgment_json("A", "support"),
            _judgment_json("B", "refute"),
            _judgment_json("C", "insufficient"),
            _judgment_json("D", "refute"),
        ]
    )
    result = reason_question_with_qwen(QUESTION, RETRIEVAL, client=client)
    assert result["option_judgments"]["A"]["judgment"] == "support"
    assert result["option_judgments"]["B"]["judgment"] == "refute"
    assert result["option_judgments"]["C"]["judgment"] == "insufficient"
    assert result["mode"] == MODE_QWEN


# ------------------------------------------------- 2. 非 JSON 输出不崩溃


def test_non_json_output_recorded_as_error():
    client = FakeQwenClient(["这不是JSON，我认为答案是A。"])
    j = judge_option_with_qwen(client, QUESTION, "A", "选项A文本", EVIDENCE)
    assert j["judgment"] == "error"
    assert j["error"] is not None
    # 整题流程也不崩
    result = reason_question_with_qwen(QUESTION, RETRIEVAL, client=client)
    assert result["answer"]  # 仍产出合法 fallback 答案
    assert result["low_confidence"] is True


def test_json_extractable_from_wrapped_text():
    wrapped = "好的，我的判断如下：\n```json\n" + _judgment_json("A", "support") + "\n```"
    obj = extract_json_from_text(wrapped)
    assert obj and obj["judgment"] == "support"


# ------------------------------------------------- 3. dry-run 不调用 API


def test_dry_run_does_not_call_api(monkeypatch):
    import agent.qwen_client as qc

    def _boom(*a, **k):
        raise AssertionError("dry-run 不应创建 QwenClient 或调用 API")

    monkeypatch.setattr(qc.QwenClient, "__init__", _boom)
    monkeypatch.setattr(qc.QwenClient, "chat", _boom)
    result = reason_question_dry_run(QUESTION, RETRIEVAL)
    assert result["mode"] == MODE_DRY_RUN
    assert result["total_tokens"] == 0
    assert all(
        j["judgment"] == "insufficient" for j in result["option_judgments"].values()
    )


# ------------------------------------------------- 4. token 汇总


def test_token_aggregation():
    client = FakeQwenClient([_judgment_json("A", "support")])
    result = reason_question_with_qwen(QUESTION, RETRIEVAL, client=client)
    assert client.calls == 4  # 四个选项各一次
    assert result["prompt_tokens"] == 400
    assert result["completion_tokens"] == 80
    assert result["total_tokens"] == 480


# ------------------------------------------------- 5. answer 来自 normalize_answer


def test_final_answer_from_normalize_not_hardcoded():
    # support 组合不同 -> 答案应随之变化
    client1 = FakeQwenClient(
        [
            _judgment_json("A", "support"),
            _judgment_json("B", "support"),
            _judgment_json("C", "refute"),
            _judgment_json("D", "refute"),
        ]
    )
    client2 = FakeQwenClient(
        [
            _judgment_json("A", "refute"),
            _judgment_json("B", "refute"),
            _judgment_json("C", "support"),
            _judgment_json("D", "support"),
        ]
    )
    r1 = reason_question_with_qwen(QUESTION, RETRIEVAL, client=client1)
    r2 = reason_question_with_qwen(QUESTION, RETRIEVAL, client=client2)
    assert r1["answer"] == "AB"
    assert r2["answer"] == "CD"


# ------------------------------------------------- 6. judgment 字段齐全


def test_option_judgments_have_required_fields():
    client = FakeQwenClient([_judgment_json("A", "support")])
    result = reason_question_with_qwen(QUESTION, RETRIEVAL, client=client)
    assert set(result["option_judgments"]) == {"A", "B", "C", "D"}
    for j in result["option_judgments"].values():
        for field in ("judgment", "rationale", "evidence_refs", "prompt_tokens", "completion_tokens", "total_tokens"):
            assert field in j
