from __future__ import annotations

from agent.evaluate_e006_prospective_churn import (
    evaluate_churn,
    raw_judgment_binding_errors,
)
from agent.run_e006_prospective_arm import (
    AUTHORIZATION_PATH,
    CHURN_EVALUATOR_PATH,
    CHURN_REPORT_PATH,
    EXPECTED_OUTPUT_DIRS,
    FROZEN_INPUT_SHA256,
    OFFICIAL_DASHSCOPE_BASE_URL,
    PAIR_ID,
    PRIMARY_CLAIM_PATH,
    PROSPECTIVE_LABELS_PATH,
    PROSPECTIVE_QIDS,
    PROSPECTIVE_SCORED_RESULT_PATH,
    PROSPECTIVE_SELECTION_PATH,
    REPEAT_CLAIM_PATH,
    RUNNER_PATH,
    _load_selection,
    _verify_frozen_inputs,
    validate_run_freeze_payload,
)
from agent.trace_gate import code_snapshot, display_path, sha256_file


def _row(qid: str, answer: str = "A"):
    return {
        "qid": qid,
        "answer": answer,
        "option_judgments": {
            option: {"judgment": "support" if option in answer else "refute"}
            for option in "ABCD"
        },
        "retrieval": {
            option: {
                "evidence": [
                    {
                        "chunk_id": f"{qid}:{option}:1",
                        "doc_id": "d",
                        "text": "x",
                    }
                ]
            }
            for option in "ABCD"
        },
    }


def _bundle(attempt: str):
    return {
        "rows": [_row(qid) for qid in PROSPECTIVE_QIDS],
        "observations": {
            "total_tokens": 100 if attempt == "primary" else 105,
            "agent_trace": {"trace_run_id": f"trace-{attempt}"},
        },
        "receipt": {
            "code_sha256": "code",
            "model_sha256": "model",
            "input_artifacts_sha256": "inputs",
            "primary_claim_sha256": "primary-claim",
            "primary_anchor": None if attempt == "primary" else {"x": "y"},
            "repeat_claim_sha256": None if attempt == "primary" else "repeat-claim",
            "run_freeze_sha256": "freeze",
        },
        "served_models": ["qwen-plus-2026-01-01"],
        "manifest": {
            "started_at": (
                "2026-07-18T10:00:00+08:00"
                if attempt == "primary"
                else "2026-07-18T10:20:00+08:00"
            ),
            "finished_at": (
                "2026-07-18T10:20:00+08:00"
                if attempt == "primary"
                else "2026-07-18T10:40:00+08:00"
            ),
            "config": {
                "attempt": attempt,
                "output_dir": attempt,
                "primary_anchor": None if attempt == "primary" else {"x": "y"},
                "repeat_claim_sha256": None if attempt == "primary" else "claim",
                "same": "frozen",
            },
        },
    }


def _valid_run_freeze():
    return {
        "schema_version": "e006-prospective-run-freeze/v1",
        "freeze_id": "E006_PROSPECTIVE_PAIR_01_2026-07-18",
        "experiment_id": "E006",
        "phase": "prospective",
        "pair_id": PAIR_ID,
        "status": "AUTHORIZED_TO_RUN_PRIMARY_REPEAT",
        "created_at": "2026-07-18T18:00:00+08:00",
        "source_code_commit": "a" * 40,
        "agent_code_snapshot_sha256": code_snapshot()["sha256"],
        "code_files": {
            "runner": {
                "path": display_path(RUNNER_PATH),
                "sha256": sha256_file(RUNNER_PATH),
            },
            "churn_evaluator": {
                "path": display_path(CHURN_EVALUATOR_PATH),
                "sha256": sha256_file(CHURN_EVALUATOR_PATH),
            },
        },
        "qids": list(PROSPECTIVE_QIDS),
        "frozen_input_sha256": FROZEN_INPUT_SHA256,
        "authorization_basis": {
            "path": display_path(AUTHORIZATION_PATH),
            "sha256": FROZEN_INPUT_SHA256["authorization"],
            "required_status": "AUTHORIZED_TO_PREREGISTER_PRIMARY_REPEAT",
        },
        "registered_paths": {
            "primary_output_dir": display_path(EXPECTED_OUTPUT_DIRS["primary"]),
            "repeat_output_dir": display_path(EXPECTED_OUTPUT_DIRS["repeat"]),
            "primary_claim": display_path(PRIMARY_CLAIM_PATH),
            "repeat_claim": display_path(REPEAT_CLAIM_PATH),
            "churn_report": display_path(CHURN_REPORT_PATH),
            "labels": display_path(PROSPECTIVE_LABELS_PATH),
            "scored_result": display_path(PROSPECTIVE_SCORED_RESULT_PATH),
        },
        "pipeline_version": "v2s1-e006-option-doc-route",
        "pipeline": {
            "pipeline_version": "v2s1-e006-option-doc-route",
            "online_parent_pipeline_version": "v2s1",
            "retrieval_control_profile": "v0-82041d0",
            "prompt_profile": "v0-82041d0",
            "enable_option_document_route": True,
            "top_k": 5,
            "route_thresholds": {
                "minimum_title_score": 12,
                "minimum_longest_match": 4,
                "minimum_score_ratio": 3.0,
                "minimum_score_margin": 8,
            },
            "v0_retrieve_source_sha256": "1e55d7f8c725805fd4b752c2bab929119cb39ee3409275b45b1cdd782484dc3c",
            "v0_prompts_source_sha256": "161392afcd1528f7bb2b0c8b04df08614aded2d8d6898bd0deae9f0cda35738d",
            "per_option_call_count": 1,
            "whole_question_review_calls": 0,
        },
        "model": {
            "provider": "dashscope-openai-compatible",
            "requested_model": "qwen-plus",
            "base_url": OFFICIAL_DASHSCOPE_BASE_URL,
            "endpoint": f"{OFFICIAL_DASHSCOPE_BASE_URL}/chat/completions",
            "temperature": 0.0,
            "timeout_seconds": 90.0,
            "max_retries": 2,
            "served_model_policy": {
                "required_prefix": "qwen-plus",
                "one_exact_value_per_attempt": True,
                "same_exact_value_across_attempts": True,
            },
        },
        "call_topology": {
            "question_count_per_attempt": 15,
            "logical_calls_per_attempt": 60,
            "derivations_per_attempt": 15,
            "physical_attempts_min": 60,
            "physical_attempts_max": 180,
        },
        "attempt_nonces": {"primary": "1" * 32, "repeat": "2" * 32},
        "initial_state": {
            "primary_output_exists": False,
            "repeat_output_exists": False,
            "primary_claim_exists": False,
            "repeat_claim_exists": False,
            "churn_report_exists": False,
            "labels_created": False,
            "labels_revealed": False,
            "scored_result_exists": False,
        },
        "scoring_policy": {
            "scoring_arm": "primary",
            "repeat_non_scoring": True,
            "failed_or_partial_attempt_may_be_retried": False,
            "output_or_claim_may_be_deleted_or_replaced": False,
        },
        "label_isolation": {
            "status": "LABELS_SEALED",
            "labels_created": False,
            "labels_revealed_to_generation": False,
            "labels_must_remain_absent_through_churn_freeze": True,
        },
        "candidate_authorized": False,
        "submission_authorized": False,
    }


