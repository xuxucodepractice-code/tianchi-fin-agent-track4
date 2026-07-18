"""Evaluate the frozen E009 development pair and enforce its hard gates."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.load_questions import load_all_questions
from agent.paths import REPO_ROOT
from agent.reason_e007_reference_integrity import (
    build_option_messages,
    parse_treatment_judgment,
)
from agent.reason_qwen import extract_json_from_text
from agent.run_e007_development_arm import (
    DEVELOPMENT_QIDS,
    EXPECTED_OUTPUT_DIRS,
    PAIR_ID,
    RUN_FREEZE_PATH,
    SELECTION_PATH,
    TREATMENT_AUTHORIZATION_PATH,
    TREATMENT_CLAIM_PATH,
)
from agent.trace_gate import resolve_recorded_path, sha256_file, validate_trace_directory

EXPERIMENT_DIR = (
    REPO_ROOT
    / "workspace/03_baseline_improvement/experiments/E009_multi_document_order_binding"
)
LABELS_PATH = EXPERIMENT_DIR / "development_labels.json"
RESULT_PATH = (
    REPO_ROOT
    / "outputs/experiments/E009_multi_document_order_binding/development_evaluation.json"
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _load_bundle(arm: str, output_dir: Path) -> dict[str, Any]:
    observations_path = output_dir / "observations.json"
    receipt_path = output_dir / "run_receipt.json"
    observations = _load_json(observations_path)
    receipt = _load_json(receipt_path)
    trace_dir = resolve_recorded_path(
        str((observations.get("agent_trace") or {}).get("trace_dir") or "")
    )
    trace_report = validate_trace_directory(
        trace_dir, require_candidate_eligible=False, require_current_code_match=True
    )
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
    errors: list[str] = []
    if observations.get("experiment_id") != "E009" or receipt.get("experiment_id") != "E009":
        errors.append(f"{arm}: experiment identity mismatch")
    if observations.get("arm") != arm or receipt.get("arm") != arm:
        errors.append(f"{arm}: arm identity mismatch")
    if observations.get("pair_id") != PAIR_ID or receipt.get("pair_id") != PAIR_ID:
        errors.append(f"{arm}: pair identity mismatch")
    if receipt.get("status") != "PASS" or receipt.get("errors") != []:
        errors.append(f"{arm}: receipt is not clean PASS")
    if not trace_report.get("ok"):
        errors.extend(f"{arm}: {error}" for error in trace_report.get("errors", []))
    if receipt.get("observations_sha256") != sha256_file(observations_path):
        errors.append(f"{arm}: observations hash mismatch")
    if receipt.get("trace_manifest_sha256") != sha256_file(trace_dir / "trace_manifest.json"):
        errors.append(f"{arm}: manifest hash mismatch")
    if receipt.get("run_freeze_sha256") != sha256_file(RUN_FREEZE_PATH):
        errors.append(f"{arm}: run-freeze hash mismatch")
    rows = observations.get("observations") or []
    if len(rows) != 13 or len(calls) != 52 or len(derivations) != 13:
        errors.append(f"{arm}: exact 13/52/13 topology mismatch")
    if int(observations.get("physical_attempt_count") or 0) != 52:
        errors.append(f"{arm}: observations physical attempt count is not 52")
    if int(receipt.get("physical_attempt_count") or 0) != 52:
        errors.append(f"{arm}: receipt physical attempt count is not 52")
    if any(len(call.get("attempts") or []) != 1 for call in calls):
        errors.append(f"{arm}: a call contains zero or multiple physical attempts")
    return {
        "observations": observations,
        "receipt": receipt,
        "trace_dir": trace_dir,
        "trace_report": trace_report,
        "manifest": _load_json(trace_dir / "trace_manifest.json"),
        "calls": calls,
        "derivations": derivations,
        "rows": {str(row.get("qid") or ""): row for row in rows},
        "errors": errors,
    }


def _raw_binding_audit(
    bundle: dict[str, Any],
    questions: dict[str, dict[str, Any]],
    *,
    arm: str,
) -> dict[str, Any]:
    errors: list[str] = []
    unknown_refs: list[str] = []
    duplicate_refs: list[str] = []
    option_mismatches: list[str] = []
    unexpected_fields: list[str] = []
    rows = bundle["rows"]
    calls = bundle["calls"]
    for qid in DEVELOPMENT_QIDS:
        row = rows.get(qid)
        if not row:
            errors.append(f"{arm}:{qid}: missing observation")
            continue
        for option in "ABCD":
            matches = [
                call
                for call in calls
                if str((call.get("context") or {}).get("qid") or "") == qid
                and str((call.get("context") or {}).get("option_key") or "") == option
            ]
            identity = f"{arm}:{qid}:{option}"
            if len(matches) != 1:
                errors.append(f"{identity}: expected exactly one raw call")
                continue
            call = matches[0]
            evidence = ((row.get("retrieval") or {}).get(option) or {}).get("evidence") or []
            expected_messages = build_option_messages(
                questions[qid],
                option,
                str(questions[qid]["options"][option]),
                evidence,
                arm=arm,
            )
            if call.get("model_evidence") != evidence:
                errors.append(f"{identity}: call evidence differs from observation")
            if call.get("messages") != expected_messages:
                errors.append(f"{identity}: exact messages differ from frozen builder")
            judgment = ((row.get("option_judgments") or {}).get(option) or {})
            content = call.get("response_content")
            if not isinstance(content, str):
                errors.append(f"{identity}: missing response content")
                continue
            if arm in {"control", "treatment"}:
                parsed, parse_error = parse_treatment_judgment(content, option)
                if parse_error:
                    errors.append(f"{identity}: {parse_error}")
                    if "schema keys differ" in parse_error:
                        unexpected_fields.append(identity)
                    if "option identity mismatch" in parse_error:
                        option_mismatches.append(identity)
                else:
                    expected_judgment = {
                        "judgment": judgment.get("judgment"),
                        "rationale": judgment.get("rationale"),
                    }
                    if parsed != expected_judgment:
                        errors.append(f"{identity}: parsed judgment differs from observation")
            else:
                obj = extract_json_from_text(content)
                if not isinstance(obj, dict):
                    errors.append(f"{identity}: control response has no JSON object")
                    continue
                if obj.get("option") != option:
                    option_mismatches.append(identity)
                refs = obj.get("evidence_refs")
                if isinstance(refs, list):
                    seen: list[Any] = []
                    for ref in refs:
                        if any(ref == previous for previous in seen):
                            duplicate_refs.append(identity)
                        seen.append(ref)
                        if not isinstance(ref, int) or isinstance(ref, bool) or not 1 <= ref <= len(evidence):
                            unknown_refs.append(identity)
    return {
        "errors": errors,
        "unknown_or_out_of_range_refs": sorted(set(unknown_refs)),
        "duplicate_refs": sorted(set(duplicate_refs)),
        "option_mismatches": sorted(set(option_mismatches)),
        "unexpected_fields": sorted(set(unexpected_fields)),
    }


def evaluate_pair(
    control: dict[str, Any],
    treatment: dict[str, Any],
    labels_payload: dict[str, Any],
    questions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    labels = {str(k): str(v) for k, v in (labels_payload.get("labels") or {}).items()}
    frozen_parent = {
        str(k): str(v)
        for k, v in (labels_payload.get("frozen_online_v2s1_answers") or {}).items()
    }
    parent_correct_qids = tuple(
        map(str, labels_payload.get("frozen_parent_correct_qids") or [])
    )
    truth_derived_parent_correct = tuple(
        qid for qid in DEVELOPMENT_QIDS if labels.get(qid) == frozen_parent.get(qid)
    )
    if (
        labels_payload.get("schema_version") != "e009-development-labels/v1"
        or labels_payload.get("experiment_id") != "E009"
        or set(labels) != set(DEVELOPMENT_QIDS)
        or set(frozen_parent) != set(DEVELOPMENT_QIDS)
        or parent_correct_qids != truth_derived_parent_correct
        or len(parent_correct_qids) != 6
    ):
        raise ValueError("E009 development labels/parent-correct set mismatch")
    control_audit = _raw_binding_audit(control, questions, arm="control")
    treatment_audit = _raw_binding_audit(treatment, questions, arm="treatment")
    rows: list[dict[str, Any]] = []
    retrieval_errors: list[str] = []
    answer_churn: list[str] = []
    control_correct = 0
    treatment_correct = 0
    parent_regressions: list[str] = []
    for qid in DEVELOPMENT_QIDS:
        control_row = control["rows"].get(qid) or {}
        treatment_row = treatment["rows"].get(qid) or {}
        control_answer = str(control_row.get("answer") or "")
        treatment_answer = str(treatment_row.get("answer") or "")
        truth = labels[qid]
        control_ok = control_answer == truth
        treatment_ok = treatment_answer == truth
        control_correct += int(control_ok)
        treatment_correct += int(treatment_ok)
        if control_answer != treatment_answer:
            answer_churn.append(f"{qid}:{control_answer}->{treatment_answer}")
        if qid in parent_correct_qids and not treatment_ok:
            parent_regressions.append(qid)
        if control_row.get("retrieval") != treatment_row.get("retrieval"):
            retrieval_errors.append(f"{qid}: retrieval/evidence differs between arms")
        if control_row.get("route_diagnostics") != treatment_row.get("route_diagnostics"):
            retrieval_errors.append(f"{qid}: route diagnostics differs between arms")
        rows.append(
            {
                "qid": qid,
                "truth": truth,
                "control_answer": control_answer,
                "treatment_answer": treatment_answer,
                "control_correct": control_ok,
                "treatment_correct": treatment_ok,
                "frozen_parent_correct": qid in parent_correct_qids,
            }
        )

    control_manifest = control["manifest"]
    treatment_manifest = treatment["manifest"]
    temporal_errors: list[str] = []
    try:
        control_finished = datetime.fromisoformat(str(control_manifest["finished_at"]))
        treatment_started = datetime.fromisoformat(str(treatment_manifest["started_at"]))
        if control_finished > treatment_started:
            temporal_errors.append("treatment started before control finished")
    except (KeyError, TypeError, ValueError) as exc:
        temporal_errors.append(f"invalid trace time: {exc}")
    authorization = _load_json(TREATMENT_AUTHORIZATION_PATH)
    claim = _load_json(TREATMENT_CLAIM_PATH)
    if claim.get("authorization_sha256") != sha256_file(TREATMENT_AUTHORIZATION_PATH):
        temporal_errors.append("treatment claim authorization hash mismatch")
    if claim.get("control_anchor") != authorization.get("control_anchor"):
        temporal_errors.append("claim/control authorization anchor mismatch")
    if treatment["receipt"].get("control_anchor") != claim.get("control_anchor"):
        temporal_errors.append("treatment receipt/control claim anchor mismatch")
    if treatment["receipt"].get("treatment_claim_sha256") != sha256_file(TREATMENT_CLAIM_PATH):
        temporal_errors.append("treatment receipt claim hash mismatch")

    bundle_errors = [
        *control["errors"],
        *treatment["errors"],
        *control_audit["errors"],
        *treatment_audit["errors"],
        *retrieval_errors,
        *temporal_errors,
    ]
    checks = {
        "control_trace_receipt_schema_pass": not control["errors"],
        "treatment_trace_receipt_schema_pass": not treatment["errors"]
        and not treatment_audit["errors"],
        "treatment_unexpected_evidence_refs_or_extra_fields_zero": not treatment_audit[
            "unexpected_fields"
        ],
        "treatment_accuracy_not_below_fresh_control": treatment_correct >= control_correct,
        "frozen_parent_correct_zero_regression": not parent_regressions,
        "retrieval_evidence_byte_identical": not retrieval_errors,
        "temporal_claim_chain_pass": not temporal_errors,
        "both_arms_exact_52_physical_attempts": (
            int(control["receipt"].get("physical_attempt_count") or 0) == 52
            and int(treatment["receipt"].get("physical_attempt_count") or 0) == 52
        ),
    }
    return {
        "schema_version": "e009-development-evaluation/v1",
        "experiment_id": "E009",
        "pair_id": PAIR_ID,
        "status": "PASS" if all(checks.values()) and not bundle_errors else "FAIL",
        "decision": (
            "DEVELOPMENT_GATE_PASS"
            if all(checks.values()) and not bundle_errors
            else "DEVELOPMENT_NO_GO"
        ),
        "question_count": 13,
        "accuracy": {
            "control_correct": control_correct,
            "treatment_correct": treatment_correct,
            "delta": treatment_correct - control_correct,
        },
        "answer_churn": answer_churn,
        "frozen_parent_correct_regressions": parent_regressions,
        "reference_integrity": {
            "control_unexpected_evidence_refs_or_extra_fields": control_audit[
                "unexpected_fields"
            ],
            "control_option_mismatches": control_audit["option_mismatches"],
            "treatment_unexpected_evidence_refs_or_extra_fields": treatment_audit[
                "unexpected_fields"
            ],
            "treatment_option_mismatches": treatment_audit["option_mismatches"],
        },
        "tokens": {
            "control": int(control["receipt"].get("total_tokens") or 0),
            "treatment": int(treatment["receipt"].get("total_tokens") or 0),
            "delta": int(treatment["receipt"].get("total_tokens") or 0)
            - int(control["receipt"].get("total_tokens") or 0),
        },
        "physical_attempts": {
            "control": int(control["receipt"].get("physical_attempt_count") or 0),
            "treatment": int(treatment["receipt"].get("physical_attempt_count") or 0),
        },
        "served_models": {
            "control": control["receipt"].get("served_models") or [],
            "treatment": treatment["receipt"].get("served_models") or [],
        },
        "checks": checks,
        "bundle_errors": bundle_errors,
        "rows": rows,
        "artifacts": {
            "selection_sha256": sha256_file(SELECTION_PATH),
            "labels_sha256": sha256_file(LABELS_PATH),
            "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
            "control_observations_sha256": sha256_file(
                EXPECTED_OUTPUT_DIRS["control"] / "observations.json"
            ),
            "control_receipt_sha256": sha256_file(
                EXPECTED_OUTPUT_DIRS["control"] / "run_receipt.json"
            ),
            "treatment_observations_sha256": sha256_file(
                EXPECTED_OUTPUT_DIRS["treatment"] / "observations.json"
            ),
            "treatment_receipt_sha256": sha256_file(
                EXPECTED_OUTPUT_DIRS["treatment"] / "run_receipt.json"
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=RESULT_PATH)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError(f"E009 evaluation output must be absent: {args.output}")
    labels = _load_json(LABELS_PATH)
    questions = {str(item["qid"]): item for item in load_all_questions()}
    report = evaluate_pair(
        _load_bundle("control", EXPECTED_OUTPUT_DIRS["control"]),
        _load_bundle("treatment", EXPECTED_OUTPUT_DIRS["treatment"]),
        labels,
        questions,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"E009 development evaluation={report['status']} "
        f"control={report['accuracy']['control_correct']}/13 "
        f"treatment={report['accuracy']['treatment_correct']}/13"
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
