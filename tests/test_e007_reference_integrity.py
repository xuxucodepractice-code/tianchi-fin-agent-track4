from __future__ import annotations

import json

from agent.reason_e007_reference_integrity import (
    CONTROL_INSTRUCTION,
    E007_PIPELINE_VERSION,
    TREATMENT_INSTRUCTION,
    V0_SYSTEM_PROMPT,
    build_option_messages,
    format_evidence_block,
    parse_treatment_judgment,
)
from agent.reason_multi_v0_compat import build_option_judgment_messages_v0
from agent.run_e007_development_arm import (
    DEVELOPMENT_QIDS,
    EVALUATOR_PATH,
    EXPECTED_OUTPUT_DIRS,
    FROZEN_INPUT_SHA256,
    PAIR_ID,
    REASON_PATH,
    RUNNER_PATH,
    SELECTION_PATH,
    TLS_CA_BUNDLE_PATH,
    TLS_CA_BUNDLE_SHA256,
    _load_selection,
    _verify_frozen_inputs,
    validate_run_freeze_payload,
)
from agent.trace_gate import code_snapshot, display_path, sha256_file, sha256_json


def _evidence():
    return [
        {
            "chunk_id": "c1",
            "doc_id": "d1",
            "page": 2,
            "section": "第二十三条",
            "text": "第二十三条 保险人应当说明。",
        },
        {
            "chunk_id": "c2",
            "doc_id": "d1",
            "page": None,
            "section": "",
            "text": "另一段证据。",
        },
    ]


def _question():
    return {
        "qid": "q1",
        "answer_format": "multi",
        "question": "哪些说法正确？",
        "options": {"A": "说法 A", "B": "B", "C": "C", "D": "D"},
    }


def test_control_prompt_is_exact_v0_prompt():
    evidence = _evidence()
    assert build_option_messages(
        _question(), "A", "说法 A", evidence, arm="control"
    ) == build_option_judgment_messages_v0(_question(), "A", "说法 A", evidence)


def test_treatment_changes_only_reference_markers_and_output_example():
    evidence = _evidence()
    control = format_evidence_block(evidence, arm="control")
    treatment = format_evidence_block(evidence, arm="treatment")
    assert "[证据1]" in control and "[证据2]" in control
    assert "[EV1]" in treatment and "[EV2]" in treatment
    assert control.replace("证据1", "EV1").replace("证据2", "EV2") == treatment
    assert "第二十三条" in treatment


def test_strict_treatment_parser_accepts_only_rendered_unique_ev_ids():
    content = json.dumps(
        {
            "option": "A",
            "judgment": "support",
            "rationale": "有依据",
            "evidence_refs": ["EV1", "EV2"],
        },
        ensure_ascii=False,
    )
    parsed, error = parse_treatment_judgment(content, "A", evidence_count=2)
    assert error is None
    assert parsed["evidence_refs"] == ["EV1", "EV2"]


def test_strict_treatment_parser_rejects_non_standalone_or_repaired_refs():
    base = {
        "option": "A",
        "judgment": "support",
        "rationale": "有依据",
        "evidence_refs": ["EV1"],
    }
    cases = []
    cases.append("prefix " + json.dumps(base))
    cases.append("```json\n" + json.dumps(base) + "\n```")
    wrong_option = dict(base, option="B")
    cases.append(json.dumps(wrong_option))
    integer_refs = dict(base, evidence_refs=[1])
    cases.append(json.dumps(integer_refs))
    unknown_refs = dict(base, evidence_refs=["EV1", "EV23"])
    cases.append(json.dumps(unknown_refs))
    duplicate_refs = dict(base, evidence_refs=["EV1", "EV1"])
    cases.append(json.dumps(duplicate_refs))
    extra_key = dict(base, qid="q1")
    cases.append(json.dumps(extra_key))
    for content in cases:
        parsed, error = parse_treatment_judgment(content, "A", evidence_count=2)
        assert error is not None
        assert parsed["judgment"] == "error"


