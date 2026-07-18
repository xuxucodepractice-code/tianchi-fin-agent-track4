"""Run one governed, label-blind E006 prospective primary/repeat arm."""

from __future__ import annotations

import argparse
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.doc_meta import load_doc_meta
from agent.load_questions import load_all_questions
from agent.paths import REPO_ROOT
from agent.qwen_client import MissingApiKeyError, QwenClient
from agent.reason_multi_v0_compat import (
    E006_PIPELINE_VERSION,
    V0_PROMPTS_SOURCE_SHA256,
    reason_multi_with_v0_prompt,
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
from agent.run_e006_paired_arm import (
    CONTROL_REFERENCE_PATH,
    EXPECTED_CONTROL_RETRIEVAL_SHA256,
    EXPERIMENT_DIR,
    OFFLINE_GATE_PATH,
    _compact_retrieval,
    _validate_questions,
    _validate_result,
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
    load_frozen_selection,
    now_iso,
    resolve_recorded_path,
    sha256_file,
    sha256_json,
    validate_trace_directory,
)

ATTEMPTS = {"primary", "repeat"}
PAIR_ID = "e006-prospective-pair-01"
PROSPECTIVE_SELECTION_PATH = EXPERIMENT_DIR / "prospective_trace_selection.json"
SOURCE_SELECTION_PATH = EXPERIMENT_DIR / "prospective_source_selection.json"
AUTHORIZATION_PATH = EXPERIMENT_DIR / "prospective_authorization.json"
RUN_FREEZE_PATH = EXPERIMENT_DIR / "prospective_run_freeze.json"
OUTPUT_ROOT = REPO_ROOT / "outputs" / "experiments" / "E006_multi_retrieval_coverage"
EXPECTED_OUTPUT_DIRS = {
    "primary": OUTPUT_ROOT / "prospective_primary_01",
    "repeat": OUTPUT_ROOT / "prospective_repeat_01",
}
PRIMARY_CLAIM_PATH = OUTPUT_ROOT / "prospective_primary_claim.json"
REPEAT_CLAIM_PATH = OUTPUT_ROOT / "prospective_repeat_claim.json"
CHURN_REPORT_PATH = OUTPUT_ROOT / "prospective_churn.json"
PROSPECTIVE_LABELS_PATH = EXPERIMENT_DIR / "prospective_labels.json"
PROSPECTIVE_SCORED_RESULT_PATH = EXPERIMENT_DIR / "prospective_scored_result.json"
RUNNER_PATH = REPO_ROOT / "agent" / "run_e006_prospective_arm.py"
CHURN_EVALUATOR_PATH = REPO_ROOT / "agent" / "evaluate_e006_prospective_churn.py"
REQUESTED_MODEL = "qwen-plus"
CLIENT_TIMEOUT_SECONDS = 90.0
CLIENT_MAX_RETRIES = 2
PROSPECTIVE_QIDS = (
    "fc_a_004",
    "fc_a_014",
    "fc_a_009",
    "fin_a_001",
    "fin_a_011",
    "fin_a_016",
    "ins_a_011",
    "ins_a_018",
    "ins_a_008",
    "reg_a_004",
    "reg_a_005",
    "reg_a_019",
    "res_a_002",
    "res_a_005",
    "res_a_016",
)
FROZEN_INPUT_SHA256 = {
    "questions": "c33dde8ac97d8a00ef3796f4312274cea74fce699f52b15c006c45fab80c0676",
    "chunks": "02aa2f9b33f304a4d9a74789acc5aa47ec9efff42d7a68bdd2390e7cea30a878",
    "doc_meta": "df9af050cce73707536d2798f62b1e4640747d4cfe595b2e12cddd22d6d472d7",
    "source_selection": "bc0cecefb1298f193da33efc293e96d2340aa223cd1a97599ba3305d39e5e5df",
    "selection": "3aa92d11ee886bc160adec3578bbf9e6d30c0f9633a4652fc7ff0d7d2f1014b3",
    "authorization": "1d469a89f3d859ae92af76adf101cd41fd2ac1b6619f1e8414fa88b6ff68812c",
    "control_reference": "db90509ba127f662b333e07664e79ff7ce0264db9f1b3cbb34cca177d10d4572",
    "offline_gate": "6c7ec2a4ff7b9efefe8923bb8c5a8d18e0e7f8f69e63b1b8eba2c8cb50a9b7b0",
}


def validate_run_freeze_payload(
    payload: dict[str, Any],
    *,
    current_code_snapshot: dict[str, Any],
) -> list[str]:
    """Validate the post-code-freeze authorization without a self-hash cycle."""
    errors: list[str] = []
    expected_paths = {
        "primary_output_dir": display_path(EXPECTED_OUTPUT_DIRS["primary"]),
        "repeat_output_dir": display_path(EXPECTED_OUTPUT_DIRS["repeat"]),
        "primary_claim": display_path(PRIMARY_CLAIM_PATH),
        "repeat_claim": display_path(REPEAT_CLAIM_PATH),
        "churn_report": display_path(CHURN_REPORT_PATH),
        "labels": display_path(PROSPECTIVE_LABELS_PATH),
        "scored_result": display_path(PROSPECTIVE_SCORED_RESULT_PATH),
    }
    expected_code_files = {
        "runner": {
            "path": display_path(RUNNER_PATH),
            "sha256": sha256_file(RUNNER_PATH),
        },
        "churn_evaluator": {
            "path": display_path(CHURN_EVALUATOR_PATH),
            "sha256": sha256_file(CHURN_EVALUATOR_PATH),
        },
    }
    if payload.get("schema_version") != "e006-prospective-run-freeze/v1":
        errors.append("run freeze schema mismatch")
    if payload.get("freeze_id") != "E006_PROSPECTIVE_PAIR_01_2026-07-18":
        errors.append("run freeze id mismatch")
    if (
        payload.get("experiment_id") != "E006"
        or payload.get("phase") != "prospective"
        or payload.get("pair_id") != PAIR_ID
        or payload.get("status") != "AUTHORIZED_TO_RUN_PRIMARY_REPEAT"
    ):
        errors.append("run freeze identity/status mismatch")
    source_commit = str(payload.get("source_code_commit") or "")
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        errors.append("run freeze source commit is not a full Git SHA")
    try:
        datetime.fromisoformat(str(payload["created_at"]))
    except (KeyError, TypeError, ValueError):
        errors.append("run freeze created_at is not ISO-8601")
    if payload.get("agent_code_snapshot_sha256") != current_code_snapshot.get(
        "sha256"
    ):
        errors.append("run freeze agent code snapshot differs from current code")
    if payload.get("code_files") != expected_code_files:
        errors.append("run freeze runner/evaluator hashes mismatch")
    if tuple(map(str, payload.get("qids") or [])) != PROSPECTIVE_QIDS:
        errors.append("run freeze qids/order mismatch")
    if payload.get("frozen_input_sha256") != FROZEN_INPUT_SHA256:
        errors.append("run freeze input hashes mismatch")
    if payload.get("authorization_basis") != {
        "path": display_path(AUTHORIZATION_PATH),
        "sha256": FROZEN_INPUT_SHA256["authorization"],
        "required_status": "AUTHORIZED_TO_PREREGISTER_PRIMARY_REPEAT",
    }:
        errors.append("run freeze authorization basis mismatch")
    if payload.get("registered_paths") != expected_paths:
        errors.append("run freeze registered paths mismatch")
    if payload.get("pipeline_version") != E006_PIPELINE_VERSION:
        errors.append("run freeze pipeline mismatch")
    if payload.get("pipeline") != {
        "pipeline_version": E006_PIPELINE_VERSION,
        "online_parent_pipeline_version": "v2s1",
        "retrieval_control_profile": "v0-82041d0",
        "prompt_profile": "v0-82041d0",
        "enable_option_document_route": True,
        "top_k": V0_TOP_K,
        "route_thresholds": {
            "minimum_title_score": ROUTE_MIN_TITLE_SCORE,
            "minimum_longest_match": ROUTE_MIN_LONGEST_MATCH,
            "minimum_score_ratio": ROUTE_MIN_SCORE_RATIO,
            "minimum_score_margin": ROUTE_MIN_SCORE_MARGIN,
        },
        "v0_retrieve_source_sha256": V0_RETRIEVE_SOURCE_SHA256,
        "v0_prompts_source_sha256": V0_PROMPTS_SOURCE_SHA256,
        "per_option_call_count": 1,
        "whole_question_review_calls": 0,
    }:
        errors.append("run freeze pipeline configuration mismatch")
    if payload.get("model") != {
        "provider": "dashscope-openai-compatible",
        "requested_model": REQUESTED_MODEL,
        "base_url": OFFICIAL_DASHSCOPE_BASE_URL,
        "endpoint": f"{OFFICIAL_DASHSCOPE_BASE_URL}/chat/completions",
        "temperature": 0.0,
        "timeout_seconds": CLIENT_TIMEOUT_SECONDS,
        "max_retries": CLIENT_MAX_RETRIES,
        "served_model_policy": {
            "required_prefix": "qwen-plus",
            "one_exact_value_per_attempt": True,
            "same_exact_value_across_attempts": True,
        },
    }:
        errors.append("run freeze model/client policy mismatch")
    if payload.get("call_topology") != {
        "question_count_per_attempt": 15,
        "logical_calls_per_attempt": 60,
        "derivations_per_attempt": 15,
        "physical_attempts_min": 60,
        "physical_attempts_max": 180,
    }:
        errors.append("run freeze call topology mismatch")
    nonces = payload.get("attempt_nonces") or {}
    if set(nonces) != ATTEMPTS or any(
        re.fullmatch(r"[0-9a-f]{32}", str(nonces.get(name) or "")) is None
        for name in ATTEMPTS
    ):
        errors.append("run freeze attempt nonces missing/invalid")
    if payload.get("initial_state") != {
        "primary_output_exists": False,
        "repeat_output_exists": False,
        "primary_claim_exists": False,
        "repeat_claim_exists": False,
        "churn_report_exists": False,
        "labels_created": False,
        "labels_revealed": False,
        "scored_result_exists": False,
    }:
        errors.append("run freeze initial-state declaration mismatch")
    if payload.get("scoring_policy") != {
        "scoring_arm": "primary",
        "repeat_non_scoring": True,
        "failed_or_partial_attempt_may_be_retried": False,
        "output_or_claim_may_be_deleted_or_replaced": False,
    }:
        errors.append("run freeze scoring/failure policy mismatch")
    if payload.get("label_isolation") != {
        "status": "LABELS_SEALED",
        "labels_created": False,
        "labels_revealed_to_generation": False,
        "labels_must_remain_absent_through_churn_freeze": True,
    }:
        errors.append("run freeze label-isolation policy mismatch")
    if payload.get("candidate_authorized") is not False or payload.get(
        "submission_authorized"
    ) is not False:
        errors.append("run freeze must not authorize candidate/submission")
    return errors


def _load_and_verify_run_freeze() -> tuple[dict[str, Any], dict[str, Any]]:
    payload = _load_json(RUN_FREEZE_PATH)
    snapshot = code_snapshot()
    errors = validate_run_freeze_payload(
        payload,
        current_code_snapshot=snapshot,
    )
    if errors:
        raise ValueError(f"E006 prospective run freeze invalid: {errors}")
    return payload, input_artifact_snapshot(RUN_FREEZE_PATH)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _load_selection(path: Path) -> dict[str, Any]:
    if path.resolve() != PROSPECTIVE_SELECTION_PATH.resolve():
        raise ValueError("prospective run must use the governed selection path")
    if sha256_file(path) != FROZEN_INPUT_SHA256["selection"]:
        raise ValueError("prospective selection SHA256 mismatch")
    payload = load_frozen_selection(path)
    if tuple(map(str, payload["qids"])) != PROSPECTIVE_QIDS:
        raise ValueError("prospective qids/order differ from the frozen 15")
    if tuple(map(str, payload["prospective_qids"])) != PROSPECTIVE_QIDS:
        raise ValueError("prospective partition differs from the frozen 15")
    if payload["known_before_freeze_qids"] != []:
        raise ValueError("prospective selection contains known-label qids")
    if payload.get("source_selection_sha256") != FROZEN_INPUT_SHA256[
        "source_selection"
    ]:
        raise ValueError("prospective source selection hash mismatch")
    return payload


def _verify_frozen_inputs(selection_path: Path) -> dict[str, dict[str, Any]]:
    paths = {
        "questions": REPO_ROOT / "public_dataset_upload" / "questions" / "group_a",
        "chunks": REPO_ROOT / "processed_data" / "chunks.jsonl",
        "doc_meta": REPO_ROOT / "processed_data" / "doc_meta.json",
        "source_selection": SOURCE_SELECTION_PATH,
        "selection": selection_path,
        "authorization": AUTHORIZATION_PATH,
        "control_reference": CONTROL_REFERENCE_PATH,
        "offline_gate": OFFLINE_GATE_PATH,
    }
    snapshots = {name: input_artifact_snapshot(path) for name, path in paths.items()}
    mismatches = {
        name: (snapshot.get("sha256"), FROZEN_INPUT_SHA256[name])
        for name, snapshot in snapshots.items()
        if snapshot.get("sha256") != FROZEN_INPUT_SHA256[name]
    }
    if mismatches:
        raise ValueError(f"E006 prospective frozen input mismatch: {mismatches}")

    source = _load_json(SOURCE_SELECTION_PATH)
    if (
        source.get("schema_version") != "e004-prospective-selection/v1"
        or source.get("frozen_before_labeling") is not True
        or source.get("labels_created") is not False
        or source.get("labels_revealed_to_generation") is not False
        or tuple(map(str, source.get("qids") or [])) != PROSPECTIVE_QIDS
    ):
        raise ValueError("prospective source selection semantics mismatch")
    authorization = _load_json(AUTHORIZATION_PATH)
    if (
        authorization.get("status") != "AUTHORIZED_TO_PREREGISTER_PRIMARY_REPEAT"
        or authorization.get("development_decision") != "DEVELOPMENT_GATE_PASS"
        or int(authorization.get("development_paired_net") or 0) != 3
        or int(authorization.get("development_parent_regressions", -1)) != 0
        or int(authorization.get("development_bundle_errors", -1)) != 0
        or authorization.get("independent_audit") != "PASS"
        or authorization.get("labels_created") is not False
        or authorization.get("labels_revealed") is not False
        or authorization.get("candidate_authorized") is not False
        or authorization.get("submission_authorized") is not False
    ):
        raise ValueError("prospective authorization semantics mismatch")
    control_reference = _load_json(CONTROL_REFERENCE_PATH)
    if (
        control_reference.get("canonical_multi_retrieval_sha256")
        != EXPECTED_CONTROL_RETRIEVAL_SHA256
    ):
        raise ValueError("control reference semantics mismatch")
    offline = _load_json(OFFLINE_GATE_PATH)
    if (
        offline.get("status") != "PASS"
        or (offline.get("control_reproduction") or {}).get(
            "computed_canonical_sha256"
        )
        != EXPECTED_CONTROL_RETRIEVAL_SHA256
        or offline.get("lost_required_chunks") != []
    ):
        raise ValueError("offline retrieval gate semantics mismatch")
    return snapshots


def validate_prospective_trace_contract(
    trace_report: dict[str, Any],
    *,
    trace_dir: Path,
    attempt: str,
    output_dir: Path,
) -> list[str]:
    errors: list[str] = []
    manifest = trace_report.get("manifest") or {}
    config = manifest.get("config") or {}
    model = manifest.get("model") or {}
    guard = manifest.get("blind_data_guard") or {}
    expected_read_paths = [
        (REPO_ROOT / "agent").resolve(),
        (REPO_ROOT / "public_dataset_upload" / "questions" / "group_a").resolve(),
        (REPO_ROOT / "processed_data" / "chunks.jsonl").resolve(),
        (REPO_ROOT / "processed_data" / "doc_meta.json").resolve(),
        SOURCE_SELECTION_PATH.resolve(),
        PROSPECTIVE_SELECTION_PATH.resolve(),
        AUTHORIZATION_PATH.resolve(),
        RUN_FREEZE_PATH.resolve(),
        CONTROL_REFERENCE_PATH.resolve(),
        OFFLINE_GATE_PATH.resolve(),
        PRIMARY_CLAIM_PATH.resolve(),
        output_dir.resolve(),
        *default_runtime_read_roots(),
    ]
    if attempt == "repeat":
        expected_read_paths.extend(
            [REPEAT_CLAIM_PATH.resolve(), EXPECTED_OUTPUT_DIRS["primary"].resolve()]
        )
    expected_read = {
        display_path(path)
        for path in expected_read_paths
    }
    expected_write = {
        display_path(output_dir.resolve()),
        display_path(
            PRIMARY_CLAIM_PATH.resolve()
            if attempt == "primary"
            else REPEAT_CLAIM_PATH.resolve()
        ),
    }
    if model != {
        "provider": "dashscope-openai-compatible",
        "model": "qwen-plus",
        "base_url": OFFICIAL_DASHSCOPE_BASE_URL,
    }:
        errors.append("prospective model/provider mismatch")
    if guard.get("enforced") is not True or guard.get("subprocess_blocked") is not True:
        errors.append("prospective blind-data guard not fully enforced")
    if set(map(str, guard.get("forbidden_roots") or [])) != {
        display_path(path) for path in default_candidate_forbidden_roots()
    }:
        errors.append("prospective forbidden roots mismatch")
    if set(map(str, guard.get("allowed_read_roots") or [])) != expected_read:
        errors.append("prospective read allowlist mismatch")
    if set(map(str, guard.get("allowed_write_roots") or [])) != expected_write:
        errors.append("prospective write allowlist mismatch")
    if config.get("runner") != "agent.run_e006_prospective_arm":
        errors.append("prospective runner identity mismatch")
    if config.get("experiment_id") != "E006" or config.get("phase") != "prospective":
        errors.append("prospective experiment/phase mismatch")
    if config.get("pair_id") != PAIR_ID or config.get("attempt") != attempt:
        errors.append("prospective pair/attempt mismatch")
    if config.get("pipeline_version") != E006_PIPELINE_VERSION:
        errors.append("prospective pipeline mismatch")
    if config.get("enable_option_document_route") is not True:
        errors.append("prospective treatment route is not enabled")
    if (
        config.get("online_parent_pipeline_version") != "v2s1"
        or config.get("retrieval_control_profile") != "v0-82041d0"
        or config.get("prompt_profile") != "v0-82041d0"
        or int(config.get("per_option_call_count") or 0) != 1
        or int(config.get("whole_question_review_calls", -1)) != 0
        or config.get("v0_retrieve_source_sha256") != V0_RETRIEVE_SOURCE_SHA256
        or config.get("v0_prompts_source_sha256") != V0_PROMPTS_SOURCE_SHA256
        or config.get("route_thresholds")
        != {
            "minimum_title_score": ROUTE_MIN_TITLE_SCORE,
            "minimum_longest_match": ROUTE_MIN_LONGEST_MATCH,
            "minimum_score_ratio": ROUTE_MIN_SCORE_RATIO,
            "minimum_score_margin": ROUTE_MIN_SCORE_MARGIN,
        }
    ):
        errors.append("prospective frozen pipeline configuration mismatch")
    if tuple(map(str, config.get("qids") or [])) != PROSPECTIVE_QIDS:
        errors.append("prospective trace qids/order mismatch")
    if config.get("selection_sha256") != FROZEN_INPUT_SHA256["selection"]:
        errors.append("prospective trace selection hash mismatch")
    if config.get("run_freeze_sha256") != sha256_file(RUN_FREEZE_PATH):
        errors.append("prospective trace run-freeze hash mismatch")
    run_freeze = _load_json(RUN_FREEZE_PATH)
    expected_nonce = str((run_freeze.get("attempt_nonces") or {}).get(attempt) or "")
    if config.get("attempt_nonce") != expected_nonce:
        errors.append("prospective trace attempt nonce mismatch")
    if config.get("selection_file") != display_path(PROSPECTIVE_SELECTION_PATH):
        errors.append("prospective trace selection path mismatch")
    if config.get("output_dir") != display_path(output_dir.resolve()):
        errors.append("prospective output path mismatch")
    if output_dir.resolve() != EXPECTED_OUTPUT_DIRS[attempt].resolve():
        errors.append("prospective output is outside registered attempt slot")
    if int(config.get("top_k") or 0) != V0_TOP_K or float(
        config.get("temperature", -1)
    ) != 0.0:
        errors.append("prospective top_k/temperature mismatch")
    if int(config.get("client_max_retries", -1)) != 2 or float(
        config.get("client_timeout_seconds", -1)
    ) != 90.0:
        errors.append("prospective retry/timeout policy mismatch")
    artifact_hashes = {
        name: str((entry or {}).get("sha256") or "")
        for name, entry in (config.get("input_artifacts") or {}).items()
    }
    expected_artifact_hashes = {
        **FROZEN_INPUT_SHA256,
        "run_freeze": sha256_file(RUN_FREEZE_PATH),
    }
    if artifact_hashes != expected_artifact_hashes:
        errors.append("prospective input hashes mismatch")
    if (
        not PRIMARY_CLAIM_PATH.is_file()
        or config.get("primary_claim_sha256") != sha256_file(PRIMARY_CLAIM_PATH)
    ):
        errors.append("prospective trace primary claim mismatch")
    if attempt == "primary" and (
        config.get("primary_anchor") is not None
        or config.get("repeat_claim_sha256") is not None
    ):
        errors.append("primary must not contain repeat anchor/claim")
    if attempt == "repeat" and (
        not isinstance(config.get("primary_anchor"), dict)
        or not REPEAT_CLAIM_PATH.is_file()
        or config.get("repeat_claim_sha256") != sha256_file(REPEAT_CLAIM_PATH)
    ):
        errors.append("repeat lacks primary anchor/claim")

    try:
        calls = [
            json.loads(line)
            for line in (trace_dir / "calls.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        derivations = [
            json.loads(line)
            for line in (trace_dir / "derivations.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [*errors, f"unable to inspect prospective trace: {exc}"]
    if len(calls) != 60 or len(derivations) != 15:
        errors.append("prospective trace must contain 60 calls/15 derivations")
    if [str(row.get("qid") or "") for row in derivations] != list(PROSPECTIVE_QIDS):
        errors.append("prospective derivation qids/order mismatch")
    claimed: list[str] = []
    for row in derivations:
        call_ids = list(map(str, row.get("trace_call_ids") or []))
        inputs = (row.get("answer_derivation") or {}).get("input_judgments") or {}
        if len(call_ids) != 4 or len(set(call_ids)) != 4:
            errors.append(f"{row.get('qid')}: derivation call topology mismatch")
        if sorted(inputs) != list("ABCD"):
            errors.append(f"{row.get('qid')}: derivation judgments are not A/B/C/D")
        claimed.extend(call_ids)
    actual_ids = [str(call.get("call_id") or "") for call in calls]
    if len(claimed) != len(set(claimed)) or set(claimed) != set(actual_ids):
        errors.append("prospective calls are orphaned/duplicated/cross-linked")
    for qid in PROSPECTIVE_QIDS:
        qid_calls = [
            call for call in calls if str((call.get("context") or {}).get("qid") or "") == qid
        ]
        if len(qid_calls) != 4 or sorted(
            str((call.get("context") or {}).get("option_key") or "")
            for call in qid_calls
        ) != list("ABCD"):
            errors.append(f"{qid}: expected exactly one A/B/C/D call")
    for call in calls:
        context = call.get("context") or {}
        qid = str(context.get("qid") or "")
        option = str(context.get("option_key") or "")
        if context.get("stage") != "e006_treatment_v0_option_judgment":
            errors.append(f"{qid}:{option}: prospective call stage mismatch")
        if context.get("prompt_profile") != "v0-82041d0":
            errors.append(f"{qid}:{option}: prompt profile mismatch")
        if not call.get("provider_request_id"):
            errors.append(f"{qid}:{option}: provider request id missing")
        if not str(call.get("response_model") or "").startswith("qwen-plus"):
            errors.append(f"{qid}:{option}: served model mismatch")
        if call.get("tool_calls") != [] or call.get("finish_reason") != "stop":
            errors.append(f"{qid}:{option}: tool/finish contract mismatch")
        attempts = call.get("attempts") or []
        if not isinstance(attempts, list) or not 1 <= len(attempts) <= 3:
            errors.append(f"{qid}:{option}: physical attempt count outside 1..3")
        else:
            for index, physical in enumerate(attempts, start=1):
                expected_status = "success" if index == len(attempts) else "error"
                if (
                    not isinstance(physical, dict)
                    or int(physical.get("attempt") or 0) != index
                    or physical.get("status") != expected_status
                ):
                    errors.append(f"{qid}:{option}: invalid retry attempt sequence")
                    break
            if int(call.get("retry_count") or 0) != len(attempts) - 1:
                errors.append(f"{qid}:{option}: retry_count mismatch")
        request = call.get("request_payload") or {}
        if request.get("model") != "qwen-plus" or float(
            request.get("temperature", -1)
        ) != 0.0:
            errors.append(f"{qid}:{option}: request model/temperature mismatch")
    return errors


def output_inventory_errors(directory: Path, *, attempt: str) -> list[str]:
    """Require the exact registered artifact inventory for a completed arm."""
    errors: list[str] = []
    if not directory.is_dir():
        return [f"{attempt}: registered output directory is missing"]
    expected_top = {"observations.json", "run_receipt.json", "agent_traces"}
    actual_top = {path.name for path in directory.iterdir()}
    if actual_top != expected_top:
        errors.append(
            f"{attempt}: output inventory mismatch: {sorted(actual_top)}"
        )
    trace_root = directory / "agent_traces"
    if not trace_root.is_dir():
        return [*errors, f"{attempt}: agent_traces directory missing"]
    trace_dirs = [path for path in trace_root.iterdir() if path.is_dir()]
    non_dirs = [path.name for path in trace_root.iterdir() if not path.is_dir()]
    if len(trace_dirs) != 1 or non_dirs:
        errors.append(f"{attempt}: expected exactly one trace directory")
        return errors
    trace_files = {path.name for path in trace_dirs[0].iterdir()}
    if trace_files != {"calls.jsonl", "derivations.jsonl", "trace_manifest.json"}:
        errors.append(f"{attempt}: trace file inventory mismatch: {sorted(trace_files)}")
    return errors


def _verify_registered_slot_state(*, attempt: str) -> None:
    """Enforce one-shot slots before consuming an attempt claim."""
    if CHURN_REPORT_PATH.exists():
        raise ValueError("prospective churn report already exists")
    if PROSPECTIVE_LABELS_PATH.exists() or PROSPECTIVE_SCORED_RESULT_PATH.exists():
        raise ValueError("prospective labels/result exist before churn freeze")
    if attempt == "primary":
        occupied = [
            path
            for path in (
                EXPECTED_OUTPUT_DIRS["primary"],
                EXPECTED_OUTPUT_DIRS["repeat"],
                PRIMARY_CLAIM_PATH,
                REPEAT_CLAIM_PATH,
            )
            if path.exists()
        ]
        if occupied:
            raise ValueError(
                "prospective primary one-shot slot is already occupied: "
                f"{[display_path(path) for path in occupied]}"
            )
        return
    primary_errors = output_inventory_errors(
        EXPECTED_OUTPUT_DIRS["primary"], attempt="primary"
    )
    if primary_errors:
        raise ValueError(f"prospective primary inventory invalid: {primary_errors}")
    occupied = [
        path
        for path in (
            EXPECTED_OUTPUT_DIRS["repeat"],
            REPEAT_CLAIM_PATH,
        )
        if path.exists()
    ]
    if occupied:
        raise ValueError(
            "prospective repeat one-shot slot is already occupied: "
            f"{[display_path(path) for path in occupied]}"
        )


def _primary_claim_payload(run_freeze: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "e006-prospective-primary-claim/v1",
        "experiment_id": "E006",
        "pair_id": PAIR_ID,
        "attempt": "primary",
        "attempt_nonce": str((run_freeze.get("attempt_nonces") or {}).get("primary") or ""),
        "status": "PRIMARY_ATTEMPT_CLAIMED",
        "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
        "agent_code_snapshot_sha256": code_snapshot()["sha256"],
    }


def _claim_primary_once(run_freeze: dict[str, Any]) -> str:
    claim = {**_primary_claim_payload(run_freeze), "claimed_at": now_iso()}
    with PRIMARY_CLAIM_PATH.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(claim, ensure_ascii=False, indent=2) + "\n")
    return sha256_file(PRIMARY_CLAIM_PATH)


def _verify_primary_claim(run_freeze: dict[str, Any]) -> str:
    if not PRIMARY_CLAIM_PATH.is_file():
        raise ValueError("registered prospective primary claim is missing")
    claim = _load_json(PRIMARY_CLAIM_PATH)
    expected = _primary_claim_payload(run_freeze)
    mismatches = {
        key: (claim.get(key), value)
        for key, value in expected.items()
        if claim.get(key) != value
    }
    try:
        datetime_value = str(claim["claimed_at"])
        if not datetime_value:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        mismatches["claimed_at"] = (claim.get("claimed_at"), "non-empty ISO time")
    if mismatches:
        raise ValueError(f"prospective primary claim mismatch: {mismatches}")
    return sha256_file(PRIMARY_CLAIM_PATH)


def _verified_primary_anchor(
    run_freeze: dict[str, Any], primary_claim_sha256: str
) -> dict[str, str]:
    primary_dir = EXPECTED_OUTPUT_DIRS["primary"]
    observations_path = primary_dir / "observations.json"
    receipt_path = primary_dir / "run_receipt.json"
    if not observations_path.is_file() or not receipt_path.is_file():
        raise ValueError("prospective repeat requires registered primary first")
    observations = _load_json(observations_path)
    receipt = _load_json(receipt_path)
    trace_dir = resolve_recorded_path(
        str((observations.get("agent_trace") or {}).get("trace_dir") or "")
    )
    trace_report = validate_trace_directory(
        trace_dir,
        require_candidate_eligible=False,
        require_current_code_match=True,
    )
    strict_errors = validate_prospective_trace_contract(
        trace_report,
        trace_dir=trace_dir,
        attempt="primary",
        output_dir=primary_dir,
    )
    strict_errors.extend(output_inventory_errors(primary_dir, attempt="primary"))
    if not trace_report.get("ok") or strict_errors:
        raise ValueError(
            "registered prospective primary failed strict validation: "
            f"{[*trace_report.get('errors', []), *strict_errors]}"
        )
    anchor = {
        "pair_id": PAIR_ID,
        "primary_claim_sha256": primary_claim_sha256,
        "primary_trace_run_id": str(
            (observations.get("agent_trace") or {}).get("trace_run_id") or ""
        ),
        "primary_observations_sha256": sha256_file(observations_path),
        "primary_trace_manifest_sha256": sha256_file(trace_dir / "trace_manifest.json"),
        "primary_receipt_sha256": sha256_file(receipt_path),
    }
    expected = {
        "status": "PASS",
        "experiment_id": "E006",
        "pair_id": PAIR_ID,
        "phase": "prospective",
        "attempt": "primary",
        "selection_sha256": FROZEN_INPUT_SHA256["selection"],
        "observations_sha256": anchor["primary_observations_sha256"],
        "trace_run_id": anchor["primary_trace_run_id"],
        "trace_manifest_sha256": anchor["primary_trace_manifest_sha256"],
        "call_count": 60,
        "derivation_count": 15,
        "primary_claim_sha256": primary_claim_sha256,
        "repeat_claim_sha256": None,
        "primary_anchor": None,
    }
    mismatches = {
        key: (receipt.get(key), value)
        for key, value in expected.items()
        if receipt.get(key) != value
    }
    if mismatches or receipt.get("errors") != []:
        raise ValueError(f"prospective primary receipt mismatch: {mismatches}")
    return anchor


def _claim_repeat_once(
    primary_anchor: dict[str, str],
    *,
    run_freeze: dict[str, Any],
    primary_claim_sha256: str,
) -> str:
    claim = {
        "schema_version": "e006-prospective-repeat-claim/v1",
        "experiment_id": "E006",
        "pair_id": PAIR_ID,
        "attempt": "repeat",
        "attempt_nonce": str((run_freeze.get("attempt_nonces") or {}).get("repeat") or ""),
        "status": "REPEAT_ATTEMPT_CLAIMED",
        "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
        "primary_claim_sha256": primary_claim_sha256,
        "primary_anchor": primary_anchor,
        "claimed_at": now_iso(),
    }
    with REPEAT_CLAIM_PATH.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(claim, ensure_ascii=False, indent=2) + "\n")
    return sha256_file(REPEAT_CLAIM_PATH)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--attempt", choices=sorted(ATTEMPTS), required=True)
    args = parser.parse_args()
    if args.output_dir.resolve() != EXPECTED_OUTPUT_DIRS[args.attempt].resolve():
        raise ValueError(
            f"E006 {PAIR_ID}/{args.attempt} must use {EXPECTED_OUTPUT_DIRS[args.attempt]}"
        )
    try:
        client = QwenClient()
    except MissingApiKeyError as exc:
        print(f"[error] {exc}")
        return 1
    if client.model != REQUESTED_MODEL:
        raise ValueError(f"E006 freezes qwen-plus, got {client.model!r}")
    if client.base_url.rstrip("/") != OFFICIAL_DASHSCOPE_BASE_URL:
        raise ValueError("E006 requires official DashScope")
    if client.max_retries != CLIENT_MAX_RETRIES or float(
        client.timeout
    ) != CLIENT_TIMEOUT_SECONDS:
        raise ValueError("E006 prospective freezes max_retries=2 and timeout=90s")
    observations_path = args.output_dir / "observations.json"
    trace_dir = (
        args.output_dir
        / "agent_traces"
        / f"e006-prospective-{args.attempt}-{uuid.uuid4()}"
    )
    allowed_read_roots = [
        (REPO_ROOT / "agent").resolve(),
        (REPO_ROOT / "public_dataset_upload" / "questions" / "group_a").resolve(),
        (REPO_ROOT / "processed_data" / "chunks.jsonl").resolve(),
        (REPO_ROOT / "processed_data" / "doc_meta.json").resolve(),
        SOURCE_SELECTION_PATH.resolve(),
        args.selection.resolve(),
        AUTHORIZATION_PATH.resolve(),
        RUN_FREEZE_PATH.resolve(),
        CONTROL_REFERENCE_PATH.resolve(),
        OFFLINE_GATE_PATH.resolve(),
        PRIMARY_CLAIM_PATH.resolve(),
        args.output_dir.resolve(),
    ]
    attempt_claim_path = (
        PRIMARY_CLAIM_PATH if args.attempt == "primary" else REPEAT_CLAIM_PATH
    )
    if args.attempt == "repeat":
        allowed_read_roots.extend(
            [REPEAT_CLAIM_PATH.resolve(), EXPECTED_OUTPUT_DIRS["primary"].resolve()]
        )
    recorder: AgentTraceRecorder | None = None
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    try:
        with blind_data_guard(
            default_candidate_forbidden_roots(),
            allowed_read_roots=allowed_read_roots,
            allowed_write_roots=(
                args.output_dir.resolve(),
                attempt_claim_path.resolve(),
            ),
            block_subprocess=True,
        ):
            selection = _load_selection(args.selection)
            frozen_inputs = _verify_frozen_inputs(args.selection)
            run_freeze, run_freeze_snapshot = _load_and_verify_run_freeze()
            frozen_inputs = {**frozen_inputs, "run_freeze": run_freeze_snapshot}
            _verify_registered_slot_state(attempt=args.attempt)
            qids = list(map(str, selection["qids"]))
            questions = {str(item["qid"]): item for item in load_all_questions()}
            _validate_questions(qids, questions)
            chunks = load_chunks()
            doc_meta = load_doc_meta()
            if not doc_meta:
                raise ValueError("E006 prospective requires deterministic doc_meta")
            if args.attempt == "primary":
                primary_claim_sha256 = _claim_primary_once(run_freeze)
                primary_anchor = None
                repeat_claim_sha256 = None
            else:
                primary_claim_sha256 = _verify_primary_claim(run_freeze)
                primary_anchor = _verified_primary_anchor(
                    run_freeze, primary_claim_sha256
                )
                repeat_claim_sha256 = _claim_repeat_once(
                    primary_anchor,
                    run_freeze=run_freeze,
                    primary_claim_sha256=primary_claim_sha256,
                )
            args.output_dir.mkdir(parents=True, exist_ok=False)
            config = {
                "runner": "agent.run_e006_prospective_arm",
                "experiment_id": "E006",
                "phase": "prospective",
                "pair_id": PAIR_ID,
                "attempt": args.attempt,
                "attempt_nonce": str(
                    (run_freeze.get("attempt_nonces") or {}).get(args.attempt) or ""
                ),
                "primary_claim_sha256": primary_claim_sha256,
                "primary_anchor": primary_anchor,
                "repeat_claim_sha256": repeat_claim_sha256,
                "pipeline_version": E006_PIPELINE_VERSION,
                "online_parent_pipeline_version": "v2s1",
                "retrieval_control_profile": "v0-82041d0",
                "prompt_profile": "v0-82041d0",
                "enable_option_document_route": True,
                "qids": qids,
                "top_k": V0_TOP_K,
                "selection_file": display_path(args.selection),
                "selection_sha256": sha256_file(args.selection),
                "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
                "output_dir": display_path(args.output_dir),
                "labels_accessed": False,
                "per_option_call_count": 1,
                "whole_question_review_calls": 0,
                "temperature": 0.0,
                "client_timeout_seconds": client.timeout,
                "client_max_retries": client.max_retries,
                "v0_retrieve_source_sha256": V0_RETRIEVE_SOURCE_SHA256,
                "v0_prompts_source_sha256": V0_PROMPTS_SOURCE_SHA256,
                "route_thresholds": {
                    "minimum_title_score": ROUTE_MIN_TITLE_SCORE,
                    "minimum_longest_match": ROUTE_MIN_LONGEST_MATCH,
                    "minimum_score_ratio": ROUTE_MIN_SCORE_RATIO,
                    "minimum_score_margin": ROUTE_MIN_SCORE_MARGIN,
                },
                "input_artifacts": frozen_inputs,
            }
            recorder = AgentTraceRecorder(
                trace_dir,
                purpose=f"e006_prospective_{args.attempt}",
                model=client.model,
                base_url=client.base_url,
                config=config,
            )
            client.trace_recorder = recorder
            for qid in qids:
                question = questions[qid]
                diagnostics: dict[str, Any] = {}
                retrieval = retrieve_multi_v0_compatible(
                    question,
                    chunks,
                    enable_option_document_route=True,
                    top_k=V0_TOP_K,
                    doc_meta=doc_meta,
                    diagnostics_out=diagnostics,
                )
                result = reason_multi_with_v0_prompt(
                    question, retrieval, client=client, arm="treatment"
                )
                result["retrieval"] = _compact_retrieval(retrieval)
                result["route_diagnostics"] = diagnostics
                results.append(result)
                recorder.record_derivation(result)
            for result in results:
                failures.extend(
                    {"qid": str(result.get("qid") or ""), "error": error}
                    for error in _validate_result(result, arm="treatment")
                )
            payload = {
                "schema_version": "e006-prospective-observations/v1",
                "experiment_id": "E006",
                "phase": "prospective",
                "pair_id": PAIR_ID,
                "attempt": args.attempt,
                "attempt_nonce": str(
                    (run_freeze.get("attempt_nonces") or {}).get(args.attempt) or ""
                ),
                "primary_claim_sha256": primary_claim_sha256,
                "primary_anchor": primary_anchor,
                "repeat_claim_sha256": repeat_claim_sha256,
                "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
                "pipeline_version": E006_PIPELINE_VERSION,
                "retrieval_control_profile": "v0-82041d0",
                "selection_file": display_path(args.selection),
                "selection_sha256": sha256_file(args.selection),
                "labels_accessed": False,
                "qids": qids,
                "started_from_empty_directory": True,
                "completed_at": now_iso(),
                "question_count": len(results),
                "api_call_count": sum(
                    len(result.get("option_judgments", {})) for result in results
                ),
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
            observations_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            recorder.finalize(output_paths=(observations_path,), failures=failures)
    except Exception as exc:
        if recorder is not None and recorder.manifest.get("status") == "recording":
            recorder.finalize(output_paths=None, failures=[{"qid": "", "error": str(exc)}])
        print(f"[error] {exc}")
        return 1

    trace_report = validate_trace_directory(
        recorder.trace_dir,
        require_candidate_eligible=False,
        require_current_code_match=True,
    )
    trace_report.setdefault("errors", []).extend(
        validate_prospective_trace_contract(
            trace_report,
            trace_dir=recorder.trace_dir,
            attempt=args.attempt,
            output_dir=args.output_dir,
        )
    )
    trace_report["ok"] = not trace_report.get("errors")
    traced_calls = [
        json.loads(line)
        for line in recorder.calls_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    physical_attempt_count = sum(
        len(call.get("attempts") or []) for call in traced_calls
    )
    receipt = {
        "schema_version": "e006-prospective-run-receipt/v1",
        "experiment_id": "E006",
        "phase": "prospective",
        "pair_id": PAIR_ID,
        "attempt": args.attempt,
        "attempt_nonce": str(
            (run_freeze.get("attempt_nonces") or {}).get(args.attempt) or ""
        ),
        "primary_claim_sha256": primary_claim_sha256,
        "primary_anchor": primary_anchor,
        "repeat_claim_sha256": repeat_claim_sha256,
        "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
        "status": "PASS" if trace_report["ok"] and not failures else "FAIL",
        "selection_sha256": sha256_file(args.selection),
        "observations_sha256": sha256_file(observations_path),
        "trace_run_id": recorder.run_id,
        "trace_manifest_sha256": sha256_file(recorder.manifest_path),
        "code_sha256": (trace_report.get("manifest") or {}).get("code", {}).get(
            "sha256"
        ),
        "config_sha256": (trace_report.get("manifest") or {}).get("config_sha256"),
        "model_sha256": (trace_report.get("manifest") or {}).get("model_sha256"),
        "input_artifacts_sha256": sha256_json(frozen_inputs),
        "pipeline_version": E006_PIPELINE_VERSION,
        "call_count": trace_report.get("call_count"),
        "logical_call_count": trace_report.get("call_count"),
        "physical_attempt_count": physical_attempt_count,
        "max_retries_per_logical_call": 2,
        "derivation_count": trace_report.get("derivation_count"),
        "total_tokens": sum(int(result.get("total_tokens") or 0) for result in results),
        "errors": [
            *trace_report.get("errors", []),
            *(failure["error"] for failure in failures),
        ],
        "created_at": now_iso(),
    }
    (args.output_dir / "run_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if receipt["status"] != "PASS":
        for error in receipt["errors"]:
            print(f"[e006-prospective-error] {error}")
        return 1
    print(
        f"E006 prospective {args.attempt}=PASS questions=15 calls=60 "
        f"tokens={receipt['total_tokens']} output={args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
