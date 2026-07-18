from agent.run_gold_oracle import run_oracle_case


class FakeClient:
    model = "fake-qwen"

    def __init__(self):
        self.calls = []

    def chat(self, messages, temperature=0.0, **kwargs):
        self.calls.append(messages)
        return {
            "content": '{"verdict":"true","fact_checks":[{"claim":"x","verdict":"true","evidence_refs":[1]}],"rationale":"证据支持"}',
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "total_tokens": 12,
        }


def test_oracle_runner_uses_gold_and_current_evidence_without_gold_answer():
    question = {
        "qid": "tf_1",
        "domain": "regulatory",
        "answer_format": "tf",
        "question": "Claim",
        "options": {"A": "正确", "B": "错误"},
        "doc_ids": ["doc"],
    }
    chunks = [
        {
            "chunk_id": "doc:1",
            "domain": "regulatory",
            "doc_id": "doc",
            "source_type": "txt",
            "source_path": "doc.txt",
            "page": 1,
            "section": "",
            "text": "Claim",
        }
    ]
    client = FakeClient()
    result = run_oracle_case(
        {"qid": "tf_1", "gold_answer": "B", "required_chunk_ids": ["doc:1"]},
        question,
        chunks,
        client,
    )

    assert result["gold_evidence_answer"] == "A"
    assert result["current_final_answer"] == "A"
    assert result["gold_total_tokens"] == 12
    assert result["current_total_tokens"] == 12
    assert len(client.calls) == 2
    assert all("gold_answer" not in str(messages) for messages in client.calls)


class FakeOptionClient:
    model = "fake-qwen"

    def __init__(self):
        self.calls = []

    def chat(self, messages, temperature=0.0, **kwargs):
        self.calls.append((messages, kwargs.get("trace_context", {})))
        option = kwargs.get("trace_context", {}).get("option_key", "A")
        judgment = "support" if option == "A" else "refute"
        return {
            "content": (
                '{"option":"%s","judgment":"%s",'
                '"rationale":"evidence","evidence_refs":[1]}'
            )
            % (option, judgment),
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "total_tokens": 12,
        }


def test_oracle_runner_keeps_v2s1_mcq_per_option_topology():
    question = {
        "qid": "mcq_1",
        "domain": "regulatory",
        "answer_format": "mcq",
        "question": "Which?",
        "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
        "doc_ids": ["doc"],
    }
    chunks = [
        {
            "chunk_id": "doc:1",
            "domain": "regulatory",
            "doc_id": "doc",
            "source_type": "txt",
            "source_path": "doc.txt",
            "page": 1,
            "section": "",
            "text": "a",
        }
    ]
    client = FakeOptionClient()

    result = run_oracle_case(
        {"qid": "mcq_1", "gold_answer": "A", "required_chunk_ids": ["doc:1"]},
        question,
        chunks,
        client,
    )

    assert result["gold_evidence_answer"] == "A"
    assert result["current_final_answer"] == "A"
    assert len(client.calls) == 8
    assert {context["option_key"] for _, context in client.calls} == {
        "A",
        "B",
        "C",
        "D",
    }
