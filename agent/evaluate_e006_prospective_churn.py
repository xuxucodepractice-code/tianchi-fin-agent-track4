"""Validate E006 prospective primary/repeat and compute label-free churn."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.doc_meta import load_doc_meta
from agent.evaluate_e006_paired import call_prompt_binding_errors
from agent.load_questions import load_all_questions
from agent.normalize_answer import normalize_answer
from agent.paths import REPO_ROOT
from agent.reason_qwen import _parse_judgment, extract_json_from_text
from agent.reason_multi_v0_compat import E006_PIPELINE_VERSION
from agent.retrieve import load_chunks
from agent.retrieve_v0_compat import V0_TOP_K, retrieve_multi_v0_compatible
from agent.run_e006_paired_arm import _compact_retrieval, _validate_result
from agent.run_e006_prospective_arm import (
    EXPECTED_OUTPUT_DIRS,
    AUTHORIZATION_PATH,
    CONTROL_REFERENCE_PATH,
    FROZEN_INPUT_SHA256,
    PAIR_ID,
    PRIMARY_CLAIM_PATH,
    PROSPECTIVE_LABELS_PATH,
    PROSPECTIVE_SCORED_RESULT_PATH,
    PROSPECTIVE_SELECTION_PATH,
    PROSPECTIVE_QIDS,
    REPEAT_CLAIM_PATH,
    RUN_FREEZE_PATH,
    SOURCE_SELECTION_PATH,
    OFFLINE_GATE_PATH,
    CHURN_REPORT_PATH,
    output_inventory_errors,
    validate_prospective_trace_contract,
)
from agent.trace_gate import (
    canonical_json_bytes,
    blind_data_guard,
    default_candidate_forbidden_roots,
    default_runtime_read_roots,
    now_iso,
    resolve_recorded_path,
    sha256_file,
    sha256_json,
    validate_trace_directory,
)


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _rows(payload: dict[str, Any], *, attempt: str) -> list[dict[str, Any]]:
    if payload.get("schema_version") != "e006-prospective-observations/v1":
        raise ValueError(f"{attempt}: observations schema mismatch")
    if (
        payload.get("experiment_id") != "E006"
        or payload.get("phase") != "prospective"
        or payload.get("pair_id") != PAIR_ID
        or payload.get("attempt") != attempt
    ):
        raise ValueError(f"{attempt}: experiment/pair/attempt mismatch")
    if payload.get("labels_accessed") is not False:
        raise ValueError(f"{attempt}: label isolation declaration mismatch")
    if payload.get("pipeline_version") != E006_PIPELINE_VERSION:
        raise ValueError(f"{attempt}: pipeline mismatch")
    qids = list(map(str, payload.get("qids") or []))
    if tuple(qids) != PROSPECTIVE_QIDS:
        raise ValueError(f"{attempt}: qids/order differ from frozen holdout")
    rows = payload.get("observations") or []
    row_qids = [str(row.get("qid") or "") for row in rows if isinstance(row, dict)]
    if (
        not isinstance(rows, list)
        or len(rows) != 15
        or len(row_qids) != 15
        or len(set(row_qids)) != 15
        or row_qids != list(PROSPECTIVE_QIDS)
    ):
        raise ValueError(f"{attempt}: observations must contain ordered 15 unique rows")
    if int(payload.get("question_count") or 0) != 15:
        raise ValueError(f"{attempt}: question_count must be 15")
    if int(payload.get("api_call_count") or 0) != 60:
        raise ValueError(f"{attempt}: api_call_count must be 60")
    if payload.get("failures") != []:
        raise ValueError(f"{attempt}: observations contain failures")
    for row in rows:
        errors = _validate_result(row, arm="treatment")
        if errors:
            raise ValueError(f"{attempt}: invalid result: {errors}")
        judgments = row.get("option_judgments") or {}
        expected_inputs = {
            option: {
                "judgment": judgment.get("judgment"),
                "evidence_refs": judgment.get("evidence_refs", []),
                "error": judgment.get("error"),
            }
            for option, judgment in sorted(judgments.items())
        }
        derivation = row.get("answer_derivation") or {}
        if sorted(judgments) != list("ABCD") or sorted(expected_inputs) != list("ABCD"):
            raise ValueError(f"{attempt}:{row.get('qid')}: judgments are not A/B/C/D")
        if (
            derivation.get("method") != "agent.normalize_answer.normalize_answer"
            or derivation.get("answer_format") != "multi"
            or derivation.get("input_judgments") != expected_inputs
            or str(derivation.get("output_answer") or "")
            != str(row.get("answer") or "")
        ):
            raise ValueError(f"{attempt}:{row.get('qid')}: derivation binding mismatch")
        if str(
            normalize_answer("multi", judgments, row.get("options") or {}).get("answer")
            or ""
        ) != str(row.get("answer") or ""):
            raise ValueError(f"{attempt}:{row.get('qid')}: normalizer replay mismatch")
    return rows


def raw_judgment_binding_errors(
    calls: list[dict[str, Any]],
    rows: dict[str, dict[str, Any]],
    *,
    attempt: str,
) -> list[str]:
    """Replay the production parser and bind all parsed fields to observations."""
    errors: list[str] = []
    for call in calls:
        context = call.get("context") or {}
        qid = str(context.get("qid") or "")
        option = str(context.get("option_key") or "")
        prefix = f"{attempt}:{qid}:{option}"
        row = rows.get(qid) or {}
        judgment = (row.get("option_judgments") or {}).get(option) or {}
        content = str(call.get("response_content") or "")
        raw = extract_json_from_text(content)
        if not isinstance(raw, dict):
            errors.append(f"{prefix}: response is not a JSON object")
            continue
        try:
            direct = json.loads(content)
        except json.JSONDecodeError:
            direct = None
        if not isinstance(direct, dict):
            errors.append(f"{prefix}: response is not strict standalone JSON")
        if str(raw.get("option") or "") != option:
            errors.append(f"{prefix}: raw option identity mismatch")
        parsed, parse_error = _parse_judgment(content, option)
        expected_parsed = {
            "judgment": judgment.get("judgment"),
            "rationale": judgment.get("rationale", ""),
            "evidence_refs": judgment.get("evidence_refs", []),
        }
        if parsed != expected_parsed or parse_error != judgment.get("error"):
            errors.append(f"{prefix}: parsed raw judgment differs from observation")
        evidence = ((row.get("retrieval") or {}).get(option) or {}).get(
            "evidence"
        ) or []
        refs = parsed.get("evidence_refs") or []
        if any(
            not isinstance(ref, int)
            or isinstance(ref, bool)
            or ref < 1
            or ref > len(evidence)
            for ref in refs
        ):
            errors.append(f"{prefix}: evidence_refs outside rendered evidence range")
    return errors


def load_bundle(
    observations_path: Path, receipt_path: Path, *, attempt: str
) -> dict[str, Any]:
    observations_path = observations_path.resolve()
    receipt_path = receipt_path.resolve()
    if observations_path != (EXPECTED_OUTPUT_DIRS[attempt] / "observations.json").resolve():
        raise ValueError(f"{attempt}: observations path is outside registered slot")
    if receipt_path != (EXPECTED_OUTPUT_DIRS[attempt] / "run_receipt.json").resolve():
        raise ValueError(f"{attempt}: receipt path is outside registered slot")
    observations = _load(observations_path)
    receipt = _load(receipt_path)
    errors: list[str] = []
    try:
        rows = _rows(observations, attempt=attempt)
    except ValueError as exc:
        errors.append(str(exc))
        rows = observations.get("observations") or []
    trace_meta = observations.get("agent_trace") or {}
    trace_dir = resolve_recorded_path(str(trace_meta.get("trace_dir") or ""))
    report = validate_trace_directory(
        trace_dir,
        require_candidate_eligible=False,
        require_current_code_match=True,
    )
    errors.extend(map(str, report.get("errors") or []))
    errors.extend(
        validate_prospective_trace_contract(
            report,
            trace_dir=trace_dir,
            attempt=attempt,
            output_dir=observations_path.parent,
        )
    )
    manifest = report.get("manifest") or {}
    config = manifest.get("config") or {}
    run_freeze = _load(RUN_FREEZE_PATH)
    attempt_nonce = str(
        (run_freeze.get("attempt_nonces") or {}).get(attempt) or ""
    )
    primary_claim_sha256 = sha256_file(PRIMARY_CLAIM_PATH)
    repeat_claim_sha256 = (
        sha256_file(REPEAT_CLAIM_PATH) if attempt == "repeat" else None
    )
    expected_primary_anchor = None if attempt == "primary" else receipt.get(
        "primary_anchor"
    )
    expected_receipt = {
        "schema_version": "e006-prospective-run-receipt/v1",
        "experiment_id": "E006",
        "phase": "prospective",
        "pair_id": PAIR_ID,
        "attempt": attempt,
        "attempt_nonce": attempt_nonce,
        "status": "PASS",
        "primary_claim_sha256": primary_claim_sha256,
        "primary_anchor": expected_primary_anchor,
        "repeat_claim_sha256": repeat_claim_sha256,
        "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
        "selection_sha256": FROZEN_INPUT_SHA256["selection"],
        "observations_sha256": sha256_file(observations_path),
        "trace_run_id": str(trace_meta.get("trace_run_id") or ""),
        "trace_manifest_sha256": sha256_file(trace_dir / "trace_manifest.json"),
        "code_sha256": str((manifest.get("code") or {}).get("sha256") or ""),
        "config_sha256": str(manifest.get("config_sha256") or ""),
        "model_sha256": str(manifest.get("model_sha256") or ""),
        "input_artifacts_sha256": sha256_json(config.get("input_artifacts") or {}),
        "pipeline_version": E006_PIPELINE_VERSION,
        "call_count": 60,
        "logical_call_count": 60,
        "derivation_count": 15,
    }
    for key, expected in expected_receipt.items():
        if receipt.get(key) != expected:
            errors.append(f"{attempt}: receipt {key} mismatch")
    if receipt.get("errors") != []:
        errors.append(f"{attempt}: receipt contains errors")
    trace_run_id = str(manifest.get("trace_run_id") or "")
    if str(trace_meta.get("trace_run_id") or "") != trace_run_id:
        errors.append(f"{attempt}: observations trace_run_id differs from manifest")
    if str(receipt.get("trace_run_id") or "") != trace_run_id:
        errors.append(f"{attempt}: receipt trace_run_id differs from manifest")
    expected_identity = {
        "attempt_nonce": attempt_nonce,
        "primary_claim_sha256": primary_claim_sha256,
        "primary_anchor": expected_primary_anchor,
        "repeat_claim_sha256": repeat_claim_sha256,
        "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
    }
    for label, source in (
        ("observations", observations),
        ("trace config", config),
        ("receipt", receipt),
    ):
        for key, expected in expected_identity.items():
            if source.get(key) != expected:
                errors.append(f"{attempt}: {label} {key} mismatch")
    errors.extend(output_inventory_errors(observations_path.parent, attempt=attempt))
    try:
        derivations = [
            json.loads(line)
            for line in (trace_dir / "derivations.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        calls = [
            json.loads(line)
            for line in (trace_dir / "calls.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        physical_attempt_count = sum(
            len(call.get("attempts") or []) for call in calls
        )
        if int(receipt.get("physical_attempt_count") or 0) != physical_attempt_count:
            errors.append(f"{attempt}: physical attempt count mismatch")
        if int(receipt.get("max_retries_per_logical_call") or -1) != 2:
            errors.append(f"{attempt}: receipt retry policy mismatch")
        if len(calls) != 60:
            errors.append(f"{attempt}: logical call count differs from 60")
        if not 60 <= physical_attempt_count <= 180:
            errors.append(f"{attempt}: physical attempt total outside 60..180")
        for call in calls:
            qid = str((call.get("context") or {}).get("qid") or "")
            option = str((call.get("context") or {}).get("option_key") or "")
            call_attempts = call.get("attempts") or []
            if not isinstance(call_attempts, list) or not 1 <= len(call_attempts) <= 3:
                errors.append(f"{attempt}:{qid}:{option}: attempts outside 1..3")
                continue
            if int(call.get("retry_count") or 0) != len(call_attempts) - 1:
                errors.append(f"{attempt}:{qid}:{option}: retry count mismatch")
            for index, physical in enumerate(call_attempts, start=1):
                expected_status = "success" if index == len(call_attempts) else "error"
                if (
                    not isinstance(physical, dict)
                    or int(physical.get("attempt") or 0) != index
                    or physical.get("status") != expected_status
                ):
                    errors.append(
                        f"{attempt}:{qid}:{option}: invalid physical attempt sequence"
                    )
                    break
        if len(rows) != len(derivations):
            errors.append(f"{attempt}: observations/derivations length mismatch")
        else:
            for row, derivation in zip(rows, derivations, strict=True):
                qid = str(row.get("qid") or "")
                if (
                    str(derivation.get("qid") or "") != qid
                    or str(derivation.get("answer") or "")
                    != str(row.get("answer") or "")
                    or derivation.get("answer_derivation")
                    != row.get("answer_derivation")
                    or derivation.get("retrieval_sha256")
                    != sha256_json(row.get("retrieval") or {})
                ):
                    errors.append(f"{attempt}:{qid}: observation/Trace binding mismatch")
                for token_key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    if int(derivation.get(token_key) or 0) != int(
                        row.get(token_key) or 0
                    ):
                        errors.append(f"{attempt}:{qid}: {token_key} mismatch")
        total = sum(int(row.get("total_tokens") or 0) for row in rows)
        if int(observations.get("total_tokens") or 0) != total:
            errors.append(f"{attempt}: observations token total mismatch")
        if int(receipt.get("total_tokens") or 0) != total:
            errors.append(f"{attempt}: receipt token total mismatch")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"{attempt}: unable to correlate Trace: {exc}")
        calls = []
        physical_attempt_count = 0
    served_models = sorted(
        {
            str(call.get("response_model") or "")
            for call in calls
            if str(call.get("response_model") or "")
        }
    )
    if len(served_models) != 1 or not served_models[0].startswith("qwen-plus"):
        errors.append(f"{attempt}: expected one exact qwen-plus served model")
    return {
        "observations": observations,
        "rows": rows,
        "receipt": receipt,
        "manifest": manifest,
        "trace_dir": trace_dir,
        "calls": calls,
        "physical_attempt_count": physical_attempt_count,
        "served_models": served_models,
        "artifact_hashes": {
            "observations_sha256": sha256_file(observations_path),
            "receipt_sha256": sha256_file(receipt_path),
            "trace_manifest_sha256": sha256_file(
                trace_dir / "trace_manifest.json"
            ),
        },
        "errors": errors,
    }


def _semantic_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in config.items()
        if key
        not in {
            "attempt",
            "attempt_nonce",
            "output_dir",
            "primary_anchor",
            "repeat_claim_sha256",
        }
    }


def replay_errors(bundle: dict[str, Any], *, attempt: str) -> list[str]:
    errors: list[str] = []
    questions = {str(item["qid"]): item for item in load_all_questions()}
    chunks = load_chunks()
    doc_meta = load_doc_meta()
    rows = {str(row["qid"]): row for row in bundle["rows"]}
    for qid in PROSPECTIVE_QIDS:
        diagnostics: dict[str, Any] = {}
        expected = retrieve_multi_v0_compatible(
            questions[qid],
            chunks,
            enable_option_document_route=True,
            top_k=V0_TOP_K,
            doc_meta=doc_meta,
            diagnostics_out=diagnostics,
        )
        if rows[qid].get("retrieval") != _compact_retrieval(expected):
            errors.append(f"{attempt}:{qid}: retrieval differs from replay")
        if rows[qid].get("route_diagnostics") != diagnostics:
            errors.append(f"{attempt}:{qid}: route diagnostics differ from replay")
    errors.extend(
        call_prompt_binding_errors(
            bundle["calls"],
            rows,
            questions,
            arm="treatment",
            qids=PROSPECTIVE_QIDS,
        )
    )
    errors.extend(
        raw_judgment_binding_errors(
            bundle["calls"], rows, attempt=attempt
        )
    )
    return errors


def pair_anchor_errors(
    primary: dict[str, Any], repeat: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    primary_obs_path = EXPECTED_OUTPUT_DIRS["primary"] / "observations.json"
    primary_receipt_path = EXPECTED_OUTPUT_DIRS["primary"] / "run_receipt.json"
    expected_anchor = {
        "pair_id": PAIR_ID,
        "primary_claim_sha256": sha256_file(PRIMARY_CLAIM_PATH),
        "primary_trace_run_id": str(
            (primary["observations"].get("agent_trace") or {}).get("trace_run_id") or ""
        ),
        "primary_observations_sha256": sha256_file(primary_obs_path),
        "primary_trace_manifest_sha256": sha256_file(
            primary["trace_dir"] / "trace_manifest.json"
        ),
        "primary_receipt_sha256": sha256_file(primary_receipt_path),
    }
    primary_config = primary["manifest"].get("config") or {}
    repeat_config = repeat["manifest"].get("config") or {}
    if primary_config.get("primary_anchor") is not None or primary_config.get(
        "repeat_claim_sha256"
    ) is not None:
        errors.append("primary contains repeat anchor/claim")
    for label, source in (
        ("primary observations", primary["observations"]),
        ("primary receipt", primary["receipt"]),
    ):
        if source.get("primary_anchor") is not None or source.get(
            "repeat_claim_sha256"
        ) is not None:
            errors.append(f"{label}: contains repeat anchor/claim")
    if not PRIMARY_CLAIM_PATH.is_file():
        errors.append("primary claim missing")
    else:
        run_freeze = _load(RUN_FREEZE_PATH)
        primary_claim = _load(PRIMARY_CLAIM_PATH)
        if (
            primary_claim.get("schema_version")
            != "e006-prospective-primary-claim/v1"
            or primary_claim.get("experiment_id") != "E006"
            or primary_claim.get("pair_id") != PAIR_ID
            or primary_claim.get("attempt") != "primary"
            or primary_claim.get("status") != "PRIMARY_ATTEMPT_CLAIMED"
            or primary_claim.get("attempt_nonce")
            != (run_freeze.get("attempt_nonces") or {}).get("primary")
            or primary_claim.get("run_freeze_sha256")
            != sha256_file(RUN_FREEZE_PATH)
            or primary_claim.get("agent_code_snapshot_sha256")
            != primary["receipt"].get("code_sha256")
        ):
            errors.append("primary claim semantics mismatch")
    for label, value in (
        ("repeat config", repeat_config.get("primary_anchor")),
        ("repeat observations", repeat["observations"].get("primary_anchor")),
        ("repeat receipt", repeat["receipt"].get("primary_anchor")),
    ):
        if value != expected_anchor:
            errors.append(f"{label}: primary anchor mismatch")
    if not REPEAT_CLAIM_PATH.is_file():
        return [*errors, "repeat claim missing"]
    claim = _load(REPEAT_CLAIM_PATH)
    claim_sha = sha256_file(REPEAT_CLAIM_PATH)
    if (
        claim.get("schema_version") != "e006-prospective-repeat-claim/v1"
        or claim.get("experiment_id") != "E006"
        or claim.get("pair_id") != PAIR_ID
        or claim.get("attempt") != "repeat"
        or claim.get("status") != "REPEAT_ATTEMPT_CLAIMED"
        or claim.get("attempt_nonce")
        != (_load(RUN_FREEZE_PATH).get("attempt_nonces") or {}).get("repeat")
        or claim.get("run_freeze_sha256") != sha256_file(RUN_FREEZE_PATH)
        or claim.get("primary_claim_sha256") != sha256_file(PRIMARY_CLAIM_PATH)
        or claim.get("primary_anchor") != expected_anchor
    ):
        errors.append("repeat claim semantics/anchor mismatch")
    for label, value in (
        ("repeat config", repeat_config.get("repeat_claim_sha256")),
        ("repeat observations", repeat["observations"].get("repeat_claim_sha256")),
        ("repeat receipt", repeat["receipt"].get("repeat_claim_sha256")),
    ):
        if value != claim_sha:
            errors.append(f"{label}: repeat claim hash mismatch")
    try:
        freeze_created = datetime.fromisoformat(str(_load(RUN_FREEZE_PATH)["created_at"]))
        primary_claimed = datetime.fromisoformat(
            str(_load(PRIMARY_CLAIM_PATH)["claimed_at"])
        )
        primary_started = datetime.fromisoformat(str(primary["manifest"]["started_at"]))
        primary_finished = datetime.fromisoformat(str(primary["manifest"]["finished_at"]))
        claimed_at = datetime.fromisoformat(str(claim["claimed_at"]))
        repeat_started = datetime.fromisoformat(str(repeat["manifest"]["started_at"]))
        if not freeze_created <= primary_claimed <= primary_started:
            errors.append("primary claim time is outside freeze/primary boundary")
        if not primary_finished <= claimed_at <= repeat_started:
            errors.append("repeat claim time is outside pair boundary")
    except (KeyError, TypeError, ValueError):
        errors.append("unable to validate repeat claim time")
    return errors


def evaluate_churn(
    primary: dict[str, Any],
    repeat: dict[str, Any],
    *,
    bundle_errors: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    primary_rows = {str(row["qid"]): row for row in primary["rows"]}
    repeat_rows = {str(row["qid"]): row for row in repeat["rows"]}
    answer_churn: list[str] = []
    verdict_churn: list[str] = []
    retrieval_drift: list[str] = []
    for qid in PROSPECTIVE_QIDS:
        if primary_rows[qid]["answer"] != repeat_rows[qid]["answer"]:
            answer_churn.append(
                f"{qid}:{primary_rows[qid]['answer']}->{repeat_rows[qid]['answer']}"
            )
        for option in "ABCD":
            p_verdict = primary_rows[qid]["option_judgments"][option]["judgment"]
            r_verdict = repeat_rows[qid]["option_judgments"][option]["judgment"]
            if p_verdict != r_verdict:
                verdict_churn.append(f"{qid}:{option}:{p_verdict}->{r_verdict}")
            if canonical_json_bytes(
                primary_rows[qid]["retrieval"][option]["evidence"]
            ) != canonical_json_bytes(
                repeat_rows[qid]["retrieval"][option]["evidence"]
            ):
                retrieval_drift.append(f"{qid}:{option}")
    p_manifest = primary["manifest"]
    r_manifest = repeat["manifest"]
    p_config = p_manifest.get("config") or {}
    r_config = r_manifest.get("config") or {}
    try:
        p_start = datetime.fromisoformat(str(p_manifest["started_at"]))
        p_finish = datetime.fromisoformat(str(p_manifest["finished_at"]))
        r_start = datetime.fromisoformat(str(r_manifest["started_at"]))
        r_finish = datetime.fromisoformat(str(r_manifest["finished_at"]))
        time_order = p_start <= p_finish <= r_start <= r_finish
        elapsed = (r_finish - p_start).total_seconds()
        within_two_hours = 0 <= elapsed <= 7200
    except (KeyError, TypeError, ValueError):
        time_order = False
        elapsed = None
        within_two_hours = False
    checks = {
        "bundle_integrity": not bundle_errors,
        "primary_is_registered_scoring_arm": bool(
            primary["receipt"].get("primary_claim_sha256")
        )
        and primary["receipt"].get("primary_anchor") is None
        and primary["receipt"].get("repeat_claim_sha256") is None
        and primary["receipt"].get("primary_claim_sha256")
        == repeat["receipt"].get("primary_claim_sha256"),
        "same_code": primary["receipt"].get("code_sha256")
        == repeat["receipt"].get("code_sha256")
        and bool(primary["receipt"].get("code_sha256")),
        "same_requested_model": primary["receipt"].get("model_sha256")
        == repeat["receipt"].get("model_sha256")
        and bool(primary["receipt"].get("model_sha256")),
        "same_exact_served_model": len(primary.get("served_models") or []) == 1
        and primary.get("served_models") == repeat.get("served_models"),
        "same_inputs": primary["receipt"].get("input_artifacts_sha256")
        == repeat["receipt"].get("input_artifacts_sha256")
        and bool(primary["receipt"].get("input_artifacts_sha256")),
        "same_semantic_config_except_attempt_anchor_output": _semantic_config(p_config)
        == _semantic_config(r_config),
        "retrieval_is_byte_identical": not retrieval_drift,
        "primary_then_repeat_time_order": time_order,
        "pair_completed_within_two_hours": within_two_hours,
    }
    p_tokens = int(primary["observations"].get("total_tokens") or 0)
    r_tokens = int(repeat["observations"].get("total_tokens") or 0)
    return {
        "schema_version": "e006-prospective-churn/v1",
        "experiment_id": "E006",
        "pair_id": PAIR_ID,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "decision": (
            "READY_FOR_BLIND_LABELING"
            if all(checks.values())
            else "PROSPECTIVE_TRACE_NO_GO"
        ),
        "scoring_arm": "primary",
        "repeat_non_scoring": True,
        "question_count": 15,
        "primary_repeat_answer_churn_C": len(answer_churn),
        "answer_churn": answer_churn,
        "option_verdict_churn_count": len(verdict_churn),
        "option_verdict_churn": verdict_churn,
        "retrieval_drift": retrieval_drift,
        "answers": {
            qid: {
                "primary": str(primary_rows[qid]["answer"]),
                "repeat": str(repeat_rows[qid]["answer"]),
            }
            for qid in PROSPECTIVE_QIDS
        },
        "served_models": {
            "primary": list(primary.get("served_models") or []),
            "repeat": list(repeat.get("served_models") or []),
        },
        "artifact_bindings": {
            "run_freeze_sha256": str(
                primary["receipt"].get("run_freeze_sha256") or ""
            ),
            "source_selection_sha256": FROZEN_INPUT_SHA256["source_selection"],
            "trace_selection_sha256": FROZEN_INPUT_SHA256["selection"],
            "authorization_sha256": FROZEN_INPUT_SHA256["authorization"],
            "primary_claim_sha256": str(
                primary["receipt"].get("primary_claim_sha256") or ""
            ),
            "repeat_claim_sha256": str(
                repeat["receipt"].get("repeat_claim_sha256") or ""
            ),
            "primary": dict(primary.get("artifact_hashes") or {}),
            "repeat": dict(repeat.get("artifact_hashes") or {}),
            "primary_trace_run_id": str(
                (primary["observations"].get("agent_trace") or {}).get(
                    "trace_run_id"
                )
                or ""
            ),
        },
        "tokens": {"primary": p_tokens, "repeat": r_tokens, "delta": r_tokens - p_tokens},
        "http_attempts": {
            "primary_logical_calls": 60,
            "primary_physical_attempts": primary.get("physical_attempt_count", 0),
            "repeat_logical_calls": 60,
            "repeat_physical_attempts": repeat.get("physical_attempt_count", 0),
            "max_retries_per_logical_call": 2,
        },
        "pair_elapsed_seconds": elapsed,
        "created_at": now_iso(),
        "bundle_errors": list(bundle_errors),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if CHURN_REPORT_PATH.exists():
        raise ValueError(f"fixed churn report already exists: {CHURN_REPORT_PATH}")
    if PROSPECTIVE_LABELS_PATH.exists() or PROSPECTIVE_SCORED_RESULT_PATH.exists():
        raise ValueError("labels/scored result exist before label-free churn freeze")
    allowed_reads = (
        Path(__file__).resolve().parent,
        (REPO_ROOT / "public_dataset_upload" / "questions" / "group_a").resolve(),
        (REPO_ROOT / "processed_data" / "chunks.jsonl").resolve(),
        (REPO_ROOT / "processed_data" / "doc_meta.json").resolve(),
        PROSPECTIVE_SELECTION_PATH.resolve(),
        SOURCE_SELECTION_PATH.resolve(),
        AUTHORIZATION_PATH.resolve(),
        RUN_FREEZE_PATH.resolve(),
        CONTROL_REFERENCE_PATH.resolve(),
        OFFLINE_GATE_PATH.resolve(),
        PRIMARY_CLAIM_PATH.resolve(),
        REPEAT_CLAIM_PATH.resolve(),
        EXPECTED_OUTPUT_DIRS["primary"].resolve(),
        EXPECTED_OUTPUT_DIRS["repeat"].resolve(),
        *default_runtime_read_roots(),
    )
    try:
        with blind_data_guard(
            default_candidate_forbidden_roots(),
            allowed_read_roots=allowed_reads,
            allowed_write_roots=(CHURN_REPORT_PATH.resolve(),),
            block_subprocess=True,
        ):
            primary = load_bundle(
                EXPECTED_OUTPUT_DIRS["primary"] / "observations.json",
                EXPECTED_OUTPUT_DIRS["primary"] / "run_receipt.json",
                attempt="primary",
            )
            repeat = load_bundle(
                EXPECTED_OUTPUT_DIRS["repeat"] / "observations.json",
                EXPECTED_OUTPUT_DIRS["repeat"] / "run_receipt.json",
                attempt="repeat",
            )
            extra_errors = [
                *primary["errors"],
                *repeat["errors"],
                *replay_errors(primary, attempt="primary"),
                *replay_errors(repeat, attempt="repeat"),
                *pair_anchor_errors(primary, repeat),
            ]
            report = evaluate_churn(primary, repeat, bundle_errors=extra_errors)
            rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            with CHURN_REPORT_PATH.open("x", encoding="utf-8") as handle:
                handle.write(rendered)
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": "e006-prospective-churn/v1",
            "experiment_id": "E006",
            "pair_id": PAIR_ID,
            "status": "FAIL",
            "decision": "PROSPECTIVE_TRACE_NO_GO",
            "scoring_arm": "primary",
            "repeat_non_scoring": True,
            "created_at": now_iso(),
            "errors": [str(exc)],
        }
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        with CHURN_REPORT_PATH.open("x", encoding="utf-8") as handle:
            handle.write(rendered)
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
