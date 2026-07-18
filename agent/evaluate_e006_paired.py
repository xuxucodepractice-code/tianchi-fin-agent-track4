"""Strictly evaluate fresh paired E006 development control/treatment runs."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.doc_meta import load_doc_meta
from agent.load_questions import load_all_questions
from agent.normalize_answer import normalize_answer
from agent.paths import REPO_ROOT
from agent.reason_multi_v0_compat import E006_PIPELINE_VERSION
from agent.reason_multi_v0_compat import build_option_judgment_messages_v0
from agent.retrieve import load_chunks
from agent.retrieve_v0_compat import V0_TOP_K, retrieve_multi_v0_compatible
from agent.run_e006_paired_arm import (
    DEVELOPMENT_QIDS,
    DEVELOPMENT_SELECTION_PATH,
    EXPECTED_OUTPUT_DIRS,
    FROZEN_INPUT_SHA256,
    OFFLINE_GATE_PATH,
    PAIR_ID,
    TREATMENT_CLAIM_PATH,
    _compact_retrieval,
    _validate_result,
    validate_e006_trace_contract,
)
from agent.trace_gate import (
    canonical_json_bytes,
    resolve_recorded_path,
    sha256_file,
    sha256_json,
    validate_trace_directory,
)

DEVELOPMENT_LABELS_PATH = (
    REPO_ROOT
    / "workspace"
    / "03_baseline_improvement"
    / "experiments"
    / "E006_multi_retrieval_coverage"
    / "development_labels.json"
)
DEVELOPMENT_LABELS_SHA256 = (
    "ac20951dab02ec5fd2c31571a78f9129f08a2f969db81c722b9128a437d9fedd"
)


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _observation_rows(payload: dict[str, Any], *, arm: str) -> list[dict[str, Any]]:
    if payload.get("schema_version") != "e006-observations/v1":
        raise ValueError(f"{arm}: observations schema mismatch")
    if payload.get("experiment_id") != "E006" or payload.get("phase") != "development":
        raise ValueError(f"{arm}: experiment/phase mismatch")
    if payload.get("pair_id") != PAIR_ID:
        raise ValueError(f"{arm}: pair identity mismatch")
    if payload.get("arm") != arm:
        raise ValueError(f"{arm}: arm identity mismatch")
    if payload.get("pipeline_version") != E006_PIPELINE_VERSION:
        raise ValueError(f"{arm}: pipeline identity mismatch")
    if payload.get("retrieval_control_profile") != "v0-82041d0":
        raise ValueError(f"{arm}: control profile mismatch")
    qids = list(map(str, payload.get("qids") or []))
    if tuple(qids) != DEVELOPMENT_QIDS:
        raise ValueError(f"{arm}: qids/order differ from frozen development set")
    rows = payload.get("observations") or []
    if not isinstance(rows, list):
        raise ValueError(f"{arm}: observations must be a list")
    row_qids = [str(row.get("qid") or "") for row in rows if isinstance(row, dict)]
    if len(rows) != 13 or len(row_qids) != 13 or len(set(row_qids)) != 13:
        raise ValueError(f"{arm}: observations must contain 13 unique rows")
    if row_qids != list(DEVELOPMENT_QIDS):
        raise ValueError(f"{arm}: observation qids/order mismatch")
    if int(payload.get("question_count") or 0) != 13:
        raise ValueError(f"{arm}: question_count must be 13")
    if int(payload.get("api_call_count") or 0) != 52:
        raise ValueError(f"{arm}: api_call_count must be 52")
    if payload.get("failures") != []:
        raise ValueError(f"{arm}: observations contain failures")
    for row in rows:
        errors = _validate_result(row, arm=arm)
        if errors:
            raise ValueError(f"{arm}: invalid result: {errors}")
        judgments = row.get("option_judgments") or {}
        if sorted(judgments) != list("ABCD"):
            raise ValueError(f"{arm}:{row.get('qid')}: judgments must be A/B/C/D")
        expected_inputs = {
            option: {
                "judgment": judgment.get("judgment"),
                "evidence_refs": judgment.get("evidence_refs", []),
                "error": judgment.get("error"),
            }
            for option, judgment in sorted(judgments.items())
        }
        derivation = row.get("answer_derivation") or {}
        if derivation.get("method") != "agent.normalize_answer.normalize_answer":
            raise ValueError(f"{arm}:{row.get('qid')}: normalizer identity mismatch")
        if derivation.get("answer_format") != "multi":
            raise ValueError(f"{arm}:{row.get('qid')}: derivation format mismatch")
        if derivation.get("input_judgments") != expected_inputs:
            raise ValueError(
                f"{arm}:{row.get('qid')}: derivation inputs differ from option judgments"
            )
        if str(derivation.get("output_answer") or "") != str(row.get("answer") or ""):
            raise ValueError(f"{arm}:{row.get('qid')}: derivation output mismatch")
        replay = normalize_answer("multi", judgments, row.get("options") or {})
        if str(replay.get("answer") or "") != str(row.get("answer") or ""):
            raise ValueError(f"{arm}:{row.get('qid')}: option judgments replay changed answer")
    return rows


def _semantic_config(config: dict[str, Any]) -> dict[str, Any]:
    """Remove only the three fields that are expected to differ by paired arm."""
    return {
        key: value
        for key, value in config.items()
        if key
        not in {
            "arm",
            "enable_option_document_route",
            "output_dir",
            "control_anchor",
            "treatment_claim_sha256",
        }
    }


def load_run_bundle(
    observations_path: Path,
    receipt_path: Path,
    *,
    expected_arm: str,
) -> dict[str, Any]:
    """Load and cryptographically bind observations, receipt, and strict Trace."""
    observations_path = observations_path.resolve()
    receipt_path = receipt_path.resolve()
    if observations_path != (EXPECTED_OUTPUT_DIRS[expected_arm] / "observations.json").resolve():
        raise ValueError(f"{expected_arm}: observations are outside the registered pair slot")
    if receipt_path != (EXPECTED_OUTPUT_DIRS[expected_arm] / "run_receipt.json").resolve():
        raise ValueError(f"{expected_arm}: receipt is outside the registered pair slot")
    observations = _load(observations_path)
    receipt = _load(receipt_path)
    errors: list[str] = []
    try:
        _observation_rows(observations, arm=expected_arm)
    except ValueError as exc:
        errors.append(str(exc))

    trace_meta = observations.get("agent_trace") or {}
    trace_dir_value = str(trace_meta.get("trace_dir") or "")
    trace_dir = resolve_recorded_path(trace_dir_value) if trace_dir_value else Path("/")
    trace_report = validate_trace_directory(
        trace_dir,
        require_candidate_eligible=False,
        require_current_code_match=True,
    )
    errors.extend(map(str, trace_report.get("errors") or []))
    errors.extend(
        validate_e006_trace_contract(
            trace_report,
            trace_dir=trace_dir,
            arm=expected_arm,
            output_dir=observations_path.parent,
        )
    )
    manifest = trace_report.get("manifest") or {}
    config = manifest.get("config") or {}
    expected_receipt = {
        "schema_version": "e006-run-receipt/v1",
        "experiment_id": "E006",
        "pair_id": PAIR_ID,
        "phase": "development",
        "arm": expected_arm,
        "status": "PASS",
        "selection_sha256": FROZEN_INPUT_SHA256["selection"],
        "observations_sha256": sha256_file(observations_path),
        "trace_run_id": str(trace_meta.get("trace_run_id") or ""),
        "trace_manifest_sha256": (
            sha256_file(trace_dir / "trace_manifest.json")
            if (trace_dir / "trace_manifest.json").is_file()
            else ""
        ),
        "code_sha256": str((manifest.get("code") or {}).get("sha256") or ""),
        "config_sha256": str(manifest.get("config_sha256") or ""),
        "model_sha256": str(manifest.get("model_sha256") or ""),
        "input_artifacts_sha256": sha256_json(config.get("input_artifacts") or {}),
        "pipeline_version": E006_PIPELINE_VERSION,
        "call_count": 52,
        "derivation_count": 13,
    }
    for key, expected in expected_receipt.items():
        if receipt.get(key) != expected:
            errors.append(
                f"{expected_arm}: receipt {key} mismatch: {receipt.get(key)!r} != {expected!r}"
            )
    if receipt.get("errors") != []:
        errors.append(f"{expected_arm}: receipt contains errors")
    if str(manifest.get("trace_run_id") or "") != expected_receipt["trace_run_id"]:
        errors.append(f"{expected_arm}: observations trace_run_id differs from manifest")
    if observations.get("selection_sha256") != FROZEN_INPUT_SHA256["selection"]:
        errors.append(f"{expected_arm}: observations selection hash mismatch")
    if Path(str(observations.get("selection_file") or "")).as_posix() != Path(
        str(config.get("selection_file") or "")
    ).as_posix():
        errors.append(f"{expected_arm}: observations selection path differs from Trace")
    try:
        derivations = [
            json.loads(line)
            for line in (trace_dir / "derivations.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        rows = observations.get("observations") or []
        if len(derivations) != len(rows):
            errors.append(f"{expected_arm}: observations/derivations length mismatch")
        else:
            for row, derivation in zip(rows, derivations, strict=True):
                qid = str(row.get("qid") or "")
                if str(derivation.get("qid") or "") != qid:
                    errors.append(f"{expected_arm}:{qid}: derivation qid mismatch")
                if str(derivation.get("answer") or "") != str(row.get("answer") or ""):
                    errors.append(f"{expected_arm}:{qid}: answer differs from Trace")
                if derivation.get("answer_derivation") != row.get("answer_derivation"):
                    errors.append(
                        f"{expected_arm}:{qid}: answer derivation differs from Trace"
                    )
                if derivation.get("retrieval_sha256") != sha256_json(
                    row.get("retrieval") or {}
                ):
                    errors.append(f"{expected_arm}:{qid}: retrieval differs from Trace")
                for token_key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    if int(derivation.get(token_key) or 0) != int(
                        row.get(token_key) or 0
                    ):
                        errors.append(
                            f"{expected_arm}:{qid}: {token_key} differs from Trace"
                        )
        row_tokens = sum(int(row.get("total_tokens") or 0) for row in rows)
        if int(observations.get("total_tokens") or 0) != row_tokens:
            errors.append(f"{expected_arm}: observation token total mismatch")
        if int(receipt.get("total_tokens") or 0) != row_tokens:
            errors.append(f"{expected_arm}: receipt token total mismatch")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"{expected_arm}: unable to correlate observations with Trace: {exc}")
    return {
        "observations": observations,
        "receipt": receipt,
        "manifest": manifest,
        "trace_report": trace_report,
        "trace_dir": trace_dir,
        "calls": (
            [
                json.loads(line)
                for line in (trace_dir / "calls.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
            if (trace_dir / "calls.jsonl").is_file()
            else []
        ),
        "errors": errors,
    }


def call_prompt_binding_errors(
    calls: list[dict[str, Any]],
    rows: dict[str, dict[str, Any]],
    questions: dict[str, dict[str, Any]],
    *,
    arm: str,
    qids: tuple[str, ...] = DEVELOPMENT_QIDS,
) -> list[str]:
    """Bind every exact model message/evidence pack to one qid/option pair."""
    errors: list[str] = []
    if len(calls) != len(qids) * 4:
        errors.append(f"{arm}: call count differs from qids*4")
    for qid in qids:
        question = questions[qid]
        row = rows[qid]
        for option_key in "ABCD":
            matches = [
                call
                for call in calls
                if str((call.get("context") or {}).get("qid") or "") == qid
                and str((call.get("context") or {}).get("option_key") or "")
                == option_key
            ]
            option_id = f"{arm}:{qid}:{option_key}"
            if len(matches) != 1:
                errors.append(f"{option_id}: expected exactly one API call")
                continue
            call = matches[0]
            context = call.get("context") or {}
            option_text = str(question["options"][option_key])
            evidence = row["retrieval"][option_key]["evidence"]
            expected_messages = build_option_judgment_messages_v0(
                question, option_key, option_text, evidence
            )
            if context.get("stage") != f"e006_{arm}_v0_option_judgment":
                errors.append(f"{option_id}: stage mismatch")
            if context.get("prompt_profile") != "v0-82041d0":
                errors.append(f"{option_id}: prompt profile mismatch")
            if str(context.get("option_text") or "") != option_text:
                errors.append(f"{option_id}: option text differs from frozen question")
            if call.get("model_evidence") != evidence:
                errors.append(f"{option_id}: model evidence differs from retrieval")
            if call.get("messages") != expected_messages:
                errors.append(f"{option_id}: exact messages differ from v0 prompt replay")
            judgment = (row.get("option_judgments") or {}).get(option_key) or {}
            if str(judgment.get("trace_call_id") or "") != str(call.get("call_id") or ""):
                errors.append(f"{option_id}: judgment trace_call_id differs from raw call")
            if str(judgment.get("trace_run_id") or "") != str(
                call.get("trace_run_id") or ""
            ):
                errors.append(f"{option_id}: judgment trace_run_id differs from raw call")
    expected_pairs = {(qid, option) for qid in qids for option in "ABCD"}
    actual_pairs = {
        (
            str((call.get("context") or {}).get("qid") or ""),
            str((call.get("context") or {}).get("option_key") or ""),
        )
        for call in calls
    }
    if actual_pairs != expected_pairs:
        errors.append(f"{arm}: call qid/option pair set mismatch")
    return errors


def replay_retrieval_errors(
    control_bundle: dict[str, Any], treatment_bundle: dict[str, Any]
) -> list[str]:
    """Recompute retrieval and bind it to the exact prompts actually sent."""
    errors: list[str] = []
    questions = {str(item["qid"]): item for item in load_all_questions()}
    chunks = load_chunks()
    doc_meta = load_doc_meta()
    for arm, bundle, enabled in (
        ("control", control_bundle, False),
        ("treatment", treatment_bundle, True),
    ):
        payload = bundle["observations"]
        rows = {str(row["qid"]): row for row in payload.get("observations") or []}
        for qid in DEVELOPMENT_QIDS:
            diagnostics: dict[str, Any] = {}
            expected = retrieve_multi_v0_compatible(
                questions[qid],
                chunks,
                enable_option_document_route=enabled,
                top_k=V0_TOP_K,
                doc_meta=doc_meta,
                diagnostics_out=diagnostics,
            )
            row = rows.get(qid) or {}
            if row.get("retrieval") != _compact_retrieval(expected):
                errors.append(f"{arm}:{qid}: retrieval differs from deterministic replay")
            if row.get("route_diagnostics") != diagnostics:
                errors.append(f"{arm}:{qid}: route diagnostics differ from replay")
        errors.extend(
            call_prompt_binding_errors(
                bundle.get("calls") or [],
                rows,
                questions,
                arm=arm,
            )
        )
    return errors


def verify_pair_anchor_errors(
    control_bundle: dict[str, Any],
    treatment_bundle: dict[str, Any],
    *,
    output_dirs: dict[str, Path] | None = None,
    claim_path: Path | None = None,
) -> list[str]:
    """Bind the only treatment attempt to the exact preceding control bundle."""
    errors: list[str] = []
    resolved_output_dirs = output_dirs or EXPECTED_OUTPUT_DIRS
    resolved_claim_path = claim_path or TREATMENT_CLAIM_PATH
    control_observations_path = resolved_output_dirs["control"] / "observations.json"
    control_receipt_path = resolved_output_dirs["control"] / "run_receipt.json"
    control_trace_dir = control_bundle["trace_dir"]
    expected_anchor = {
        "pair_id": PAIR_ID,
        "control_trace_run_id": str(
            (control_bundle["observations"].get("agent_trace") or {}).get(
                "trace_run_id"
            )
            or ""
        ),
        "control_observations_sha256": sha256_file(control_observations_path),
        "control_trace_manifest_sha256": sha256_file(
            control_trace_dir / "trace_manifest.json"
        ),
        "control_receipt_sha256": sha256_file(control_receipt_path),
    }
    control_config = control_bundle["manifest"].get("config") or {}
    treatment_config = treatment_bundle["manifest"].get("config") or {}
    if control_config.get("control_anchor") is not None:
        errors.append("control: control_anchor must be null")
    if control_config.get("treatment_claim_sha256") is not None:
        errors.append("control: treatment claim must be null")
    if control_bundle["receipt"].get("control_anchor") is not None:
        errors.append("control: receipt control_anchor must be null")
    if control_bundle["receipt"].get("treatment_claim_sha256") is not None:
        errors.append("control: receipt treatment claim must be null")
    for label, value in (
        ("treatment config", treatment_config.get("control_anchor")),
        ("treatment observations", treatment_bundle["observations"].get("control_anchor")),
        ("treatment receipt", treatment_bundle["receipt"].get("control_anchor")),
    ):
        if value != expected_anchor:
            errors.append(f"{label}: control anchor mismatch")
    if not resolved_claim_path.is_file():
        return [*errors, "registered treatment claim is missing"]
    claim = _load(resolved_claim_path)
    claim_sha256 = sha256_file(resolved_claim_path)
    if claim.get("schema_version") != "e006-treatment-claim/v1":
        errors.append("treatment claim schema mismatch")
    if claim.get("pair_id") != PAIR_ID or claim.get("experiment_id") != "E006":
        errors.append("treatment claim identity mismatch")
    if claim.get("status") != "TREATMENT_ATTEMPT_CLAIMED":
        errors.append("treatment claim status mismatch")
    if claim.get("control_anchor") != expected_anchor:
        errors.append("treatment claim control anchor mismatch")
    for label, value in (
        ("treatment config", treatment_config.get("treatment_claim_sha256")),
        (
            "treatment observations",
            treatment_bundle["observations"].get("treatment_claim_sha256"),
        ),
        (
            "treatment receipt",
            treatment_bundle["receipt"].get("treatment_claim_sha256"),
        ),
    ):
        if value != claim_sha256:
            errors.append(f"{label}: treatment claim hash mismatch")
    try:
        control_finished = datetime.fromisoformat(
            str(control_bundle["manifest"]["finished_at"])
        )
        claimed_at = datetime.fromisoformat(str(claim["claimed_at"]))
        treatment_started = datetime.fromisoformat(
            str(treatment_bundle["manifest"]["started_at"])
        )
        if not control_finished <= claimed_at <= treatment_started:
            errors.append("treatment claim time is outside control/treatment boundary")
    except (KeyError, TypeError, ValueError):
        errors.append("unable to validate treatment claim timestamps")
    return errors


def evaluate_paired(
    control: dict[str, Any],
    treatment: dict[str, Any],
    labels_payload: dict[str, Any],
    *,
    control_receipt: dict[str, Any],
    treatment_receipt: dict[str, Any],
    control_manifest: dict[str, Any],
    treatment_manifest: dict[str, Any],
    bundle_errors: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Evaluate the frozen 13-question development pair; reject arbitrary subsets."""
    control_rows_list = _observation_rows(control, arm="control")
    treatment_rows_list = _observation_rows(treatment, arm="treatment")
    if labels_payload.get("schema_version") != "e006-development-labels/v1":
        raise ValueError("development labels schema mismatch")
    if labels_payload.get("experiment_id") != "E006":
        raise ValueError("development labels experiment mismatch")
    if labels_payload.get("role") != "retrospective_development_only":
        raise ValueError("development labels role mismatch")
    if labels_payload.get("labels_known_before_code_freeze") is not True:
        raise ValueError("development labels provenance mismatch")

    labels = {str(key): str(value) for key, value in labels_payload["labels"].items()}
    parent_answers = {
        str(key): str(value)
        for key, value in labels_payload["frozen_online_v2s1_answers"].items()
    }
    if tuple(labels) != DEVELOPMENT_QIDS or tuple(parent_answers) != DEVELOPMENT_QIDS:
        raise ValueError("labels/parent answers do not match frozen qids/order")
    derived_parent_correct = {
        qid for qid in DEVELOPMENT_QIDS if parent_answers[qid] == labels[qid]
    }
    declared_parent_correct = set(
        map(str, labels_payload.get("frozen_parent_correct_qids") or [])
    )
    if declared_parent_correct != derived_parent_correct:
        raise ValueError("declared parent-correct set differs from truth-derived set")

    control_rows = {str(row["qid"]): row for row in control_rows_list}
    treatment_rows = {str(row["qid"]): row for row in treatment_rows_list}
    paired_n = paired_m = both_correct = both_wrong = 0
    parent_n = parent_m = 0
    parent_regressions: list[str] = []
    control_parent_churn: list[str] = []
    treatment_parent_churn: list[str] = []
    answer_changes: list[str] = []
    changed_evidence_options: list[str] = []
    routed_options: list[str] = []
    routed_changed_options: list[str] = []
    routed_noop_options: list[str] = []
    unique_variable_errors: list[str] = []
    rows: list[dict[str, Any]] = []

    for qid in DEVELOPMENT_QIDS:
        truth = labels[qid]
        parent_answer = parent_answers[qid]
        control_row = control_rows[qid]
        treatment_row = treatment_rows[qid]
        control_answer = str(control_row["answer"])
        treatment_answer = str(treatment_row["answer"])
        control_correct = control_answer == truth
        treatment_correct = treatment_answer == truth
        parent_correct = parent_answer == truth
        paired_n += int(not control_correct and treatment_correct)
        paired_m += int(control_correct and not treatment_correct)
        both_correct += int(control_correct and treatment_correct)
        both_wrong += int(not control_correct and not treatment_correct)
        parent_n += int(not parent_correct and treatment_correct)
        parent_m += int(parent_correct and not treatment_correct)
        if parent_correct and not treatment_correct:
            parent_regressions.append(qid)
        if control_answer != parent_answer:
            control_parent_churn.append(qid)
        if treatment_answer != parent_answer:
            treatment_parent_churn.append(qid)
        if control_answer != treatment_answer:
            answer_changes.append(f"{qid}:{control_answer}->{treatment_answer}")

        for option_key in "ABCD":
            option_id = f"{qid}:{option_key}"
            control_evidence = control_row["retrieval"][option_key]["evidence"]
            treatment_evidence = treatment_row["retrieval"][option_key]["evidence"]
            control_diag = control_row["route_diagnostics"]["options"][option_key]
            treatment_diag = treatment_row["route_diagnostics"]["options"][option_key]
            control_ids = [str(item.get("chunk_id") or "") for item in control_evidence]
            treatment_ids = [
                str(item.get("chunk_id") or "") for item in treatment_evidence
            ]
            changed = canonical_json_bytes(control_evidence) != canonical_json_bytes(
                treatment_evidence
            )
            if changed:
                changed_evidence_options.append(option_id)
            if control_diag.get("decision") != "fallback" or control_diag.get(
                "reason"
            ) != "route_disabled_control":
                unique_variable_errors.append(f"{option_id}: invalid control decision")
            if list(map(str, control_diag.get("selected_chunk_ids") or [])) != control_ids:
                unique_variable_errors.append(f"{option_id}: control diagnostics mismatch")
            if list(map(str, treatment_diag.get("control_chunk_ids") or [])) != control_ids:
                unique_variable_errors.append(
                    f"{option_id}: treatment control baseline differs from paired control"
                )
            decision = treatment_diag.get("decision")
            if decision == "fallback":
                if changed or treatment_ids != control_ids:
                    unique_variable_errors.append(
                        f"{option_id}: fallback evidence is not byte-identical"
                    )
            elif decision == "route":
                target = str(treatment_diag.get("target_doc_id") or "")
                routed_options.append(f"{option_id}->{target}")
                if any(str(item.get("doc_id") or "") != target for item in treatment_evidence):
                    unique_variable_errors.append(
                        f"{option_id}: routed evidence escaped target document"
                    )
                if treatment_ids != list(
                    map(str, treatment_diag.get("selected_chunk_ids") or [])
                ):
                    unique_variable_errors.append(
                        f"{option_id}: routed diagnostics differ from evidence"
                    )
                if changed:
                    routed_changed_options.append(option_id)
                else:
                    routed_noop_options.append(option_id)
            else:
                unique_variable_errors.append(f"{option_id}: unknown treatment decision")
            if changed != (decision == "route" and treatment_ids != control_ids):
                unique_variable_errors.append(
                    f"{option_id}: changed evidence is not explained by routing"
                )

        rows.append(
            {
                "qid": qid,
                "truth": truth,
                "frozen_parent_answer": parent_answer,
                "control_answer": control_answer,
                "treatment_answer": treatment_answer,
                "frozen_parent_correct": parent_correct,
                "control_correct": control_correct,
                "treatment_correct": treatment_correct,
            }
        )

    control_config = control_manifest.get("config") or {}
    treatment_config = treatment_manifest.get("config") or {}
    try:
        control_started = datetime.fromisoformat(str(control_manifest["started_at"]))
        control_finished = datetime.fromisoformat(str(control_manifest["finished_at"]))
        treatment_started = datetime.fromisoformat(str(treatment_manifest["started_at"]))
        treatment_finished = datetime.fromisoformat(str(treatment_manifest["finished_at"]))
        pair_time_order_valid = (
            control_started <= control_finished <= treatment_started <= treatment_finished
        )
        pair_elapsed_seconds = (treatment_finished - control_started).total_seconds()
        pair_within_two_hours = 0 <= pair_elapsed_seconds <= 7200
    except (KeyError, TypeError, ValueError):
        pair_time_order_valid = False
        pair_elapsed_seconds = None
        pair_within_two_hours = False
    receipt_checks = {
        "control_receipt_pass": control_receipt.get("status") == "PASS",
        "treatment_receipt_pass": treatment_receipt.get("status") == "PASS",
        "receipts_bind_frozen_selection": (
            control_receipt.get("selection_sha256")
            == treatment_receipt.get("selection_sha256")
            == FROZEN_INPUT_SHA256["selection"]
        ),
        "receipts_bind_registered_pair": (
            control_receipt.get("pair_id")
            == treatment_receipt.get("pair_id")
            == PAIR_ID
            and control_config.get("pair_id")
            == treatment_config.get("pair_id")
            == PAIR_ID
        ),
        "receipts_bind_exact_topology": (
            control_receipt.get("call_count")
            == treatment_receipt.get("call_count")
            == 52
            and control_receipt.get("derivation_count")
            == treatment_receipt.get("derivation_count")
            == 13
        ),
        "same_code": (
            bool(control_receipt.get("code_sha256"))
            and control_receipt.get("code_sha256")
            == treatment_receipt.get("code_sha256")
        ),
        "same_model": (
            bool(control_receipt.get("model_sha256"))
            and control_receipt.get("model_sha256")
            == treatment_receipt.get("model_sha256")
        ),
        "same_input_artifacts": (
            bool(control_receipt.get("input_artifacts_sha256"))
            and control_receipt.get("input_artifacts_sha256")
            == treatment_receipt.get("input_artifacts_sha256")
        ),
        "same_semantic_config_except_arm_route_output": (
            _semantic_config(control_config) == _semantic_config(treatment_config)
        ),
        "pair_time_order_control_then_treatment": pair_time_order_valid,
        "pair_completed_within_two_hours": pair_within_two_hours,
    }
    checks = {
        "bundle_integrity": not bundle_errors,
        "offline_gate_hash_is_frozen": sha256_file(OFFLINE_GATE_PATH)
        == FROZEN_INPUT_SHA256["offline_gate"],
        "exact_13_question_pair": True,
        "unique_retrieval_variable": not unique_variable_errors,
        **receipt_checks,
        "paired_net_at_least_one": paired_n - paired_m >= 1,
        "frozen_parent_net_at_least_one": parent_n - parent_m >= 1,
        "frozen_parent_correct_zero_regression": not parent_regressions,
    }
    control_tokens = int(control.get("total_tokens") or 0)
    treatment_tokens = int(treatment.get("total_tokens") or 0)
    return {
        "schema_version": "e006-paired-development-evaluation/v2",
        "experiment_id": "E006",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "decision": (
            "DEVELOPMENT_GATE_PASS"
            if all(checks.values())
            else "ROLLBACK_DEVELOPMENT_NO_GO"
        ),
        "question_count": 13,
        "paired_control_to_treatment": {
            "N": paired_n,
            "M": paired_m,
            "net": paired_n - paired_m,
            "both_correct": both_correct,
            "both_wrong": both_wrong,
            "control_correct": paired_m + both_correct,
            "treatment_correct": paired_n + both_correct,
        },
        "treatment_vs_frozen_parent": {
            "N": parent_n,
            "M": parent_m,
            "net": parent_n - parent_m,
            "parent_correct": len(derived_parent_correct),
            "treatment_correct": sum(
                treatment_rows[qid]["answer"] == labels[qid]
                for qid in DEVELOPMENT_QIDS
            ),
            "parent_correct_regressions": parent_regressions,
        },
        "stability": {
            "control_vs_frozen_parent_churn_count": len(control_parent_churn),
            "control_vs_frozen_parent_churn_qids": control_parent_churn,
            "treatment_vs_frozen_parent_churn_count": len(treatment_parent_churn),
            "treatment_vs_frozen_parent_churn_qids": treatment_parent_churn,
            "control_vs_treatment_answer_changes": answer_changes,
        },
        "tokens": {
            "control": control_tokens,
            "treatment": treatment_tokens,
            "delta": treatment_tokens - control_tokens,
        },
        "pair": {
            "pair_id": PAIR_ID,
            "control_started_at": control_manifest.get("started_at"),
            "control_finished_at": control_manifest.get("finished_at"),
            "treatment_started_at": treatment_manifest.get("started_at"),
            "treatment_finished_at": treatment_manifest.get("finished_at"),
            "elapsed_seconds": pair_elapsed_seconds,
        },
        "retrieval": {
            "changed_option_pack_count": len(changed_evidence_options),
            "changed_option_packs": changed_evidence_options,
            "routed_option_count": len(routed_options),
            "routed_options": routed_options,
            "routed_changed_options": routed_changed_options,
            "routed_noop_options": routed_noop_options,
            "unique_variable_errors": unique_variable_errors,
        },
        "bundle_errors": list(bundle_errors),
        "checks": checks,
        "rows": rows,
    }


