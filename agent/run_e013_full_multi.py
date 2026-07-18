"""Run the one-shot governed E013 expansion over all 65 Multi questions."""

from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.doc_meta import load_doc_meta
from agent.load_questions import load_all_questions
from agent.paths import REPO_ROOT
from agent.qwen_client import MissingApiKeyError, QwenClient
from agent.reason_e007_reference_integrity import (
    E007_PIPELINE_VERSION as PIPELINE_VERSION,
    PROMPT_PROFILE,
    build_option_messages,
    build_question_result,
    judge_option,
    parse_treatment_judgment,
)
from agent.retrieve import load_chunks
from agent.retrieve_v0_compat import (
    ROUTE_MIN_LONGEST_MATCH,
    ROUTE_MIN_SCORE_MARGIN,
    ROUTE_MIN_SCORE_RATIO,
    ROUTE_MIN_TITLE_SCORE,
    V0_RETRIEVE_SOURCE_SHA256,
    V0_TOP_K,
    retrieve_multi_v0_compatible,
)
from agent.run_e007_development_arm import (
    E006_CONTROL_REFERENCE_PATH as CONTROL_REFERENCE_PATH,
    E006_OFFLINE_GATE_PATH as OFFLINE_GATE_PATH,
    _compact_retrieval,
    _validate_questions,
)
from agent.trace_gate import (
    AgentTraceRecorder,
    OFFICIAL_DASHSCOPE_BASE_URL,
    blind_data_guard,
    code_snapshot,
    default_candidate_forbidden_roots,
    default_runtime_read_roots,
    display_path,
    input_artifact_snapshot,
    now_iso,
    sha256_file,
    sha256_json,
    validate_trace_directory,
)

EXPERIMENT_ID = "E013"
RUN_ID = "e013-full-multi-01"
EXPERIMENT_DIR = (
    REPO_ROOT / "workspace/03_baseline_improvement/experiments/E013_full_multi_expansion_rerun"
)
SELECTION_PATH = EXPERIMENT_DIR / "full_multi_selection.json"
AUTHORIZATION_PATH = EXPERIMENT_DIR / "technical_authorization.json"
RUN_FREEZE_PATH = EXPERIMENT_DIR / "full_multi_run_freeze.json"
E011_SCORED_RESULT_PATH = (
    REPO_ROOT
    / "workspace/03_baseline_improvement/experiments/E011_e010_churn_zero_value_audit/prospective_scored_result.json"
)
OUTPUT_ROOT = REPO_ROOT / "outputs/experiments/E013_full_multi_expansion_rerun"
OUTPUT_DIR = OUTPUT_ROOT / "full_multi_01"
CLAIM_PATH = OUTPUT_ROOT / "full_multi_claim.json"
FULL_MULTI_RESULT_PATH = EXPERIMENT_DIR / "full_multi_result.json"
RERUN_BUNDLE_DIR = OUTPUT_ROOT / "full_multi_bundle"
CANDIDATE_DIR = REPO_ROOT / "outputs/candidates/e013_full_multi_candidate"
CANDIDATE_AUDIT_PATH = EXPERIMENT_DIR / "candidate_audit.json"
CANDIDATE_FREEZE_PATH = EXPERIMENT_DIR / "candidate_freeze.json"
RUNNER_PATH = REPO_ROOT / "agent/run_e013_full_multi.py"
BUILDER_PATH = REPO_ROOT / "agent/build_e013_candidate.py"
REASONER_PATH = REPO_ROOT / "agent/reason_e007_reference_integrity.py"

REQUESTED_MODEL = "qwen-plus"
CLIENT_TIMEOUT_SECONDS = 90.0
CLIENT_MAX_RETRIES = 0
TLS_CA_BUNDLE_PATH = Path("/etc/ssl/cert.pem")
TLS_CA_BUNDLE_SHA256 = "9dae8d76e55cb08991f2b672d58999ea15560d910759c16b544f843bdffbb994"
QUESTION_COUNT = 65
LOGICAL_CALL_COUNT = 260

