from __future__ import annotations

from agent.build_e014_candidate import _verify_full_run, _verify_parent


def test_e014_external_parent_exact_hash_and_native_audit_pass() -> None:
    _verify_parent()


def test_e014_immutable_e013_trace_reaudit_passes_without_current_code_identity() -> None:
    observations, receipt, trace_dir, trace_report = _verify_full_run()
    assert observations["question_count"] == 65
    assert receipt["status"] == "PASS"
    assert receipt["served_models"] == ["qwen-plus"]
    assert receipt["logical_call_count"] == 260
    assert receipt["physical_attempt_count"] == 260
    assert receipt["max_retries_per_logical_call"] == 0
    assert trace_dir.is_dir()
    assert trace_report["ok"] is True
    assert trace_report["call_count"] == 260
    assert trace_report["derivation_count"] == 65
