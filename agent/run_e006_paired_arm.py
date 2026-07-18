"""Run one fresh traced arm of the governed E006 paired Multi pilot."""

from __future__ import annotations

import argparse
import json
import uuid
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
from agent.trace_gate import (
    AgentTraceRecorder,
    OFFICIAL_DASHSCOPE_BASE_URL,
    blind_data_guard,
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
PHASES = {"development"}
EXPERIMENT_DIR = (
    REPO_ROOT
    / "workspace"
    / "03_baseline_improvement"
    / "experiments"
    / "E006_multi_retrieval_coverage"
)
DEVELOPMENT_SELECTION_PATH = EXPERIMENT_DIR / "development_selection.json"
CONTROL_REFERENCE_PATH = EXPERIMENT_DIR / "control_reference.json"
OFFLINE_GATE_PATH = EXPERIMENT_DIR / "offline_retrieval_gate.json"
GOVERNED_OUTPUT_ROOT = (
    REPO_ROOT / "outputs" / "experiments" / "E006_multi_retrieval_coverage"
)
PAIR_ID = "e006-development-pair-01"
EXPECTED_OUTPUT_DIRS = {
    "control": GOVERNED_OUTPUT_ROOT / "development_control_01",
    "treatment": GOVERNED_OUTPUT_ROOT / "development_treatment_01",
}
TREATMENT_CLAIM_PATH = EXPECTED_OUTPUT_DIRS["control"] / "treatment_claim.json"

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
    "selection": "f09cb3fc1cdc4e32c771781d9e09a0a2b4e88a4997925961f35515a1c9d7159f",
    "control_reference": "db90509ba127f662b333e07664e79ff7ce0264db9f1b3cbb34cca177d10d4572",
    "offline_gate": "6c7ec2a4ff7b9efefe8923bb8c5a8d18e0e7f8f69e63b1b8eba2c8cb50a9b7b0",
}
EXPECTED_CONTROL_RETRIEVAL_SHA256 = (
    "274652fc800589a61eb964717f75ec5e16cd8f248f8382f0dea08ba4abff1740"
)


