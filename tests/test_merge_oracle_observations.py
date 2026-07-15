import pytest

from agent.merge_oracle_observations import merge_observations


def case_payload():
    return {
        "experiment_id": "oracle",
        "cases": [
            {
                "qid": "q1",
                "gold_answer": "A",
                "raw_source_contains_all_required_facts": True,
                "chunks_contain_all_required_facts": True,
                "current_retrieval_contains_all_required_facts": True,
                "current_evidence_rendering_preserves_all_required_facts": True,
                "gold_evidence_answer": None,
                "current_reasoning_answer": None,
                "current_final_answer": None,
            }
        ],
    }


def observation_payload(*, mode="qwen", tokens=10):
    result = {"qid": "q1", "mode": mode, "total_tokens": tokens}
    return {
        "observations": [
            {
                "qid": "q1",
                "gold_evidence_answer": "A",
                "current_reasoning_answer": "A",
                "current_final_answer": "A",
                "observed_at": "2026-07-14T00:00:00+08:00",
                "pipeline_version": "v2s1",
                "model": "qwen-plus",
                "gold_total_tokens": tokens,
                "current_total_tokens": tokens,
                "gold_result": result,
                "current_result": result,
            }
        ]
    }


def test_valid_observation_is_merged_and_classified():
    merged, results = merge_observations(case_payload(), observation_payload())
    assert merged["cases"][0]["gold_evidence_answer"] == "A"
    assert merged["cases"][0]["oracle_observation"]["model"] == "qwen-plus"
    assert results["complete_count"] == 1
    assert results["cases"][0]["primary_failure"] == "no_failure"


@pytest.mark.parametrize(
    "observations",
    [observation_payload(mode="dry_run_mock"), observation_payload(tokens=0)],
)
def test_mock_or_zero_token_observation_is_rejected(observations):
    with pytest.raises(ValueError):
        merge_observations(case_payload(), observations)
