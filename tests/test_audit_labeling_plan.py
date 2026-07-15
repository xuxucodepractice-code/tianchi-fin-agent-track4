from agent.audit_labeling_plan import audit_plan


def test_repository_labeling_plan_is_complete_and_leak_free():
    result = audit_plan()
    assert result["valid"], result["errors"]
    assert result["counts"] == {
        "all_tf": 20,
        "historical_tf": 8,
        "s2a_tf": 2,
        "remaining_tf": 10,
        "mcq": 15,
        "multi": 15,
        "multi_domains": 5,
    }