def _failure_report(exc: Exception) -> dict[str, Any]:
    return {
        "schema_version": "e006-paired-development-evaluation/v2",
        "experiment_id": "E006",
        "status": "FAIL",
        "decision": "ROLLBACK_DEVELOPMENT_NO_GO",
        "errors": [str(exc)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--treatment", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--control-receipt", type=Path, required=True)
    parser.add_argument("--treatment-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.labels.resolve() != DEVELOPMENT_LABELS_PATH.resolve():
            raise ValueError("must use the governed E006 development labels path")
        if sha256_file(args.labels) != DEVELOPMENT_LABELS_SHA256:
            raise ValueError("E006 development labels SHA256 mismatch")
        control_bundle = load_run_bundle(
            args.control, args.control_receipt, expected_arm="control"
        )
        treatment_bundle = load_run_bundle(
            args.treatment, args.treatment_receipt, expected_arm="treatment"
        )
        replay_errors = replay_retrieval_errors(control_bundle, treatment_bundle)
        pair_anchor_errors = verify_pair_anchor_errors(
            control_bundle, treatment_bundle
        )
        report = evaluate_paired(
            control_bundle["observations"],
            treatment_bundle["observations"],
            _load(args.labels),
            control_receipt=control_bundle["receipt"],
            treatment_receipt=treatment_bundle["receipt"],
            control_manifest=control_bundle["manifest"],
            treatment_manifest=treatment_bundle["manifest"],
            bundle_errors=[
                *control_bundle["errors"],
                *treatment_bundle["errors"],
                *replay_errors,
                *pair_anchor_errors,
            ],
        )
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        report = _failure_report(exc)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
