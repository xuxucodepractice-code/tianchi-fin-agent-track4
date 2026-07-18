"""Run one governed fresh E007R1 development arm without retries."""

from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from agent.doc_meta import load_doc_meta
from agent.load_questions import load_all_questions
from agent.paths import REPO_ROOT
from agent.qwen_client import MissingApiKeyError, QwenClient
from agent.reason_e007_reference_integrity import (
    CONTROL_INSTRUCTION,
    E007_PIPELINE_VERSION,
    PROMPT_PROFILE,
    TREATMENT_INSTRUCTION,
    V0_SYSTEM_PROMPT,
    build_question_result,
    judge_option,
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
    resolve_recorded_path,
    sha256_file,
    sha256_json,
    validate_trace_directory,
)

ARMS = {"control", "treatment"}
PAIR_ID = "e007r1-development-pair-01"
EXPERIMENT_DIR = (
    REPO_ROOT
    / "workspace"
    / "03_baseline_improvement"
    / "experiments"
    / "E007R1_multi_evidence_reference_integrity"
)
SELECTION_PATH = EXPERIMENT_DIR / "development_selection.json"
RUN_FREEZE_PATH = EXPERIMENT_DIR / "development_run_freeze.json"
OUTPUT_ROOT = (
    REPO_ROOT / "outputs" / "experiments" / "E007R1_multi_evidence_reference_integrity"
)
EXPECTED_OUTPUT_DIRS = {
    "control": OUTPUT_ROOT / "development_control_01",
    "treatment": OUTPUT_ROOT / "development_treatment_01",
}
TREATMENT_AUTHORIZATION_PATH = OUTPUT_ROOT / "development_treatment_authorization.json"
TREATMENT_CLAIM_PATH = OUTPUT_ROOT / "development_treatment_claim.json"
RUNNER_PATH = REPO_ROOT / "agent" / "run_e007_development_arm.py"
REASON_PATH = REPO_ROOT / "agent" / "reason_e007_reference_integrity.py"
EVALUATOR_PATH = REPO_ROOT / "agent" / "evaluate_e007_development.py"
REQUESTED_MODEL = "qwen-plus"
CLIENT_TIMEOUT_SECONDS = 90.0
CLIENT_MAX_RETRIES = 0
TLS_CA_BUNDLE_PATH = Path("/etc/ssl/cert.pem")
TLS_CA_BUNDLE_SHA256 = "9dae8d76e55cb08991f2b672d58999ea15560d910759c16b544f843bdffbb994"