def test_frozen_prospective_selection_and_inputs_are_exact():
    selection = _load_selection(PROSPECTIVE_SELECTION_PATH)
    assert tuple(selection["qids"]) == PROSPECTIVE_QIDS
    assert selection["known_before_freeze_qids"] == []
    snapshots = _verify_frozen_inputs(PROSPECTIVE_SELECTION_PATH)
    assert {key: item["sha256"] for key, item in snapshots.items()} == FROZEN_INPUT_SHA256
    assert EXPECTED_OUTPUT_DIRS["primary"] != EXPECTED_OUTPUT_DIRS["repeat"]


def test_churn_evaluator_keeps_primary_as_scoring_arm():
    report = evaluate_churn(_bundle("primary"), _bundle("repeat"))
    assert report["status"] == "PASS"
    assert report["scoring_arm"] == "primary"
    assert report["primary_repeat_answer_churn_C"] == 0
    assert report["tokens"]["delta"] == 5
    assert report["repeat_non_scoring"] is True


def test_post_code_run_freeze_contract_is_exact():
    payload = _valid_run_freeze()
    assert validate_run_freeze_payload(
        payload, current_code_snapshot=code_snapshot()
    ) == []
    payload["model"]["max_retries"] = 3
    assert "run freeze model/client policy mismatch" in validate_run_freeze_payload(
        payload, current_code_snapshot=code_snapshot()
    )


def test_answer_churn_is_recorded_without_replacing_primary():
    primary = _bundle("primary")
    repeat = _bundle("repeat")
    repeat["rows"][0]["answer"] = "B"
    repeat["rows"][0]["option_judgments"]["A"]["judgment"] = "refute"
    repeat["rows"][0]["option_judgments"]["B"]["judgment"] = "support"
    report = evaluate_churn(primary, repeat)
    assert report["status"] == "PASS"
    assert report["primary_repeat_answer_churn_C"] == 1
    assert report["answer_churn"] == [f"{PROSPECTIVE_QIDS[0]}:A->B"]
    assert report["scoring_arm"] == "primary"


def test_retrieval_drift_or_semantic_config_drift_fails():
    primary = _bundle("primary")
    repeat = _bundle("repeat")
    repeat["rows"][0]["retrieval"]["A"]["evidence"][0]["text"] = "changed"
    report = evaluate_churn(primary, repeat)
    assert report["status"] == "FAIL"
    assert report["checks"]["retrieval_is_byte_identical"] is False

    repeat = _bundle("repeat")
    repeat["manifest"]["config"]["same"] = "different"
    report = evaluate_churn(primary, repeat)
    assert report["status"] == "FAIL"
    assert (
        report["checks"]["same_semantic_config_except_attempt_anchor_output"]
        is False
    )


def test_exact_served_model_drift_fails():
    primary = _bundle("primary")
    repeat = _bundle("repeat")
    repeat["served_models"] = ["qwen-plus-2026-02-01"]
    report = evaluate_churn(primary, repeat)
    assert report["status"] == "FAIL"
    assert report["checks"]["same_exact_served_model"] is False


def test_raw_judgment_binds_option_fields_and_evidence_range():
    qid = PROSPECTIVE_QIDS[0]
    row = _row(qid)
    row["option_judgments"]["A"].update(
        {"rationale": "有依据", "evidence_refs": [1], "error": None}
    )
    call = {
        "context": {"qid": qid, "option_key": "A"},
        "response_content": (
            '{"option":"A","judgment":"support","rationale":"有依据",'
            '"evidence_refs":[1]}'
        ),
    }
    assert raw_judgment_binding_errors([call], {qid: row}, attempt="primary") == []
    call["response_content"] = (
        '{"option":"B","judgment":"support","rationale":"有依据",'
        '"evidence_refs":[2]}'
    )
    errors = raw_judgment_binding_errors([call], {qid: row}, attempt="primary")
    assert any("option identity mismatch" in error for error in errors)
    assert any("outside rendered evidence range" in error for error in errors)