def _load_selection(path: Path, *, phase: str, arm: str) -> dict[str, Any]:
    if phase != "development":
        raise ValueError(
            "E006 primary/repeat are sealed until a development PASS authorizes a new runner"
        )
    if arm not in ARMS:
        raise ValueError(f"unknown E006 arm: {arm!r}")
    if path.resolve() != DEVELOPMENT_SELECTION_PATH.resolve():
        raise ValueError("development run must use the governed selection path")
    if sha256_file(path) != FROZEN_INPUT_SHA256["selection"]:
        raise ValueError("development selection SHA256 mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("development selection must be a JSON object")
    qids = list(map(str, payload.get("qids") or []))
    if tuple(qids) != DEVELOPMENT_QIDS:
        raise ValueError("development selection qids/order differ from the frozen 13")
    if payload.get("schema_version") != "e006-development-selection/v1":
        raise ValueError("development selection schema mismatch")
    if payload.get("experiment_id") != "E006":
        raise ValueError("development selection experiment mismatch")
    if payload.get("role") != "retrospective_development_only":
        raise ValueError("development selection role mismatch")
    if payload.get("labels_known_before_code_freeze") is not True:
        raise ValueError("development selection must declare known labels")
    payload["qids"] = qids
    return payload


def _verify_frozen_inputs(selection_path: Path) -> dict[str, dict[str, Any]]:
    """Fail before API setup if any governed E006 input changed."""
    paths = {
        "questions": REPO_ROOT / "public_dataset_upload" / "questions" / "group_a",
        "chunks": REPO_ROOT / "processed_data" / "chunks.jsonl",
        "doc_meta": REPO_ROOT / "processed_data" / "doc_meta.json",
        "selection": selection_path,
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
        raise ValueError(f"E006 frozen input SHA256 mismatch: {mismatches}")

    control_reference = json.loads(CONTROL_REFERENCE_PATH.read_text(encoding="utf-8"))
    if (
        control_reference.get("canonical_multi_retrieval_sha256")
        != EXPECTED_CONTROL_RETRIEVAL_SHA256
        or int(control_reference.get("multi_question_count") or 0) != 65
        or int(control_reference.get("option_pack_count") or 0) != 260
    ):
        raise ValueError("E006 control reference semantics mismatch")

    offline_gate = json.loads(OFFLINE_GATE_PATH.read_text(encoding="utf-8"))
    recall = offline_gate.get("canonical_recall") or {}
    reproduction = offline_gate.get("control_reproduction") or {}
    checks = offline_gate.get("checks") or {}
    if (
        offline_gate.get("status") != "PASS"
        or not checks
        or not all(value is True for value in checks.values())
        or reproduction.get("computed_canonical_sha256")
        != EXPECTED_CONTROL_RETRIEVAL_SHA256
        or reproduction.get("exact_match") is not True
        or int(recall.get("control_hits") or 0) != 30
        or int(recall.get("treatment_hits") or 0) != 34
        or int(recall.get("delta") or 0) != 4
        or offline_gate.get("lost_required_chunks") != []
    ):
        raise ValueError("E006 offline retrieval gate semantics mismatch")
    return snapshots


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _verified_control_anchor() -> dict[str, str]:
    """Require one completed, strict control before a treatment can start."""
    control_dir = EXPECTED_OUTPUT_DIRS["control"]
    observations_path = control_dir / "observations.json"
    receipt_path = control_dir / "run_receipt.json"
    if not observations_path.is_file() or not receipt_path.is_file():
        raise ValueError("E006 treatment requires the registered control run first")
    observations = _load_json_object(observations_path)
    receipt = _load_json_object(receipt_path)
    trace_dir = resolve_recorded_path(
        str((observations.get("agent_trace") or {}).get("trace_dir") or "")
    )
    trace_report = validate_trace_directory(
        trace_dir,
        require_candidate_eligible=False,
        require_current_code_match=True,
    )
    strict_errors = validate_e006_trace_contract(
        trace_report,
        trace_dir=trace_dir,
        arm="control",
        output_dir=control_dir,
    )
    if not trace_report.get("ok") or strict_errors:
        raise ValueError(
            "registered E006 control failed strict revalidation: "
            f"{[*trace_report.get('errors', []), *strict_errors]}"
        )
    manifest_path = trace_dir / "trace_manifest.json"
    anchor = {
        "pair_id": PAIR_ID,
        "control_trace_run_id": str(
            (observations.get("agent_trace") or {}).get("trace_run_id") or ""
        ),
        "control_observations_sha256": sha256_file(observations_path),
        "control_trace_manifest_sha256": sha256_file(manifest_path),
        "control_receipt_sha256": sha256_file(receipt_path),
    }
    required_receipt = {
        "status": "PASS",
        "experiment_id": "E006",
        "pair_id": PAIR_ID,
        "phase": "development",
        "arm": "control",
        "selection_sha256": FROZEN_INPUT_SHA256["selection"],
        "observations_sha256": anchor["control_observations_sha256"],
        "trace_run_id": anchor["control_trace_run_id"],
        "trace_manifest_sha256": anchor["control_trace_manifest_sha256"],
        "call_count": 52,
        "derivation_count": 13,
    }
    mismatches = {
        key: (receipt.get(key), value)
        for key, value in required_receipt.items()
        if receipt.get(key) != value
    }
    if mismatches or receipt.get("errors") != []:
        raise ValueError(f"registered E006 control receipt mismatch: {mismatches}")
    return anchor


def _claim_treatment_once(control_anchor: dict[str, str]) -> tuple[dict[str, Any], str]:
    """Atomically consume the only treatment attempt attached to this control."""
    claim = {
        "schema_version": "e006-treatment-claim/v1",
        "experiment_id": "E006",
        "pair_id": PAIR_ID,
        "status": "TREATMENT_ATTEMPT_CLAIMED",
        "control_anchor": control_anchor,
        "claimed_at": now_iso(),
    }
    TREATMENT_CLAIM_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TREATMENT_CLAIM_PATH.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(claim, ensure_ascii=False, indent=2) + "\n")
    return claim, sha256_file(TREATMENT_CLAIM_PATH)


def _validate_questions(qids: list[str], questions: dict[str, dict[str, Any]]) -> None:
    missing = [qid for qid in qids if qid not in questions]
    if missing:
        raise ValueError(f"unknown qids: {missing}")
    invalid = [
        qid
        for qid in qids
        if questions[qid].get("answer_format") != "multi"
        or sorted(questions[qid].get("options", {})) != list("ABCD")
        or not questions[qid].get("doc_ids")
    ]
    if invalid:
        raise ValueError(f"E006 requires A/B/C/D Multi questions with doc_ids: {invalid}")


def _compact_retrieval(retrieval: dict[str, Any]) -> dict[str, Any]:
    return {
        key: {"option_text": item["option_text"], "evidence": item["evidence"]}
        for key, item in retrieval["options"].items()
    }


def _validate_result(result: dict[str, Any], *, arm: str) -> list[str]:
    errors: list[str] = []
    qid = str(result.get("qid") or "")
    if result.get("pipeline_version") != E006_PIPELINE_VERSION:
        errors.append(f"{qid}: pipeline identity mismatch")
    if result.get("experiment_arm") != arm:
        errors.append(f"{qid}: arm identity mismatch")
    judgments = result.get("option_judgments") or {}
    if sorted(judgments) != list("ABCD"):
        errors.append(f"{qid}: judgments are not exactly A/B/C/D")
    for option_key, judgment in sorted(judgments.items()):
        if judgment.get("error"):
            errors.append(f"{qid}:{option_key}: {judgment['error']}")
        if not judgment.get("trace_call_id"):
            errors.append(f"{qid}:{option_key}: missing trace_call_id")
    retrieval = result.get("retrieval") or {}
    diagnostics_root = result.get("route_diagnostics") or {}
    diagnostics = diagnostics_root.get("options") or {}
    if sorted(retrieval) != list("ABCD"):
        errors.append(f"{qid}: retrieval is not exactly A/B/C/D")
    if sorted(diagnostics) != list("ABCD"):
        errors.append(f"{qid}: diagnostics are not exactly A/B/C/D")
    if diagnostics_root.get("enabled") is not (arm == "treatment"):
        errors.append(f"{qid}: route enabled flag differs from arm")
    for option_key in "ABCD":
        evidence = (retrieval.get(option_key) or {}).get("evidence") or []
        if len(evidence) != V0_TOP_K:
            errors.append(f"{qid}:{option_key}: evidence count {len(evidence)} != {V0_TOP_K}")
        item = diagnostics.get(option_key) or {}
        selected = list(map(str, item.get("selected_chunk_ids") or []))
        control = list(map(str, item.get("control_chunk_ids") or []))
        evidence_chunk_ids = [str(row.get("chunk_id") or "") for row in evidence]
        if selected != evidence_chunk_ids:
            errors.append(f"{qid}:{option_key}: selected ids differ from rendered evidence")
        decision = item.get("decision")
        if arm == "control":
            if decision != "fallback" or item.get("reason") != "route_disabled_control":
                errors.append(f"{qid}:{option_key}: invalid control route decision")
            if selected != control:
                errors.append(f"{qid}:{option_key}: control selection changed")
            if item.get("target_doc_id") is not None:
                errors.append(f"{qid}:{option_key}: control unexpectedly has a target doc")
        elif decision == "fallback":
            if selected != control:
                errors.append(f"{qid}:{option_key}: fallback is not byte-stable")
        elif decision == "route":
            target = str(item.get("target_doc_id"))
            if not target or target == "None":
                errors.append(f"{qid}:{option_key}: routed option lacks target doc")
            if any(str(row.get("doc_id")) != target for row in evidence):
                errors.append(f"{qid}:{option_key}: routed evidence escaped target doc")
        else:
            errors.append(f"{qid}:{option_key}: unknown route decision {decision!r}")
    return errors


def validate_e006_trace_contract(
    trace_report: dict[str, Any],
    *,
    trace_dir: Path,
    arm: str,
    output_dir: Path,
) -> list[str]:
    """Apply the strict E006 checks omitted by candidate-only validation."""
    errors: list[str] = []
    manifest = trace_report.get("manifest") or {}
    config = manifest.get("config") or {}
    model = manifest.get("model") or {}
    guard = manifest.get("blind_data_guard") or {}
    expected_read_roots = {
        display_path(path)
        for path in (
            (REPO_ROOT / "agent").resolve(),
            (REPO_ROOT / "public_dataset_upload" / "questions" / "group_a").resolve(),
            (REPO_ROOT / "processed_data" / "chunks.jsonl").resolve(),
            (REPO_ROOT / "processed_data" / "doc_meta.json").resolve(),
            DEVELOPMENT_SELECTION_PATH.resolve(),
            CONTROL_REFERENCE_PATH.resolve(),
            OFFLINE_GATE_PATH.resolve(),
            output_dir.resolve(),
            *default_runtime_read_roots(),
        )
    }
    expected_forbidden = {
        display_path(path) for path in default_candidate_forbidden_roots()
    }
    if model != {
        "provider": "dashscope-openai-compatible",
        "model": "qwen-plus",
        "base_url": OFFICIAL_DASHSCOPE_BASE_URL,
    }:
        errors.append("E006 trace model/provider identity mismatch")
    if guard.get("enforced") is not True or guard.get("subprocess_blocked") is not True:
        errors.append("E006 blind-data guard was not fully enforced")
    if set(map(str, guard.get("forbidden_roots") or [])) != expected_forbidden:
        errors.append("E006 forbidden-root policy mismatch")
    if set(map(str, guard.get("allowed_read_roots") or [])) != expected_read_roots:
        errors.append("E006 read allowlist mismatch")
    if set(map(str, guard.get("allowed_write_roots") or [])) != {
        display_path(output_dir.resolve())
    }:
        errors.append("E006 write allowlist mismatch")
    if config.get("runner") != "agent.run_e006_paired_arm":
        errors.append("E006 runner identity mismatch")
    if config.get("experiment_id") != "E006" or config.get("phase") != "development":
        errors.append("E006 experiment/phase identity mismatch")
    if config.get("pair_id") != PAIR_ID:
        errors.append("E006 pair identity mismatch")
    if arm == "control" and (
        config.get("control_anchor") is not None
        or config.get("treatment_claim_sha256") is not None
    ):
        errors.append("E006 control must not contain a treatment anchor/claim")
    if arm == "treatment" and (
        not isinstance(config.get("control_anchor"), dict)
        or not str(config.get("treatment_claim_sha256") or "")
    ):
        errors.append("E006 treatment lacks its control anchor/one-shot claim")
    if config.get("arm") != arm:
        errors.append("E006 trace arm mismatch")
    if config.get("pipeline_version") != E006_PIPELINE_VERSION:
        errors.append("E006 trace pipeline identity mismatch")
    if config.get("retrieval_control_profile") != "v0-82041d0":
        errors.append("E006 control profile mismatch")
    if config.get("enable_option_document_route") is not (arm == "treatment"):
        errors.append("E006 treatment flag differs from arm")
    if tuple(map(str, config.get("qids") or [])) != DEVELOPMENT_QIDS:
        errors.append("E006 trace qids/order differ from frozen development set")
    if int(config.get("top_k") or 0) != V0_TOP_K:
        errors.append("E006 top_k mismatch")
    if float(config.get("temperature", -1)) != 0.0:
        errors.append("E006 temperature mismatch")
    if config.get("selection_sha256") != FROZEN_INPUT_SHA256["selection"]:
        errors.append("E006 trace selection hash mismatch")
    if config.get("selection_file") != display_path(DEVELOPMENT_SELECTION_PATH):
        errors.append("E006 trace selection path mismatch")
    if config.get("output_dir") != display_path(output_dir.resolve()):
        errors.append("E006 trace output path mismatch")
    if output_dir.resolve() != EXPECTED_OUTPUT_DIRS[arm].resolve():
        errors.append("E006 trace output is outside its registered pair slot")
    artifact_hashes = {
        name: str((entry or {}).get("sha256") or "")
        for name, entry in (config.get("input_artifacts") or {}).items()
    }
    if artifact_hashes != FROZEN_INPUT_SHA256:
        errors.append("E006 trace input-artifact hashes mismatch")

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
        return [*errors, f"unable to inspect E006 trace files: {exc}"]
    if len(calls) != 52 or len(derivations) != 13:
        errors.append("E006 trace must contain exactly 52 calls and 13 derivations")
    if [str(row.get("qid") or "") for row in derivations] != list(DEVELOPMENT_QIDS):
        errors.append("E006 derivation qids/order mismatch")
    claimed: list[str] = []
    for row in derivations:
        call_ids = list(map(str, row.get("trace_call_ids") or []))
        if len(call_ids) != 4 or len(set(call_ids)) != 4:
            errors.append(f"{row.get('qid')}: derivation must claim four unique calls")
        input_judgments = (row.get("answer_derivation") or {}).get(
            "input_judgments"
        ) or {}
        if sorted(input_judgments) != list("ABCD"):
            errors.append(f"{row.get('qid')}: derivation must contain A/B/C/D judgments")
        claimed.extend(call_ids)
    actual_ids = [str(call.get("call_id") or "") for call in calls]
    if len(claimed) != len(set(claimed)) or set(claimed) != set(actual_ids):
        errors.append("E006 calls are orphaned, duplicated, or cross-linked")
    for qid in DEVELOPMENT_QIDS:
        qid_calls = [
            call for call in calls if str((call.get("context") or {}).get("qid") or "") == qid
        ]
        option_keys = [
            str((call.get("context") or {}).get("option_key") or "")
            for call in qid_calls
        ]
        if len(qid_calls) != 4 or sorted(option_keys) != list("ABCD"):
            errors.append(f"{qid}: must have exactly one call for each A/B/C/D option")
    for call in calls:
        context = call.get("context") or {}
        qid = str(context.get("qid") or "")
        option_key = str(context.get("option_key") or "")
        if qid not in DEVELOPMENT_QIDS or option_key not in "ABCD":
            errors.append("E006 call contains an unknown qid/option")
        if context.get("stage") != f"e006_{arm}_v0_option_judgment":
            errors.append(f"{qid}:{option_key}: trace stage mismatch")
        if context.get("prompt_profile") != "v0-82041d0":
            errors.append(f"{qid}:{option_key}: prompt profile mismatch")
        if not call.get("provider_request_id"):
            errors.append(f"{qid}:{option_key}: provider request id missing")
        if not str(call.get("response_model") or "").startswith("qwen-plus"):
            errors.append(f"{qid}:{option_key}: served model is not qwen-plus")
        if call.get("tool_calls") != []:
            errors.append(f"{qid}:{option_key}: tool calls are forbidden")
        if call.get("finish_reason") != "stop":
            errors.append(f"{qid}:{option_key}: finish_reason is not stop")
        request_payload = call.get("request_payload") or {}
        if request_payload.get("model") != "qwen-plus":
            errors.append(f"{qid}:{option_key}: requested model is not qwen-plus")
        if float(request_payload.get("temperature", -1)) != 0.0:
            errors.append(f"{qid}:{option_key}: request temperature mismatch")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--arm", choices=sorted(ARMS), required=True)
    parser.add_argument("--phase", choices=sorted(PHASES), default="development")
    parser.add_argument("--top-k", type=int, default=V0_TOP_K)
    args = parser.parse_args()

    if args.top_k != V0_TOP_K:
        raise ValueError(f"E006 freezes top_k={V0_TOP_K}")
    if args.output_dir.exists():
        raise ValueError(f"output directory must be absent: {args.output_dir}")
    if args.output_dir.resolve() in {
        (REPO_ROOT / "submission").resolve(),
        (REPO_ROOT / "outputs" / "candidates").resolve(),
    }:
        raise ValueError("E006 pilot cannot write to a candidate/submission directory")
    if args.output_dir.resolve() != EXPECTED_OUTPUT_DIRS[args.arm].resolve():
        raise ValueError(
            f"E006 {PAIR_ID}/{args.arm} must use its exact registered output directory: "
            f"{EXPECTED_OUTPUT_DIRS[args.arm]}"
        )

    selection = _load_selection(args.selection, phase=args.phase, arm=args.arm)
    frozen_inputs = _verify_frozen_inputs(args.selection)
    control_anchor = _verified_control_anchor() if args.arm == "treatment" else None
    qids = selection["qids"]
    questions = {str(item["qid"]): item for item in load_all_questions()}
    _validate_questions(qids, questions)
    chunks = load_chunks()
    doc_meta = load_doc_meta()
    if args.arm == "treatment" and not doc_meta:
        raise ValueError("E006 treatment requires deterministic doc_meta")
    try:
        client = QwenClient()
    except MissingApiKeyError as exc:
        print(f"[error] {exc}")
        return 1
    if client.model != "qwen-plus":
        raise ValueError(f"E006 freezes model=qwen-plus, got {client.model!r}")
    if client.base_url.rstrip("/") != OFFICIAL_DASHSCOPE_BASE_URL:
        raise ValueError("E006 requires the official DashScope endpoint")

    treatment_claim: dict[str, Any] | None = None
    treatment_claim_sha256: str | None = None
    if args.arm == "treatment":
        treatment_claim, treatment_claim_sha256 = _claim_treatment_once(control_anchor)

    args.output_dir.mkdir(parents=True, exist_ok=False)
    observations_path = args.output_dir / "observations.json"
    trace_dir = args.output_dir / "agent_traces" / f"e006-{args.arm}-{uuid.uuid4()}"
    allowed_read_roots = (
        (REPO_ROOT / "agent").resolve(),
        (REPO_ROOT / "public_dataset_upload" / "questions" / "group_a").resolve(),
        (REPO_ROOT / "processed_data" / "chunks.jsonl").resolve(),
        (REPO_ROOT / "processed_data" / "doc_meta.json").resolve(),
        args.selection.resolve(),
        CONTROL_REFERENCE_PATH.resolve(),
        OFFLINE_GATE_PATH.resolve(),
        args.output_dir.resolve(),
    )
    recorder: AgentTraceRecorder | None = None
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    try:
        with blind_data_guard(
            default_candidate_forbidden_roots(),
            allowed_read_roots=allowed_read_roots,
            allowed_write_roots=(args.output_dir.resolve(),),
            block_subprocess=True,
        ):
            recorder = AgentTraceRecorder(
                trace_dir,
                purpose=f"e006_{args.phase}_{args.arm}",
                model=client.model,
                base_url=client.base_url,
                config={
                    "runner": "agent.run_e006_paired_arm",
                    "experiment_id": "E006",
                    "pair_id": PAIR_ID,
                    "control_anchor": control_anchor,
                    "treatment_claim_sha256": treatment_claim_sha256,
                    "phase": args.phase,
                    "arm": args.arm,
                    "pipeline_version": E006_PIPELINE_VERSION,
                    "online_parent_pipeline_version": "v2s1",
                    "retrieval_control_profile": "v0-82041d0",
                    "enable_option_document_route": args.arm == "treatment",
                    "qids": qids,
                    "top_k": V0_TOP_K,
                    "selection_file": display_path(args.selection),
                    "selection_sha256": sha256_file(args.selection),
                    "output_dir": display_path(args.output_dir),
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
                },
            )
            client.trace_recorder = recorder
            for qid in qids:
                question = questions[qid]
                diagnostics: dict[str, Any] = {}
                retrieval = retrieve_multi_v0_compatible(
                    question,
                    chunks,
                    enable_option_document_route=args.arm == "treatment",
                    top_k=V0_TOP_K,
                    doc_meta=doc_meta,
                    diagnostics_out=diagnostics,
                )
                result = reason_multi_with_v0_prompt(
                    question,
                    retrieval,
                    client=client,
                    arm=args.arm,
                )
                result["retrieval"] = _compact_retrieval(retrieval)
                result["route_diagnostics"] = diagnostics
                results.append(result)
                recorder.record_derivation(result)

            for result in results:
                failures.extend(
                    {"qid": str(result.get("qid") or ""), "error": error}
                    for error in _validate_result(result, arm=args.arm)
                )
            payload = {
                "schema_version": "e006-observations/v1",
                "experiment_id": "E006",
                "pair_id": PAIR_ID,
                "control_anchor": control_anchor,
                "treatment_claim_sha256": treatment_claim_sha256,
                "phase": args.phase,
                "arm": args.arm,
                "pipeline_version": E006_PIPELINE_VERSION,
                "online_parent_pipeline_version": "v2s1",
                "retrieval_control_profile": "v0-82041d0",
                "selection_file": display_path(args.selection),
                "selection_sha256": sha256_file(args.selection),
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
        validate_e006_trace_contract(
            trace_report,
            trace_dir=recorder.trace_dir,
            arm=args.arm,
            output_dir=args.output_dir,
        )
    )
    trace_report["ok"] = not trace_report.get("errors")
    expected_calls = 52
    if trace_report.get("call_count") != expected_calls:
        trace_report.setdefault("errors", []).append(
            f"E006 call topology mismatch: {trace_report.get('call_count')} != {expected_calls}"
        )
        trace_report["ok"] = False
    if trace_report.get("derivation_count") != 13:
        trace_report.setdefault("errors", []).append("E006 derivation topology mismatch")
        trace_report["ok"] = False
    calls = [
        json.loads(line)
        for line in recorder.calls_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    expected_stage = f"e006_{args.arm}_v0_option_judgment"
    for qid in qids:
        qid_calls = [call for call in calls if (call.get("context") or {}).get("qid") == qid]
        option_keys = sorted(
            str((call.get("context") or {}).get("option_key") or "")
            for call in qid_calls
        )
        stages = {
            str((call.get("context") or {}).get("stage") or "") for call in qid_calls
        }
        if option_keys != list("ABCD") or stages != {expected_stage}:
            trace_report.setdefault("errors", []).append(
                f"{qid}: invalid option/stage topology"
            )
            trace_report["ok"] = False

    receipt = {
        "schema_version": "e006-run-receipt/v1",
        "experiment_id": "E006",
        "pair_id": PAIR_ID,
        "control_anchor": control_anchor,
        "treatment_claim_sha256": treatment_claim_sha256,
        "phase": args.phase,
        "arm": args.arm,
        "status": "PASS" if trace_report.get("ok") and not failures else "FAIL",
        "selection_sha256": sha256_file(args.selection),
        "observations_sha256": sha256_file(observations_path),
        "trace_run_id": recorder.run_id,
        "trace_manifest_sha256": sha256_file(recorder.manifest_path),
        "code_sha256": (trace_report.get("manifest") or {}).get("code", {}).get("sha256"),
        "config_sha256": (trace_report.get("manifest") or {}).get("config_sha256"),
        "model_sha256": (trace_report.get("manifest") or {}).get("model_sha256"),
        "input_artifacts_sha256": sha256_json(frozen_inputs),
        "pipeline_version": E006_PIPELINE_VERSION,
        "call_count": trace_report.get("call_count"),
        "derivation_count": trace_report.get("derivation_count"),
        "total_tokens": sum(int(result.get("total_tokens") or 0) for result in results),
        "errors": [
            *trace_report.get("errors", []),
            *(failure["error"] for failure in failures),
        ],
        "created_at": now_iso(),
    }
    receipt_path = args.output_dir / "run_receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if receipt["status"] != "PASS":
        for error in receipt["errors"]:
            print(f"[e006-error] {error}")
        return 1
    print(
        f"E006 {args.phase}/{args.arm}=PASS questions={len(qids)} "
        f"calls={expected_calls} tokens={receipt['total_tokens']} output={args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