FROZEN_INPUT_SHA256 = {
    "questions": "c33dde8ac97d8a00ef3796f4312274cea74fce699f52b15c006c45fab80c0676",
    "chunks": "02aa2f9b33f304a4d9a74789acc5aa47ec9efff42d7a68bdd2390e7cea30a878",
    "doc_meta": "df9af050cce73707536d2798f62b1e4640747d4cfe595b2e12cddd22d6d472d7",
    "selection": "cadbeab9af7dacbd656ef975a91f7f4c731ded30adfe4801569a05e76286d20a",
    "authorization": "d988d69020e801193d91ac720899b6b808b33bc3a497c6410a86792bc86f3966",
    "e011_scored_result": "ef7ec2af6859416e5342dbb27c95b1673b91117b4c19add9b733618c0453b737",
    "control_reference": "db90509ba127f662b333e07664e79ff7ce0264db9f1b3cbb34cca177d10d4572",
    "offline_gate": "6c7ec2a4ff7b9efefe8923bb8c5a8d18e0e7f8f69e63b1b8eba2c8cb50a9b7b0",
    "tls_ca_bundle": TLS_CA_BUNDLE_SHA256,
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _official_multi_qids() -> tuple[str, ...]:
    return tuple(
        str(question["qid"])
        for question in load_all_questions()
        if question.get("answer_format") == "multi"
    )


def _expected_code_files() -> dict[str, dict[str, str]]:
    return {
        "runner": {"path": display_path(RUNNER_PATH), "sha256": sha256_file(RUNNER_PATH)},
        "builder": {"path": display_path(BUILDER_PATH), "sha256": sha256_file(BUILDER_PATH)},
        "reasoner": {"path": display_path(REASONER_PATH), "sha256": sha256_file(REASONER_PATH)},
    }


def validate_run_freeze_payload(
    payload: dict[str, Any], *, current_code_snapshot: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    if (
        payload.get("schema_version") != "e013-full-multi-run-freeze/v1"
        or payload.get("freeze_id") != "E013_FULL_MULTI_01_2026-07-18"
        or payload.get("experiment_id") != EXPERIMENT_ID
        or payload.get("run_id") != RUN_ID
        or payload.get("phase") != "full_multi_expansion"
        or payload.get("status") != "AUTHORIZED_TO_RUN_ONCE"
    ):
        errors.append("run-freeze identity/status mismatch")
    if re.fullmatch(r"[0-9a-f]{40}", str(payload.get("source_code_commit") or "")) is None:
        errors.append("run-freeze source commit is invalid")
    try:
        datetime.fromisoformat(str(payload["created_at"]))
    except (KeyError, TypeError, ValueError):
        errors.append("run-freeze created_at is not ISO-8601")
    if payload.get("agent_code_snapshot_sha256") != current_code_snapshot.get("sha256"):
        errors.append("run-freeze agent code snapshot mismatch")
    if payload.get("code_files") != _expected_code_files():
        errors.append("run-freeze code file hashes mismatch")
    if payload.get("frozen_input_sha256") != FROZEN_INPUT_SHA256:
        errors.append("run-freeze input hashes mismatch")
    if tuple(map(str, payload.get("qids") or [])) != _official_multi_qids():
        errors.append("run-freeze qids/order mismatch")
    if re.fullmatch(r"[0-9a-f]{32}", str(payload.get("attempt_nonce") or "")) is None:
        errors.append("run-freeze nonce missing/invalid")
    expected_paths = {
        "selection": display_path(SELECTION_PATH),
        "authorization": display_path(AUTHORIZATION_PATH),
        "output_dir": display_path(OUTPUT_DIR),
        "claim": display_path(CLAIM_PATH),
        "full_multi_result": display_path(FULL_MULTI_RESULT_PATH),
        "rerun_bundle_dir": display_path(RERUN_BUNDLE_DIR),
        "candidate_dir": display_path(CANDIDATE_DIR),
        "candidate_audit": display_path(CANDIDATE_AUDIT_PATH),
        "candidate_freeze": display_path(CANDIDATE_FREEZE_PATH),
    }
    if payload.get("registered_paths") != expected_paths:
        errors.append("run-freeze registered paths mismatch")
    expected_pipeline = {
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
    }
    if payload.get("pipeline") != expected_pipeline:
        errors.append("run-freeze pipeline mismatch")
    expected_model = {
        "provider": "dashscope-openai-compatible",
        "requested_model": REQUESTED_MODEL,
        "base_url": OFFICIAL_DASHSCOPE_BASE_URL,
        "endpoint": f"{OFFICIAL_DASHSCOPE_BASE_URL}/chat/completions",
        "temperature": 0.0,
        "timeout_seconds": CLIENT_TIMEOUT_SECONDS,
        "max_retries": CLIENT_MAX_RETRIES,
        "served_model_policy": {"required_exact_value": "qwen-plus", "one_value": True},
    }
    if payload.get("model") != expected_model:
        errors.append("run-freeze model/client mismatch")
    if payload.get("transport") != {
        "ssl_cert_file": str(TLS_CA_BUNDLE_PATH),
        "ssl_cert_file_sha256": TLS_CA_BUNDLE_SHA256,
    }:
        errors.append("run-freeze TLS mismatch")
    if payload.get("call_topology") != {
        "question_count": QUESTION_COUNT,
        "logical_calls": LOGICAL_CALL_COUNT,
        "derivations": QUESTION_COUNT,
        "physical_attempts": LOGICAL_CALL_COUNT,
        "max_retries_per_logical_call": 0,
    }:
        errors.append("run-freeze call topology mismatch")
    if payload.get("initial_state") != {
        "output_exists": False,
        "claim_exists": False,
        "full_multi_result_exists": False,
        "rerun_bundle_exists": False,
        "candidate_exists": False,
        "candidate_audit_exists": False,
        "candidate_freeze_exists": False,
    }:
        errors.append("run-freeze initial-state mismatch")
    if payload.get("failure_policy") != {
        "failed_or_partial_run_may_be_retried": False,
        "claim_or_output_may_be_deleted_or_replaced": False,
        "fail_fast_on_first_parser_api_error": True,
        "candidate_forbidden_unless_receipt_pass": True,
    }:
        errors.append("run-freeze failure policy mismatch")
    if any(payload.get(field) is not False for field in (
        "candidate_authorized", "submission_authorized", "upload_authorized",
        "push_authorized", "merge_authorized",
    )):
        errors.append("run-freeze cannot authorize candidate/submission/external mutation")
    return errors


def load_and_verify_run_freeze() -> tuple[dict[str, Any], dict[str, Any]]:
    payload = _load_json(RUN_FREEZE_PATH)
    errors = validate_run_freeze_payload(payload, current_code_snapshot=code_snapshot())
    if errors:
        raise ValueError(f"E013 run-freeze invalid: {errors}")
    return payload, input_artifact_snapshot(RUN_FREEZE_PATH)


def _load_selection() -> dict[str, Any]:
    if sha256_file(SELECTION_PATH) != FROZEN_INPUT_SHA256["selection"]:
        raise ValueError("E013 selection hash mismatch")
    payload = _load_json(SELECTION_PATH)
    qids = tuple(map(str, payload.get("qids") or []))
    if (
        payload.get("schema_version") != "e013-full-multi-selection/v1"
        or payload.get("experiment_id") != EXPERIMENT_ID
        or payload.get("selection_id") != "e013-official-group-a-multi-65"
        or payload.get("selection_method")
        != "official_group_a_order_where_answer_format_equals_multi"
        or qids != _official_multi_qids()
        or int(payload.get("question_count") or 0) != QUESTION_COUNT
        or int(payload.get("logical_call_count") or 0) != LOGICAL_CALL_COUNT
        or payload.get("domain_counts") != {
            "financial_contracts": 13,
            "financial_reports": 13,
            "insurance": 13,
            "regulatory": 13,
            "research": 13,
        }
        or payload.get("labels_are_not_runner_inputs") is not True
        or payload.get("qid_doc_chunk_special_cases_forbidden") is not True
    ):
        raise ValueError("E013 selection semantics mismatch")
    return payload


def _verify_frozen_inputs() -> dict[str, dict[str, Any]]:
    paths = {
        "questions": REPO_ROOT / "public_dataset_upload/questions/group_a",
        "chunks": REPO_ROOT / "processed_data/chunks.jsonl",
        "doc_meta": REPO_ROOT / "processed_data/doc_meta.json",
        "selection": SELECTION_PATH,
        "authorization": AUTHORIZATION_PATH,
        "e011_scored_result": E011_SCORED_RESULT_PATH,
        "control_reference": CONTROL_REFERENCE_PATH,
        "offline_gate": OFFLINE_GATE_PATH,
        "tls_ca_bundle": TLS_CA_BUNDLE_PATH,
    }
    snapshots = {name: input_artifact_snapshot(path) for name, path in paths.items()}
    mismatches = {
        name: (entry.get("sha256"), FROZEN_INPUT_SHA256[name])
        for name, entry in snapshots.items()
        if entry.get("sha256") != FROZEN_INPUT_SHA256[name]
    }
    if mismatches:
        raise ValueError(f"E013 frozen input mismatch: {mismatches}")
    authorization = _load_json(AUTHORIZATION_PATH)
    basis = authorization.get("authorization_basis") or {}
    if (
        authorization.get("status") != "AUTHORIZED_TO_FREEZE_FULL_MULTI_RUN"
        or basis.get("sha256") != FROZEN_INPUT_SHA256["e011_scored_result"]
        or basis.get("required_status") != "PASS"
        or basis.get("required_decision") != "ALLOW_FULL_65_MULTI_EXPANSION"
        or basis.get("N") != 2
        or basis.get("M") != 0
        or basis.get("C") != 0
        or float(basis.get("projected_score") or 0) != 69.36777264
    ):
        raise ValueError("E013 technical authorization mismatch")
    scored = _load_json(E011_SCORED_RESULT_PATH)
    if (
        scored.get("status") != "PASS"
        or scored.get("decision") != "ALLOW_FULL_65_MULTI_EXPANSION"
        or scored.get("allow_full_65_multi_expansion") is not True
        or scored.get("N") != 2
        or scored.get("M") != 0
        or scored.get("C") != 0
        or not all((scored.get("checks") or {}).values())
    ):
        raise ValueError("E011 scored result does not authorize E013")
    offline = _load_json(OFFLINE_GATE_PATH)
    if offline.get("status") != "PASS" or offline.get("lost_required_chunks") != []:
        raise ValueError("E006 offline retrieval gate mismatch")
    return snapshots


def _allowed_read_roots(output_dir: Path) -> list[Path]:
    return [
        (REPO_ROOT / "agent").resolve(),
        (REPO_ROOT / "public_dataset_upload/questions/group_a").resolve(),
        (REPO_ROOT / "processed_data/chunks.jsonl").resolve(),
        (REPO_ROOT / "processed_data/doc_meta.json").resolve(),
        SELECTION_PATH.resolve(),
        AUTHORIZATION_PATH.resolve(),
        E011_SCORED_RESULT_PATH.resolve(),
        CONTROL_REFERENCE_PATH.resolve(),
        OFFLINE_GATE_PATH.resolve(),
        RUN_FREEZE_PATH.resolve(),
        TLS_CA_BUNDLE_PATH.resolve(),
        CLAIM_PATH.resolve(),
        output_dir.resolve(),
    ]


def _claim_payload(run_freeze: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "e013-full-multi-claim/v1",
        "experiment_id": EXPERIMENT_ID,
        "run_id": RUN_ID,
        "attempt_nonce": str(run_freeze.get("attempt_nonce") or ""),
        "status": "FULL_MULTI_ATTEMPT_CLAIMED",
        "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
        "agent_code_snapshot_sha256": code_snapshot()["sha256"],
    }


def _claim_once(run_freeze: dict[str, Any]) -> str:
    if not CLAIM_PATH.parent.is_dir():
        raise ValueError("E013 registered output root must be precreated")
    payload = {**_claim_payload(run_freeze), "claimed_at": now_iso()}
    with CLAIM_PATH.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return sha256_file(CLAIM_PATH)


def _validate_result(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    judgments = result.get("option_judgments") or {}
    if sorted(judgments) != list("ABCD"):
        errors.append("option judgments are not exactly A/B/C/D")
    for option, judgment in judgments.items():
        if judgment.get("judgment") not in {"support", "refute", "insufficient"}:
            errors.append(f"{option}: invalid judgment")
        if judgment.get("error") is not None:
            errors.append(f"{option}: parser/API error: {judgment.get('error')}")
        if "evidence_refs" in judgment:
            errors.append(f"{option}: reference-free result contains evidence_refs")
        if int(judgment.get("retry_count") or 0) != 0:
            errors.append(f"{option}: retry count is not zero")
    answer = str(result.get("answer") or "")
    if not answer or any(letter not in "ABCD" for letter in answer):
        errors.append("normalized Multi answer is invalid")
    derivation = result.get("answer_derivation") or {}
    if (
        result.get("experiment_id") != EXPERIMENT_ID
        or result.get("experiment_arm") != "treatment"
        or derivation.get("method") != "agent.normalize_answer.normalize_answer"
        or derivation.get("output_answer") != answer
    ):
        errors.append("answer derivation identity/binding mismatch")
    return errors


def validate_full_multi_trace_contract(
    trace_report: dict[str, Any], *, trace_dir: Path, output_dir: Path
) -> list[str]:
    errors: list[str] = []
    manifest = trace_report.get("manifest") or {}
    config = manifest.get("config") or {}
    guard = manifest.get("blind_data_guard") or {}
    if manifest.get("candidate_eligible") is not False:
        errors.append("full expansion trace must not self-authorize candidate eligibility")
    if manifest.get("model") != {
        "provider": "dashscope-openai-compatible",
        "model": REQUESTED_MODEL,
        "base_url": OFFICIAL_DASHSCOPE_BASE_URL,
    }:
        errors.append("trace model/provider mismatch")
    expected_read = {
        display_path(path)
        for path in [*_allowed_read_roots(output_dir), *default_runtime_read_roots()]
    }
    expected_write = {display_path(output_dir.resolve()), display_path(CLAIM_PATH.resolve())}
    if (
        guard.get("enforced") is not True
        or guard.get("subprocess_blocked") is not True
        or set(map(str, guard.get("forbidden_roots") or []))
        != {display_path(path) for path in default_candidate_forbidden_roots()}
        or set(map(str, guard.get("allowed_read_roots") or [])) != expected_read
        or set(map(str, guard.get("allowed_write_roots") or [])) != expected_write
    ):
        errors.append("trace blind-data guard mismatch")
    run_freeze = _load_json(RUN_FREEZE_PATH)
    expected_config = {
        "runner": "agent.run_e013_full_multi",
        "experiment_id": EXPERIMENT_ID,
        "phase": "full_multi_expansion",
        "run_id": RUN_ID,
        "attempt_nonce": str(run_freeze.get("attempt_nonce") or ""),
        "claim_sha256": sha256_file(CLAIM_PATH),
        "pipeline_version": PIPELINE_VERSION,
        "online_parent_pipeline_version": "v2s1",
        "retrieval_control_profile": "v0-82041d0",
        "prompt_profile": PROMPT_PROFILE,
        "reference_profile": "trace_bound_with_doc_order",
        "trace_evidence_binding": "call.model_evidence",
        "enable_option_document_route": True,
        "qids": list(_official_multi_qids()),
        "top_k": V0_TOP_K,
        "selection_file": display_path(SELECTION_PATH),
        "selection_sha256": FROZEN_INPUT_SHA256["selection"],
        "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
        "output_dir": display_path(output_dir),
        "labels_accessed": False,
        "qid_doc_chunk_special_cases": False,
        "per_option_call_count": 1,
        "whole_question_review_calls": 0,
        "temperature": 0.0,
        "client_timeout_seconds": CLIENT_TIMEOUT_SECONDS,
        "client_max_retries": CLIENT_MAX_RETRIES,
        "ssl_cert_file": str(TLS_CA_BUNDLE_PATH),
        "ssl_cert_file_sha256": TLS_CA_BUNDLE_SHA256,
        "v0_retrieve_source_sha256": V0_RETRIEVE_SOURCE_SHA256,
        "route_thresholds": {
            "minimum_title_score": ROUTE_MIN_TITLE_SCORE,
            "minimum_longest_match": ROUTE_MIN_LONGEST_MATCH,
            "minimum_score_ratio": ROUTE_MIN_SCORE_RATIO,
            "minimum_score_margin": ROUTE_MIN_SCORE_MARGIN,
        },
        "input_artifacts": {
            **{name: input_artifact_snapshot(path) for name, path in {
                "questions": REPO_ROOT / "public_dataset_upload/questions/group_a",
                "chunks": REPO_ROOT / "processed_data/chunks.jsonl",
                "doc_meta": REPO_ROOT / "processed_data/doc_meta.json",
                "selection": SELECTION_PATH,
                "authorization": AUTHORIZATION_PATH,
                "e011_scored_result": E011_SCORED_RESULT_PATH,
                "control_reference": CONTROL_REFERENCE_PATH,
                "offline_gate": OFFLINE_GATE_PATH,
                "tls_ca_bundle": TLS_CA_BUNDLE_PATH,
            }.items()},
            "run_freeze": input_artifact_snapshot(RUN_FREEZE_PATH),
        },
    }
    if config != expected_config:
        errors.append("trace config differs from frozen E013 config")
    try:
        calls = [json.loads(line) for line in (trace_dir / "calls.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        derivations = [json.loads(line) for line in (trace_dir / "derivations.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        return [*errors, f"unable to inspect E013 trace: {exc}"]
    if len(calls) != LOGICAL_CALL_COUNT or len(derivations) != QUESTION_COUNT:
        errors.append("trace must contain 260 calls and 65 derivations")
    qids = list(_official_multi_qids())
    if [str(row.get("qid") or "") for row in derivations] != qids:
        errors.append("trace derivation qids/order mismatch")
    claimed: list[str] = []
    for row in derivations:
        call_ids = list(map(str, row.get("trace_call_ids") or []))
        inputs = (row.get("answer_derivation") or {}).get("input_judgments") or {}
        if len(call_ids) != 4 or len(set(call_ids)) != 4 or sorted(inputs) != list("ABCD"):
            errors.append(f"{row.get('qid')}: derivation topology mismatch")
        claimed.extend(call_ids)
    actual_ids = [str(call.get("call_id") or "") for call in calls]
    if len(claimed) != len(set(claimed)) or set(claimed) != set(actual_ids):
        errors.append("trace calls are orphaned/duplicated/cross-linked")
    questions = {str(item["qid"]): item for item in load_all_questions()}
    served_models: set[str] = set()
    for call in calls:
        context = call.get("context") or {}
        qid = str(context.get("qid") or "")
        option = str(context.get("option_key") or "")
        served_models.add(str(call.get("response_model") or ""))
        if context.get("stage") != "e009_treatment_option_judgment":
            errors.append(f"{qid}:{option}: stage mismatch")
        if context.get("prompt_profile") != PROMPT_PROFILE or context.get("reference_profile") != "trace_bound_with_doc_order":
            errors.append(f"{qid}:{option}: prompt/reference profile mismatch")
        if not call.get("provider_request_id") or call.get("tool_calls") != [] or call.get("finish_reason") != "stop":
            errors.append(f"{qid}:{option}: provider/tool/finish contract mismatch")
        attempts = call.get("attempts") or []
        if (
            not isinstance(attempts, list)
            or len(attempts) != 1
            or int(call.get("retry_count") or 0) != 0
            or not isinstance(attempts[0], dict)
            or attempts[0].get("status") != "success"
        ):
            errors.append(f"{qid}:{option}: zero-retry attempt mismatch")
        request = call.get("request_payload") or {}
        if request.get("model") != REQUESTED_MODEL or float(request.get("temperature", -1)) != 0.0:
            errors.append(f"{qid}:{option}: request model/temperature mismatch")
        if qid in questions and option in "ABCD":
            expected_messages = build_option_messages(
                questions[qid], option, str(context.get("option_text") or ""),
                list(call.get("model_evidence") or []), arm="treatment"
            )
            if request.get("messages") != expected_messages or call.get("messages") != expected_messages:
                errors.append(f"{qid}:{option}: messages differ from frozen builder")
        parsed, parse_error = parse_treatment_judgment(str(call.get("response_content") or ""), option)
        if parse_error or parsed.get("judgment") == "error":
            errors.append(f"{qid}:{option}: raw response fails strict parser")
    if served_models != {"qwen-plus"}:
        errors.append(f"actual served model must be exactly qwen-plus: {sorted(served_models)}")
    for qid in qids:
        qid_calls = [call for call in calls if str((call.get("context") or {}).get("qid") or "") == qid]
        if len(qid_calls) != 4 or sorted(str((call.get("context") or {}).get("option_key") or "") for call in qid_calls) != list("ABCD"):
            errors.append(f"{qid}: expected exactly one A/B/C/D call")
    return errors


def output_inventory_errors(directory: Path) -> list[str]:
    if not directory.is_dir():
        return ["registered full Multi output directory is missing"]
    errors: list[str] = []
    actual_top = {path.name for path in directory.iterdir()}
    if actual_top != {"observations.json", "run_receipt.json", "agent_traces"}:
        errors.append(f"output inventory mismatch: {sorted(actual_top)}")
    trace_root = directory / "agent_traces"
    trace_dirs = [path for path in trace_root.iterdir() if path.is_dir()] if trace_root.is_dir() else []
    if len(trace_dirs) != 1 or (trace_root.is_dir() and any(not path.is_dir() for path in trace_root.iterdir())):
        return [*errors, "expected exactly one trace directory"]
    if {path.name for path in trace_dirs[0].iterdir()} != {"calls.jsonl", "derivations.jsonl", "trace_manifest.json"}:
        errors.append("trace file inventory mismatch")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.selection.resolve() != SELECTION_PATH.resolve() or args.output_dir.resolve() != OUTPUT_DIR.resolve():
        raise ValueError("E013 must use its registered selection and output slot")
    if any(path.exists() for path in (
        OUTPUT_DIR, CLAIM_PATH, FULL_MULTI_RESULT_PATH, RERUN_BUNDLE_DIR,
        CANDIDATE_DIR, CANDIDATE_AUDIT_PATH, CANDIDATE_FREEZE_PATH,
    )):
        raise ValueError("E013 one-shot output/claim/candidate slot is already occupied")
    if os.environ.get("SSL_CERT_FILE") != str(TLS_CA_BUNDLE_PATH):
        raise ValueError("E013 requires SSL_CERT_FILE=/etc/ssl/cert.pem")
    if sha256_file(TLS_CA_BUNDLE_PATH) != TLS_CA_BUNDLE_SHA256:
        raise ValueError("E013 TLS CA bundle hash mismatch")
    try:
        client = QwenClient(model=REQUESTED_MODEL, timeout=CLIENT_TIMEOUT_SECONDS, max_retries=CLIENT_MAX_RETRIES)
    except MissingApiKeyError as exc:
        print(f"[error] {exc}")
        return 1
    if (
        client.model != REQUESTED_MODEL
        or client.base_url.rstrip("/") != OFFICIAL_DASHSCOPE_BASE_URL
        or client.max_retries != 0
        or float(client.timeout) != CLIENT_TIMEOUT_SECONDS
    ):
        raise ValueError("E013 Qwen client identity/config mismatch")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=False)
    trace_dir = OUTPUT_DIR / "agent_traces" / f"e013-full-multi-{uuid.uuid4()}"
    observations_path = OUTPUT_DIR / "observations.json"
    recorder: AgentTraceRecorder | None = None
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    try:
        with blind_data_guard(
            default_candidate_forbidden_roots(),
            allowed_read_roots=tuple(_allowed_read_roots(OUTPUT_DIR)),
            allowed_write_roots=(OUTPUT_DIR.resolve(), CLAIM_PATH.resolve()),
            block_subprocess=True,
        ):
            selection = _load_selection()
            frozen_inputs = _verify_frozen_inputs()
            run_freeze, run_freeze_snapshot = load_and_verify_run_freeze()
            frozen_inputs = {**frozen_inputs, "run_freeze": run_freeze_snapshot}
            qids = list(map(str, selection["qids"]))
            questions = {str(item["qid"]): item for item in load_all_questions()}
            _validate_questions(qids, questions)
            if any(questions[qid].get("answer_format") != "multi" for qid in qids):
                raise ValueError("E013 selection contains a non-Multi question")
            chunks = load_chunks()
            doc_meta = load_doc_meta()
            if not doc_meta:
                raise ValueError("E013 requires deterministic doc_meta")
            claim_sha256 = _claim_once(run_freeze)
            OUTPUT_DIR.mkdir(parents=True, exist_ok=False)
            config = {
                "runner": "agent.run_e013_full_multi",
                "experiment_id": EXPERIMENT_ID,
                "phase": "full_multi_expansion",
                "run_id": RUN_ID,
                "attempt_nonce": str(run_freeze.get("attempt_nonce") or ""),
                "claim_sha256": claim_sha256,
                "pipeline_version": PIPELINE_VERSION,
                "online_parent_pipeline_version": "v2s1",
                "retrieval_control_profile": "v0-82041d0",
                "prompt_profile": PROMPT_PROFILE,
                "reference_profile": "trace_bound_with_doc_order",
                "trace_evidence_binding": "call.model_evidence",
                "enable_option_document_route": True,
                "qids": qids,
                "top_k": V0_TOP_K,
                "selection_file": display_path(SELECTION_PATH),
                "selection_sha256": sha256_file(SELECTION_PATH),
                "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
                "output_dir": display_path(OUTPUT_DIR),
                "labels_accessed": False,
                "qid_doc_chunk_special_cases": False,
                "per_option_call_count": 1,
                "whole_question_review_calls": 0,
                "temperature": 0.0,
                "client_timeout_seconds": client.timeout,
                "client_max_retries": client.max_retries,
                "ssl_cert_file": str(TLS_CA_BUNDLE_PATH),
                "ssl_cert_file_sha256": TLS_CA_BUNDLE_SHA256,
                "v0_retrieve_source_sha256": V0_RETRIEVE_SOURCE_SHA256,
                "route_thresholds": {
                    "minimum_title_score": ROUTE_MIN_TITLE_SCORE,
                    "minimum_longest_match": ROUTE_MIN_LONGEST_MATCH,
                    "minimum_score_ratio": ROUTE_MIN_SCORE_RATIO,
                    "minimum_score_margin": ROUTE_MIN_SCORE_MARGIN,
                },
                "input_artifacts": frozen_inputs,
            }
            recorder = AgentTraceRecorder(
                trace_dir, purpose="e013_full_multi_expansion", model=client.model,
                base_url=client.base_url, config=config,
            )
            client.trace_recorder = recorder
            for qid in qids:
                question = questions[qid]
                diagnostics: dict[str, Any] = {}
                retrieval = retrieve_multi_v0_compatible(
                    question, chunks, enable_option_document_route=True, top_k=V0_TOP_K,
                    doc_meta=doc_meta, diagnostics_out=diagnostics,
                )
                judgments: dict[str, dict[str, Any]] = {}
                for option_key in "ABCD":
                    option = retrieval["options"][option_key]
                    judgment = judge_option(
                        client, question, option_key, option["option_text"],
                        option["evidence"], arm="treatment",
                    )
                    judgments[option_key] = judgment
                    if judgment.get("error"):
                        failures.append({"qid": qid, "error": f"{option_key}: {judgment['error']}"})
                        raise ValueError(f"fail-fast parser/API gate at {qid}:{option_key}: {judgment['error']}")
                result = build_question_result(question, judgments, arm="treatment")
                result["experiment_id"] = EXPERIMENT_ID
                result["technical_parent_experiment"] = "E009"
                result["retrieval"] = _compact_retrieval(retrieval)
                result["route_diagnostics"] = diagnostics
                errors = _validate_result(result)
                if errors:
                    failures.extend({"qid": qid, "error": error} for error in errors)
                    raise ValueError(f"fail-fast result gate at {qid}: {errors}")
                results.append(result)
                recorder.record_derivation(result)
            payload = {
                "schema_version": "e013-full-multi-observations/v1",
                "experiment_id": EXPERIMENT_ID,
                "phase": "full_multi_expansion",
                "run_id": RUN_ID,
                "attempt_nonce": str(run_freeze.get("attempt_nonce") or ""),
                "claim_sha256": claim_sha256,
                "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
                "pipeline_version": PIPELINE_VERSION,
                "selection_file": display_path(SELECTION_PATH),
                "selection_sha256": sha256_file(SELECTION_PATH),
                "labels_accessed": False,
                "qids": qids,
                "started_from_empty_directory": True,
                "completed_at": now_iso(),
                "question_count": len(results),
                "api_call_count": sum(len(result.get("option_judgments", {})) for result in results),
                "prompt_tokens": sum(int(result.get("prompt_tokens") or 0) for result in results),
                "completion_tokens": sum(int(result.get("completion_tokens") or 0) for result in results),
                "total_tokens": sum(int(result.get("total_tokens") or 0) for result in results),
                "failures": failures,
                "observations": results,
                "agent_trace": {
                    "schema_version": "agent-trace/v1",
                    "trace_run_id": recorder.run_id,
                    "trace_dir": display_path(recorder.trace_dir),
                    "candidate_eligible": False,
                },
            }
            observations_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            recorder.finalize(output_paths=(observations_path,), failures=failures)
    except Exception as exc:
        if recorder is not None and recorder.manifest.get("status") == "recording":
            recorder.finalize(output_paths=None, failures=[{"qid": "", "error": str(exc)}])
        print(f"[error] {exc}")
        return 1
    trace_report = validate_trace_directory(
        recorder.trace_dir, require_candidate_eligible=False, require_current_code_match=True,
    )
    trace_errors = validate_full_multi_trace_contract(
        trace_report, trace_dir=recorder.trace_dir, output_dir=OUTPUT_DIR,
    )
    trace_report.setdefault("errors", []).extend(trace_errors)
    trace_report["ok"] = not trace_report.get("errors")
    calls = [json.loads(line) for line in recorder.calls_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    physical_attempts = sum(len(call.get("attempts") or []) for call in calls)
    served_models = sorted({str(call.get("response_model") or "") for call in calls})
    receipt = {
        "schema_version": "e013-full-multi-run-receipt/v1",
        "experiment_id": EXPERIMENT_ID,
        "phase": "full_multi_expansion",
        "run_id": RUN_ID,
        "attempt_nonce": str(run_freeze.get("attempt_nonce") or ""),
        "claim_sha256": claim_sha256,
        "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
        "status": "PASS" if trace_report["ok"] and not failures else "FAIL",
        "selection_sha256": sha256_file(SELECTION_PATH),
        "observations_sha256": sha256_file(observations_path),
        "trace_run_id": recorder.run_id,
        "trace_manifest_sha256": sha256_file(recorder.manifest_path),
        "code_sha256": (trace_report.get("manifest") or {}).get("code", {}).get("sha256"),
        "config_sha256": (trace_report.get("manifest") or {}).get("config_sha256"),
        "model_sha256": (trace_report.get("manifest") or {}).get("model_sha256"),
        "input_artifacts_sha256": sha256_json(frozen_inputs),
        "pipeline_version": PIPELINE_VERSION,
        "served_models": served_models,
        "call_count": trace_report.get("call_count"),
        "logical_call_count": trace_report.get("call_count"),
        "physical_attempt_count": physical_attempts,
        "max_retries_per_logical_call": 0,
        "derivation_count": trace_report.get("derivation_count"),
        "prompt_tokens": sum(int(result.get("prompt_tokens") or 0) for result in results),
        "completion_tokens": sum(int(result.get("completion_tokens") or 0) for result in results),
        "total_tokens": sum(int(result.get("total_tokens") or 0) for result in results),
        "errors": [*trace_report.get("errors", []), *(failure["error"] for failure in failures)],
        "created_at": now_iso(),
    }
    (OUTPUT_DIR / "run_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    inventory_errors = output_inventory_errors(OUTPUT_DIR)
    if receipt["status"] != "PASS" or inventory_errors:
        for error in [*receipt["errors"], *inventory_errors]:
            print(f"[e013-full-multi-error] {error}")
        return 1
    print(
        f"E013 full Multi=PASS questions={QUESTION_COUNT} calls={LOGICAL_CALL_COUNT} "
        f"tokens={receipt['total_tokens']} served_model={served_models[0]} output={OUTPUT_DIR}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