DEVELOPMENT_QIDS = (
    "fc_a_016",
    "fin_a_005",
    "ins_a_005",
    "ins_a_007",
    "ins_a_009",
    "ins_a_010",
    "ins_a_015",
    "ins_a_016",
    "ins_a_017",
    "ins_a_019",
    "res_a_014",
    "fc_a_001",
    "reg_a_002",
)
FROZEN_INPUT_SHA256 = {
    "questions": "c33dde8ac97d8a00ef3796f4312274cea74fce699f52b15c006c45fab80c0676",
    "chunks": "02aa2f9b33f304a4d9a74789acc5aa47ec9efff42d7a68bdd2390e7cea30a878",
    "doc_meta": "df9af050cce73707536d2798f62b1e4640747d4cfe595b2e12cddd22d6d472d7",
    "selection": "702a88a95aee2a51f8acf8e30b7c2dbdbb9ff7d85456f15e7d96a8bd3225dfea",
    "tls_ca_bundle": TLS_CA_BUNDLE_SHA256,
    "e006_control_reference": "db90509ba127f662b333e07664e79ff7ce0264db9f1b3cbb34cca177d10d4572",
    "e006_offline_gate": "6c7ec2a4ff7b9efefe8923bb8c5a8d18e0e7f8f69e63b1b8eba2c8cb50a9b7b0",
}
E006_CONTROL_REFERENCE_PATH = (
    REPO_ROOT
    / "workspace/03_baseline_improvement/experiments/E006_multi_retrieval_coverage/control_reference.json"
)
E006_OFFLINE_GATE_PATH = (
    REPO_ROOT
    / "workspace/03_baseline_improvement/experiments/E006_multi_retrieval_coverage/offline_retrieval_gate.json"
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _load_selection(path: Path) -> dict[str, Any]:
    if path.resolve() != SELECTION_PATH.resolve():
        raise ValueError("E007R1 development must use the registered selection path")
    if sha256_file(path) != FROZEN_INPUT_SHA256["selection"]:
        raise ValueError("E007R1 development selection SHA256 mismatch")
    payload = _load_json(path)
    if (
        payload.get("schema_version") != "e007r1-development-selection/v1"
        or payload.get("experiment_id") != "E007R1"
        or payload.get("role") != "retrospective_development_only"
        or payload.get("labels_known_before_code_freeze") is not True
        or tuple(map(str, payload.get("qids") or [])) != DEVELOPMENT_QIDS
    ):
        raise ValueError("E007R1 development selection semantics mismatch")
    return payload


def _verify_frozen_inputs(selection_path: Path) -> dict[str, dict[str, Any]]:
    paths = {
        "questions": REPO_ROOT / "public_dataset_upload/questions/group_a",
        "chunks": REPO_ROOT / "processed_data/chunks.jsonl",
        "doc_meta": REPO_ROOT / "processed_data/doc_meta.json",
        "selection": selection_path,
        "tls_ca_bundle": TLS_CA_BUNDLE_PATH,
        "e006_control_reference": E006_CONTROL_REFERENCE_PATH,
        "e006_offline_gate": E006_OFFLINE_GATE_PATH,
    }
    snapshots = {name: input_artifact_snapshot(path) for name, path in paths.items()}
    mismatch = {
        name: (item.get("sha256"), FROZEN_INPUT_SHA256[name])
        for name, item in snapshots.items()
        if item.get("sha256") != FROZEN_INPUT_SHA256[name]
    }
    if mismatch:
        raise ValueError(f"E007R1 frozen input SHA256 mismatch: {mismatch}")
    offline = _load_json(E006_OFFLINE_GATE_PATH)
    if offline.get("status") != "PASS" or offline.get("lost_required_chunks") != []:
        raise ValueError("E006 treatment retrieval gate is not frozen PASS")
    return snapshots


def validate_run_freeze_payload(
    payload: dict[str, Any], *, current_code_snapshot: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    expected_files = {
        "runner": {"path": display_path(RUNNER_PATH), "sha256": sha256_file(RUNNER_PATH)},
        "reasoner": {"path": display_path(REASON_PATH), "sha256": sha256_file(REASON_PATH)},
        "evaluator": {
            "path": display_path(EVALUATOR_PATH),
            "sha256": sha256_file(EVALUATOR_PATH),
        },
    }
    if payload.get("schema_version") != "e007r1-development-run-freeze/v1":
        errors.append("run-freeze schema mismatch")
    if (
        payload.get("experiment_id") != "E007R1"
        or payload.get("pair_id") != PAIR_ID
        or payload.get("phase") != "development"
        or payload.get("status") != "AUTHORIZED_TO_RUN_DEVELOPMENT_PAIR"
    ):
        errors.append("run-freeze identity/status mismatch")
    if re.fullmatch(r"[0-9a-f]{40}", str(payload.get("source_code_commit") or "")) is None:
        errors.append("run-freeze source commit is invalid")
    if payload.get("agent_code_snapshot_sha256") != current_code_snapshot.get("sha256"):
        errors.append("agent code snapshot differs from freeze")
    if payload.get("code_files") != expected_files:
        errors.append("runner/reasoner/evaluator hashes differ from freeze")
    if tuple(map(str, payload.get("qids") or [])) != DEVELOPMENT_QIDS:
        errors.append("run-freeze qids/order mismatch")
    if payload.get("frozen_input_sha256") != FROZEN_INPUT_SHA256:
        errors.append("run-freeze input hashes mismatch")
    if payload.get("registered_outputs") != {
        "control": display_path(EXPECTED_OUTPUT_DIRS["control"]),
        "treatment": display_path(EXPECTED_OUTPUT_DIRS["treatment"]),
        "treatment_authorization": display_path(TREATMENT_AUTHORIZATION_PATH),
        "treatment_claim": display_path(TREATMENT_CLAIM_PATH),
    }:
        errors.append("run-freeze output slots mismatch")
    expected_prompt_hash = sha256_json(
        {
            "system": V0_SYSTEM_PROMPT,
            "control_instruction": CONTROL_INSTRUCTION,
            "treatment_instruction": TREATMENT_INSTRUCTION,
        }
    )
    if payload.get("prompt_bundle_sha256") != expected_prompt_hash:
        errors.append("prompt bundle differs from freeze")
    if payload.get("pipeline") != {
        "pipeline_version": E007_PIPELINE_VERSION,
        "retrieval_parent": "E006-treatment",
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
    }:
        errors.append("pipeline freeze mismatch")
    if payload.get("model") != {
        "provider": "dashscope-openai-compatible",
        "requested_model": REQUESTED_MODEL,
        "base_url": OFFICIAL_DASHSCOPE_BASE_URL,
        "temperature": 0.0,
        "timeout_seconds": CLIENT_TIMEOUT_SECONDS,
        "max_retries": CLIENT_MAX_RETRIES,
    }:
        errors.append("model/client freeze mismatch")
    if payload.get("transport") != {
        "ssl_cert_file": str(TLS_CA_BUNDLE_PATH),
        "ssl_cert_file_sha256": TLS_CA_BUNDLE_SHA256,
        "pre_freeze_probe": {
            "api_key_used": False,
            "endpoint": f"{OFFICIAL_DASHSCOPE_BASE_URL}/chat/completions",
            "expected_http_status": 400,
            "observed_http_status": 400,
        },
    }:
        errors.append("TLS transport freeze mismatch")
    if payload.get("call_topology") != {
        "question_count_per_arm": 13,
        "logical_calls_per_arm": 52,
        "physical_attempts_per_arm": 52,
        "derivations_per_arm": 13,
    }:
        errors.append("call topology freeze mismatch")
    if payload.get("initial_state") != {
        "control_output_exists": False,
        "treatment_output_exists": False,
        "treatment_authorization_exists": False,
        "treatment_claim_exists": False,
    }:
        errors.append("initial state freeze mismatch")
    return errors


def _load_run_freeze() -> tuple[dict[str, Any], dict[str, Any]]:
    payload = _load_json(RUN_FREEZE_PATH)
    errors = validate_run_freeze_payload(payload, current_code_snapshot=code_snapshot())
    if errors:
        raise ValueError(f"E007R1 development run-freeze invalid: {errors}")
    return payload, input_artifact_snapshot(RUN_FREEZE_PATH)


def _validate_questions(qids: list[str], questions: dict[str, dict[str, Any]]) -> None:
    invalid = [
        qid
        for qid in qids
        if qid not in questions
        or questions[qid].get("answer_format") != "multi"
        or sorted(questions[qid].get("options", {})) != list("ABCD")
        or not questions[qid].get("doc_ids")
    ]
    if invalid:
        raise ValueError(f"E007R1 requires governed A/B/C/D Multi questions: {invalid}")


def _compact_retrieval(retrieval: dict[str, Any]) -> dict[str, Any]:
    return {
        key: {"option_text": item["option_text"], "evidence": item["evidence"]}
        for key, item in retrieval["options"].items()
    }


def _control_anchor() -> dict[str, str]:
    control_dir = EXPECTED_OUTPUT_DIRS["control"]
    observations_path = control_dir / "observations.json"
    receipt_path = control_dir / "run_receipt.json"
    for path in (observations_path, receipt_path, TREATMENT_AUTHORIZATION_PATH):
        if not path.is_file():
            raise ValueError(f"E007R1 treatment requires completed control artifact: {path}")
    observations = _load_json(observations_path)
    receipt = _load_json(receipt_path)
    trace_dir = resolve_recorded_path(
        str((observations.get("agent_trace") or {}).get("trace_dir") or "")
    )
    report = validate_trace_directory(
        trace_dir, require_candidate_eligible=False, require_current_code_match=True
    )
    if not report.get("ok") or receipt.get("status") != "PASS":
        raise ValueError("E007R1 registered control no longer passes Trace/receipt validation")
    anchor = {
        "pair_id": PAIR_ID,
        "control_trace_run_id": str(
            (observations.get("agent_trace") or {}).get("trace_run_id") or ""
        ),
        "control_observations_sha256": sha256_file(observations_path),
        "control_trace_manifest_sha256": sha256_file(trace_dir / "trace_manifest.json"),
        "control_receipt_sha256": sha256_file(receipt_path),
    }
    authorization = _load_json(TREATMENT_AUTHORIZATION_PATH)
    if (
        authorization.get("schema_version") != "e007r1-treatment-authorization/v1"
        or authorization.get("status") != "AUTHORIZED_FOR_ONE_TREATMENT_ATTEMPT"
        or authorization.get("control_anchor") != anchor
    ):
        raise ValueError("E007R1 treatment authorization does not bind current control")
    return anchor


def _claim_treatment(control_anchor: dict[str, str]) -> str:
    claim = {
        "schema_version": "e007r1-treatment-claim/v1",
        "experiment_id": "E007R1",
        "pair_id": PAIR_ID,
        "status": "TREATMENT_ATTEMPT_CLAIMED",
        "control_anchor": control_anchor,
        "authorization_sha256": sha256_file(TREATMENT_AUTHORIZATION_PATH),
        "claimed_at": now_iso(),
    }
    TREATMENT_CLAIM_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TREATMENT_CLAIM_PATH.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(claim, ensure_ascii=False, indent=2) + "\n")
    return sha256_file(TREATMENT_CLAIM_PATH)


def _write_treatment_authorization(anchor: dict[str, str]) -> None:
    payload = {
        "schema_version": "e007r1-treatment-authorization/v1",
        "experiment_id": "E007R1",
        "pair_id": PAIR_ID,
        "status": "AUTHORIZED_FOR_ONE_TREATMENT_ATTEMPT",
        "control_anchor": anchor,
        "created_at": now_iso(),
    }
    with TREATMENT_AUTHORIZATION_PATH.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _trace_contract_errors(
    trace_report: dict[str, Any], *, trace_dir: Path, arm: str, completed: bool
) -> list[str]:
    errors: list[str] = []
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
    if completed and (len(calls) != 52 or len(derivations) != 13):
        errors.append("completed E007R1 arm must have 52 calls and 13 derivations")
    for call in calls:
        context = call.get("context") or {}
        qid = str(context.get("qid") or "")
        option = str(context.get("option_key") or "")
        if qid not in DEVELOPMENT_QIDS or option not in "ABCD":
            errors.append("call has unknown qid/option")
        if context.get("stage") != f"e007r1_{arm}_option_judgment":
            errors.append(f"{qid}:{option}: stage mismatch")
        if context.get("prompt_profile") != PROMPT_PROFILE:
            errors.append(f"{qid}:{option}: prompt profile mismatch")
        if call.get("tool_calls") != [] or call.get("finish_reason") != "stop":
            errors.append(f"{qid}:{option}: tool/finish contract failed")
        if not str(call.get("response_model") or "").startswith("qwen-plus"):
            errors.append(f"{qid}:{option}: served model is not qwen-plus")
        request = call.get("request_payload") or {}
        if request.get("model") != REQUESTED_MODEL or float(request.get("temperature", -1)) != 0:
            errors.append(f"{qid}:{option}: request model/temperature mismatch")
        attempts = call.get("attempts") or []
        if len(attempts) != 1 or int(call.get("retry_count") or 0) != 0:
            errors.append(f"{qid}:{option}: retry/physical attempt contract failed")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--arm", choices=sorted(ARMS), required=True)
    args = parser.parse_args()

    if args.output_dir.exists():
        raise ValueError(f"output directory must be absent: {args.output_dir}")
    if args.output_dir.resolve() != EXPECTED_OUTPUT_DIRS[args.arm].resolve():
        raise ValueError(f"E007R1 arm must use registered output slot: {EXPECTED_OUTPUT_DIRS[args.arm]}")
    selection = _load_selection(args.selection)
    frozen_inputs = _verify_frozen_inputs(args.selection)
    run_freeze, run_freeze_snapshot = _load_run_freeze()
    control_anchor = _control_anchor() if args.arm == "treatment" else None
    questions = {str(item["qid"]): item for item in load_all_questions()}
    qids = list(map(str, selection["qids"]))
    _validate_questions(qids, questions)
    chunks = load_chunks()
    doc_meta = load_doc_meta()
    if not doc_meta:
        raise ValueError("E007R1 freezes E006 treatment and requires doc_meta")
    if os.environ.get("SSL_CERT_FILE") != str(TLS_CA_BUNDLE_PATH):
        raise ValueError("E007R1 requires SSL_CERT_FILE=/etc/ssl/cert.pem")
    if sha256_file(TLS_CA_BUNDLE_PATH) != TLS_CA_BUNDLE_SHA256:
        raise ValueError("E007R1 TLS CA bundle SHA256 mismatch")
    try:
        client = QwenClient(
            model=REQUESTED_MODEL,
            timeout=CLIENT_TIMEOUT_SECONDS,
            max_retries=CLIENT_MAX_RETRIES,
        )
    except MissingApiKeyError as exc:
        print(f"[error] {exc}")
        return 1
    if client.model != REQUESTED_MODEL or client.max_retries != 0:
        raise ValueError("E007R1 model/retry configuration drift")
    if client.base_url.rstrip("/") != OFFICIAL_DASHSCOPE_BASE_URL:
        raise ValueError("E007R1 requires the official DashScope endpoint")

    treatment_claim_sha256 = (
        _claim_treatment(control_anchor) if args.arm == "treatment" else None
    )
    args.output_dir.mkdir(parents=True, exist_ok=False)
    observations_path = args.output_dir / "observations.json"
    trace_dir = args.output_dir / "agent_traces" / f"e007r1-{args.arm}-{uuid.uuid4()}"
    allowed_read_roots = (
        (REPO_ROOT / "agent").resolve(),
        (REPO_ROOT / "public_dataset_upload/questions/group_a").resolve(),
        (REPO_ROOT / "processed_data/chunks.jsonl").resolve(),
        (REPO_ROOT / "processed_data/doc_meta.json").resolve(),
        args.selection.resolve(),
        RUN_FREEZE_PATH.resolve(),
        E006_CONTROL_REFERENCE_PATH.resolve(),
        E006_OFFLINE_GATE_PATH.resolve(),
        TLS_CA_BUNDLE_PATH.resolve(),
        args.output_dir.resolve(),
        *((EXPECTED_OUTPUT_DIRS["control"].resolve(), TREATMENT_AUTHORIZATION_PATH.resolve(), TREATMENT_CLAIM_PATH.resolve()) if args.arm == "treatment" else ()),
    )
    recorder: AgentTraceRecorder | None = None
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    partial_failure: dict[str, Any] | None = None
    try:
        with blind_data_guard(
            default_candidate_forbidden_roots(),
            allowed_read_roots=allowed_read_roots,
            allowed_write_roots=(args.output_dir.resolve(),),
            block_subprocess=True,
        ):
            recorder = AgentTraceRecorder(
                trace_dir,
                purpose=f"e007r1_development_{args.arm}",
                model=client.model,
                base_url=client.base_url,
                config={
                    "runner": "agent.run_e007_development_arm",
                    "experiment_id": "E007R1",
                    "pair_id": PAIR_ID,
                    "phase": "development",
                    "arm": args.arm,
                    "control_anchor": control_anchor,
                    "treatment_claim_sha256": treatment_claim_sha256,
                    "pipeline_version": E007_PIPELINE_VERSION,
                    "retrieval_parent": "E006-treatment",
                    "enable_option_document_route": True,
                    "reference_profile": (
                        "numeric_evidence_refs" if args.arm == "control" else "opaque_ev_refs"
                    ),
                    "qids": qids,
                    "top_k": V0_TOP_K,
                    "selection_file": display_path(args.selection),
                    "selection_sha256": sha256_file(args.selection),
                    "run_freeze": run_freeze_snapshot,
                    "output_dir": display_path(args.output_dir),
                    "temperature": 0.0,
                    "client_timeout_seconds": client.timeout,
                    "client_max_retries": client.max_retries,
                    "ssl_cert_file": str(TLS_CA_BUNDLE_PATH),
                    "ssl_cert_file_sha256": TLS_CA_BUNDLE_SHA256,
                    "route_thresholds": run_freeze["pipeline"]["route_thresholds"],
                    "input_artifacts": frozen_inputs,
                },
            )
            client.trace_recorder = recorder
            aborted = False
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
                compact = _compact_retrieval(retrieval)
                judgments: dict[str, dict[str, Any]] = {}
                for option_key in "ABCD":
                    option = retrieval["options"][option_key]
                    judgment = judge_option(
                        client,
                        question,
                        option_key,
                        option["option_text"],
                        option["evidence"],
                        arm=args.arm,
                    )
                    judgments[option_key] = judgment
                    if judgment.get("error"):
                        failures.append(
                            {"qid": qid, "error": f"{option_key}: {judgment['error']}"}
                        )
                        partial_failure = {
                            "qid": qid,
                            "option_judgments": judgments,
                            "retrieval": compact,
                            "route_diagnostics": diagnostics,
                        }
                        aborted = True
                        break
                if aborted:
                    break
                result = build_question_result(question, judgments, arm=args.arm)
                result["retrieval"] = compact
                result["route_diagnostics"] = diagnostics
                results.append(result)
                recorder.record_derivation(result)

            payload = {
                "schema_version": "e007r1-development-observations/v1",
                "experiment_id": "E007R1",
                "pair_id": PAIR_ID,
                "phase": "development",
                "arm": args.arm,
                "control_anchor": control_anchor,
                "treatment_claim_sha256": treatment_claim_sha256,
                "pipeline_version": E007_PIPELINE_VERSION,
                "retrieval_parent": "E006-treatment",
                "reference_profile": (
                    "numeric_evidence_refs" if args.arm == "control" else "opaque_ev_refs"
                ),
                "selection_file": display_path(args.selection),
                "selection_sha256": sha256_file(args.selection),
                "qids": qids,
                "started_from_empty_directory": True,
                "completed_at": now_iso(),
                "question_count": len(results),
                "api_call_count": sum(
                    len(result["option_judgments"]) for result in results
                ) + (len((partial_failure or {}).get("option_judgments") or {})),
                "physical_attempt_count": 0,
                "total_tokens": sum(int(result.get("total_tokens") or 0) for result in results)
                + sum(
                    int(item.get("total_tokens") or 0)
                    for item in ((partial_failure or {}).get("option_judgments") or {}).values()
                ),
                "failures": failures,
                "partial_failure": partial_failure,
                "observations": results,
                "agent_trace": {
                    "schema_version": "agent-trace/v1",
                    "trace_run_id": recorder.run_id,
                    "trace_dir": display_path(recorder.trace_dir),
                    "candidate_eligible": False,
                },
            }
            calls = [
                json.loads(line)
                for line in recorder.calls_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            payload["physical_attempt_count"] = sum(
                len(call.get("attempts") or []) for call in calls
            )
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
    completed = not failures and len(results) == 13
    trace_errors = _trace_contract_errors(
        trace_report, trace_dir=recorder.trace_dir, arm=args.arm, completed=completed
    )
    all_errors = [*trace_report.get("errors", []), *trace_errors, *(x["error"] for x in failures)]
    calls = [
        json.loads(line)
        for line in recorder.calls_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    served_models = sorted(
        {str(call.get("response_model") or "") for call in calls if call.get("response_model")}
    )
    receipt = {
        "schema_version": "e007r1-development-run-receipt/v1",
        "experiment_id": "E007R1",
        "pair_id": PAIR_ID,
        "phase": "development",
        "arm": args.arm,
        "status": "PASS" if completed and not all_errors else "FAIL",
        "control_anchor": control_anchor,
        "treatment_claim_sha256": treatment_claim_sha256,
        "selection_sha256": sha256_file(args.selection),
        "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
        "observations_sha256": sha256_file(observations_path),
        "trace_run_id": recorder.run_id,
        "trace_manifest_sha256": sha256_file(recorder.manifest_path),
        "code_sha256": (trace_report.get("manifest") or {}).get("code", {}).get("sha256"),
        "config_sha256": (trace_report.get("manifest") or {}).get("config_sha256"),
        "model_sha256": (trace_report.get("manifest") or {}).get("model_sha256"),
        "input_artifacts_sha256": sha256_json(frozen_inputs),
        "pipeline_version": E007_PIPELINE_VERSION,
        "call_count": len(calls),
        "physical_attempt_count": sum(len(call.get("attempts") or []) for call in calls),
        "derivation_count": len(results),
        "total_tokens": sum(
            int((call.get("usage") or {}).get("total_tokens") or 0) for call in calls
        ),
        "served_models": served_models,
        "errors": all_errors,
        "created_at": now_iso(),
    }
    receipt_path = args.output_dir / "run_receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if receipt["status"] != "PASS":
        for error in receipt["errors"]:
            print(f"[e007r1-error] {error}")
        return 1
    if args.arm == "control":
        anchor = {
            "pair_id": PAIR_ID,
            "control_trace_run_id": recorder.run_id,
            "control_observations_sha256": sha256_file(observations_path),
            "control_trace_manifest_sha256": sha256_file(recorder.manifest_path),
            "control_receipt_sha256": sha256_file(receipt_path),
        }
        _write_treatment_authorization(anchor)
    print(
        f"E007R1 development/{args.arm}=PASS questions=13 calls=52 "
        f"physical=52 tokens={receipt['total_tokens']} served={served_models}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