def _valid_freeze():
    return {
        "schema_version": "e007r1-development-run-freeze/v1",
        "experiment_id": "E007R1",
        "pair_id": PAIR_ID,
        "phase": "development",
        "status": "AUTHORIZED_TO_RUN_DEVELOPMENT_PAIR",
        "source_code_commit": "a" * 40,
        "agent_code_snapshot_sha256": code_snapshot()["sha256"],
        "code_files": {
            "runner": {"path": display_path(RUNNER_PATH), "sha256": sha256_file(RUNNER_PATH)},
            "reasoner": {"path": display_path(REASON_PATH), "sha256": sha256_file(REASON_PATH)},
            "evaluator": {
                "path": display_path(EVALUATOR_PATH),
                "sha256": sha256_file(EVALUATOR_PATH),
            },
        },
        "qids": list(DEVELOPMENT_QIDS),
        "frozen_input_sha256": FROZEN_INPUT_SHA256,
        "registered_outputs": {
            "control": display_path(EXPECTED_OUTPUT_DIRS["control"]),
            "treatment": display_path(EXPECTED_OUTPUT_DIRS["treatment"]),
            "treatment_authorization": "outputs/experiments/E007R1_multi_evidence_reference_integrity/development_treatment_authorization.json",
            "treatment_claim": "outputs/experiments/E007R1_multi_evidence_reference_integrity/development_treatment_claim.json",
        },
        "prompt_bundle_sha256": sha256_json(
            {
                "system": V0_SYSTEM_PROMPT,
                "control_instruction": CONTROL_INSTRUCTION,
                "treatment_instruction": TREATMENT_INSTRUCTION,
            }
        ),
        "pipeline": {
            "pipeline_version": E007_PIPELINE_VERSION,
            "retrieval_parent": "E006-treatment",
            "enable_option_document_route": True,
            "top_k": 5,
            "route_thresholds": {
                "minimum_title_score": 12,
                "minimum_longest_match": 4,
                "minimum_score_ratio": 3.0,
                "minimum_score_margin": 8,
            },
            "v0_retrieve_source_sha256": "1e55d7f8c725805fd4b752c2bab929119cb39ee3409275b45b1cdd782484dc3c",
            "per_option_call_count": 1,
            "whole_question_review_calls": 0,
            "normalize_answer": "agent.normalize_answer.normalize_answer",
        },
        "model": {
            "provider": "dashscope-openai-compatible",
            "requested_model": "qwen-plus",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "temperature": 0.0,
            "timeout_seconds": 90.0,
            "max_retries": 0,
        },
        "transport": {
            "ssl_cert_file": str(TLS_CA_BUNDLE_PATH),
            "ssl_cert_file_sha256": TLS_CA_BUNDLE_SHA256,
            "pre_freeze_probe": {
                "api_key_used": False,
                "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                "expected_http_status": 400,
                "observed_http_status": 400,
            },
        },
        "call_topology": {
            "question_count_per_arm": 13,
            "logical_calls_per_arm": 52,
            "physical_attempts_per_arm": 52,
            "derivations_per_arm": 13,
        },
        "initial_state": {
            "control_output_exists": False,
            "treatment_output_exists": False,
            "treatment_authorization_exists": False,
            "treatment_claim_exists": False,
        },
    }


def test_governed_selection_inputs_and_freeze_contract():
    selection = _load_selection(SELECTION_PATH)
    assert tuple(selection["qids"]) == DEVELOPMENT_QIDS
    snapshots = _verify_frozen_inputs(SELECTION_PATH)
    assert {name: item["sha256"] for name, item in snapshots.items()} == FROZEN_INPUT_SHA256
    assert validate_run_freeze_payload(
        _valid_freeze(), current_code_snapshot=code_snapshot()
    ) == []
    invalid = _valid_freeze()
    invalid["model"]["max_retries"] = 1
    assert "model/client freeze mismatch" in validate_run_freeze_payload(
        invalid, current_code_snapshot=code_snapshot()
    )
