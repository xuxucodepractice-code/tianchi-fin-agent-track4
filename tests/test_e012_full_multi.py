from __future__ import annotations

from copy import deepcopy

from agent.reason_e007_reference_integrity import PROMPT_PROFILE
from agent.retrieve_v0_compat import (
    ROUTE_MIN_LONGEST_MATCH,
    ROUTE_MIN_SCORE_MARGIN,
    ROUTE_MIN_SCORE_RATIO,
    ROUTE_MIN_TITLE_SCORE,
    V0_RETRIEVE_SOURCE_SHA256,
    V0_TOP_K,
)
from agent.run_e012_full_multi import (
    AUTHORIZATION_PATH,
    BUILDER_PATH,
    CANDIDATE_AUDIT_PATH,
    CANDIDATE_DIR,
    CANDIDATE_FREEZE_PATH,
    CLAIM_PATH,
    EXPERIMENT_ID,
    FROZEN_INPUT_SHA256,
    FULL_MULTI_RESULT_PATH,
    LOGICAL_CALL_COUNT,
    OUTPUT_DIR,
    PIPELINE_VERSION,
    QUESTION_COUNT,
    REASONER_PATH,
    RERUN_BUNDLE_DIR,
    RUNNER_PATH,
    RUN_ID,
    SELECTION_PATH,
    TLS_CA_BUNDLE_PATH,
    TLS_CA_BUNDLE_SHA256,
    _load_selection,
    _official_multi_qids,
    validate_run_freeze_payload,
)
from agent.trace_gate import (
    OFFICIAL_DASHSCOPE_BASE_URL,
    code_snapshot,
    display_path,
    sha256_file,
)


def _valid_freeze() -> dict:
    return {
        "schema_version": "e012-full-multi-run-freeze/v1",
        "freeze_id": "E012_FULL_MULTI_01_2026-07-18",
        "experiment_id": EXPERIMENT_ID,
        "run_id": RUN_ID,
        "phase": "full_multi_expansion",
        "status": "AUTHORIZED_TO_RUN_ONCE",
        "source_code_commit": "1" * 40,
        "created_at": "2026-07-18T20:00:00+08:00",
        "agent_code_snapshot_sha256": code_snapshot()["sha256"],
        "code_files": {
            "runner": {"path": display_path(RUNNER_PATH), "sha256": sha256_file(RUNNER_PATH)},
            "builder": {"path": display_path(BUILDER_PATH), "sha256": sha256_file(BUILDER_PATH)},
            "reasoner": {"path": display_path(REASONER_PATH), "sha256": sha256_file(REASONER_PATH)},
        },
        "frozen_input_sha256": FROZEN_INPUT_SHA256,
        "qids": list(_official_multi_qids()),
        "attempt_nonce": "2" * 32,
        "registered_paths": {
            "selection": display_path(SELECTION_PATH),
            "authorization": display_path(AUTHORIZATION_PATH),
            "output_dir": display_path(OUTPUT_DIR),
            "claim": display_path(CLAIM_PATH),
            "full_multi_result": display_path(FULL_MULTI_RESULT_PATH),
            "rerun_bundle_dir": display_path(RERUN_BUNDLE_DIR),
            "candidate_dir": display_path(CANDIDATE_DIR),
            "candidate_audit": display_path(CANDIDATE_AUDIT_PATH),
            "candidate_freeze": display_path(CANDIDATE_FREEZE_PATH),
        },
        "pipeline": {
            "pipeline_version": PIPELINE_VERSION,
            "online_parent_pipeline_version": "v2s1",
            "retrieval_control_profile": "v0-82041d0",
            "prompt_profile": PROMPT_PROFILE,
            "reference_profile": "trace_bound_with_doc_order",
            "trace_evidence_binding": "call.model_evidence",
            "enable_option_document_route": True,
            "top_k": V0_TOP_K,
            "route_thresholds": {
                "minimum_title_score": ROUTE_MIN_TITLE_SCORE,
                "minimum_longest_match": ROUTE_MIN_LONGEST_MATCH,
                "minimum_score_ratio": ROUTE_MIN_SCORE_RATIO,
                "minimum_score_margin": ROUTE_MIN_SCORE_MARGIN,
            },
            "v0_retrieve_source_sha256": V0_RETRIEVE_SOURCE_SHA256,
            "per_option_call_count": 1,
            "whole_question_review_calls": 0,
            "normalize_answer": "agent.normalize_answer.normalize_answer",
        },
        "model": {
            "provider": "dashscope-openai-compatible",
            "requested_model": "qwen-plus",
            "base_url": OFFICIAL_DASHSCOPE_BASE_URL,
            "endpoint": f"{OFFICIAL_DASHSCOPE_BASE_URL}/chat/completions",
            "temperature": 0.0,
            "timeout_seconds": 90.0,
            "max_retries": 0,
            "served_model_policy": {"required_exact_value": "qwen-plus", "one_value": True},
        },
        "transport": {
            "ssl_cert_file": str(TLS_CA_BUNDLE_PATH),
            "ssl_cert_file_sha256": TLS_CA_BUNDLE_SHA256,
        },
        "call_topology": {
            "question_count": QUESTION_COUNT,
            "logical_calls": LOGICAL_CALL_COUNT,
            "derivations": QUESTION_COUNT,
            "physical_attempts": LOGICAL_CALL_COUNT,
            "max_retries_per_logical_call": 0,
        },
        "initial_state": {
            "output_exists": False,
            "claim_exists": False,
            "full_multi_result_exists": False,
            "rerun_bundle_exists": False,
            "candidate_exists": False,
            "candidate_audit_exists": False,
            "candidate_freeze_exists": False,
        },
        "failure_policy": {
            "failed_or_partial_run_may_be_retried": False,
            "claim_or_output_may_be_deleted_or_replaced": False,
            "fail_fast_on_first_parser_api_error": True,
            "candidate_forbidden_unless_receipt_pass": True,
        },
        "candidate_authorized": False,
        "submission_authorized": False,
        "upload_authorized": False,
        "push_authorized": False,
        "merge_authorized": False,
    }


def test_e012_selection_is_exact_official_multi_partition() -> None:
    selection = _load_selection()
    assert tuple(selection["qids"]) == _official_multi_qids()
    assert len(selection["qids"]) == 65
    assert selection["domain_counts"] == {
        "financial_contracts": 13,
        "financial_reports": 13,
        "insurance": 13,
        "regulatory": 13,
        "research": 13,
    }


def test_e012_run_freeze_contract_accepts_exact_payload() -> None:
    assert validate_run_freeze_payload(
        _valid_freeze(), current_code_snapshot=code_snapshot()
    ) == []


def test_e012_run_freeze_rejects_model_or_qid_drift() -> None:
    payload = _valid_freeze()
    drifted = deepcopy(payload)
    drifted["model"]["max_retries"] = 1
    drifted["qids"] = drifted["qids"][:-1]
    errors = validate_run_freeze_payload(
        drifted, current_code_snapshot=code_snapshot()
    )
    assert "run-freeze qids/order mismatch" in errors
    assert "run-freeze model/client mismatch" in errors
