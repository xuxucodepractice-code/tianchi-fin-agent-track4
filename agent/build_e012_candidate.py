"""Validate E012 full expansion and freeze a three-file candidate bundle."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from agent.load_questions import load_all_questions
from agent.merge_submission import merge_submission_bundles
from agent.output_writer import write_answer_csv, write_evidence_json, write_run_manifest
from agent.paths import REPO_ROOT, bundle_paths
from agent.run_e012_full_multi import (
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
    RERUN_BUNDLE_DIR,
    REQUESTED_MODEL,
    RUN_FREEZE_PATH,
    RUN_ID,
    SELECTION_PATH,
    _load_json,
    _official_multi_qids,
    load_and_verify_run_freeze,
    output_inventory_errors,
    validate_full_multi_trace_contract,
)
from agent.trace_gate import (
    display_path,
    now_iso,
    resolve_recorded_path,
    sha256_file,
    validate_trace_directory,
)
from agent.validate_submission import validate_submission_files

PARENT_DIR = Path(
    "/Users/xuzijian/Desktop/Agent Competition/outputs/candidates/v2s1_tf_only"
)
PARENT_HASHES = {
    "answer_csv": "5e082b6fe7824ee326ff1d0c2aa209b3d62115860125e25ba0107f93a4a90c69",
    "evidence_json": "f19091ec079a9162d2d174f00427c4969b5396826c47678b0804606f075f5614",
    "run_manifest_json": "1f160f367d559e565d063546febd68ed2c9ce3cea05853a0f734551bf3997b87",
}
PARENT_VERSION = "v2s1"
PARENT_SCORE = 65.0912
PROJECTED_CORRECT = 78.66666666666667
TOKEN_BUDGET = 5_000_000


def _bundle_hashes(directory: Path) -> dict[str, str]:
    answer, evidence, manifest = bundle_paths(directory)
    return {
        "answer_csv": sha256_file(answer),
        "evidence_json": sha256_file(evidence),
        "run_manifest_json": sha256_file(manifest),
    }


def _read_answer_rows(path: Path) -> tuple[list[str], dict[str, dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or rows[0].get("qid") != "summary":
        raise ValueError(f"answer.csv missing summary: {path}")
    order = [str(row.get("qid") or "") for row in rows[1:]]
    if len(order) != len(set(order)) or any(not qid for qid in order):
        raise ValueError(f"invalid answer qids: {path}")
    return order, {str(row["qid"]): row for row in rows[1:]}


def _read_evidence(path: Path) -> tuple[list[str], dict[str, dict[str, Any]]]:
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise ValueError(f"invalid evidence.json: {path}")
    order = [str(record.get("qid") or "") for record in records]
    if len(order) != len(set(order)) or any(not qid for qid in order):
        raise ValueError(f"invalid evidence qids: {path}")
    return order, {str(record["qid"]): record for record in records}


def _verify_parent() -> None:
    for path in bundle_paths(PARENT_DIR):
        if not path.is_file():
            raise FileNotFoundError(f"frozen v2s1 parent missing: {path}")
    actual = _bundle_hashes(PARENT_DIR)
    if actual != PARENT_HASHES:
        raise ValueError(f"frozen v2s1 parent hash mismatch: {actual}")
    report = validate_submission_files(*bundle_paths(PARENT_DIR))
    if not report["ok"] or report["question_count"] != 100 or report["total_tokens"] != 1_168_763:
        raise ValueError(f"frozen v2s1 parent validation mismatch: {report}")


def _verify_claim(run_freeze: dict[str, Any]) -> str:
    claim = _load_json(CLAIM_PATH)
    if (
        claim.get("schema_version") != "e012-full-multi-claim/v1"
        or claim.get("experiment_id") != EXPERIMENT_ID
        or claim.get("run_id") != RUN_ID
        or claim.get("attempt_nonce") != run_freeze.get("attempt_nonce")
        or claim.get("status") != "FULL_MULTI_ATTEMPT_CLAIMED"
        or claim.get("run_freeze_sha256") != sha256_file(RUN_FREEZE_PATH)
        or not str(claim.get("claimed_at") or "")
    ):
        raise ValueError("E012 full Multi claim mismatch")
    return sha256_file(CLAIM_PATH)


def _verify_full_run() -> tuple[dict[str, Any], dict[str, Any], Path, dict[str, Any]]:
    run_freeze, _ = load_and_verify_run_freeze()
    claim_sha256 = _verify_claim(run_freeze)
    inventory_errors = output_inventory_errors(OUTPUT_DIR)
    if inventory_errors:
        raise ValueError(f"E012 output inventory invalid: {inventory_errors}")
    observations_path = OUTPUT_DIR / "observations.json"
    receipt_path = OUTPUT_DIR / "run_receipt.json"
    observations = _load_json(observations_path)
    receipt = _load_json(receipt_path)
    trace_dir = resolve_recorded_path(
        str((observations.get("agent_trace") or {}).get("trace_dir") or "")
    )
    trace_report = validate_trace_directory(
        trace_dir, require_candidate_eligible=False, require_current_code_match=True,
    )
    strict_errors = validate_full_multi_trace_contract(
        trace_report, trace_dir=trace_dir, output_dir=OUTPUT_DIR,
    )
    if not trace_report.get("ok") or strict_errors:
        raise ValueError(
            f"E012 trace gate failed: {[*trace_report.get('errors', []), *strict_errors]}"
        )
    expected_qids = list(_official_multi_qids())
    rows = observations.get("observations") or []
    if (
        observations.get("schema_version") != "e012-full-multi-observations/v1"
        or observations.get("experiment_id") != EXPERIMENT_ID
        or observations.get("run_id") != RUN_ID
        or observations.get("claim_sha256") != claim_sha256
        or observations.get("selection_sha256") != FROZEN_INPUT_SHA256["selection"]
        or observations.get("labels_accessed") is not False
        or observations.get("failures") != []
        or [str(row.get("qid") or "") for row in rows] != expected_qids
        or int(observations.get("question_count") or 0) != QUESTION_COUNT
        or int(observations.get("api_call_count") or 0) != LOGICAL_CALL_COUNT
    ):
        raise ValueError("E012 observations mismatch")
    expected_receipt = {
        "status": "PASS",
        "experiment_id": EXPERIMENT_ID,
        "phase": "full_multi_expansion",
        "run_id": RUN_ID,
        "claim_sha256": claim_sha256,
        "selection_sha256": FROZEN_INPUT_SHA256["selection"],
        "observations_sha256": sha256_file(observations_path),
        "trace_manifest_sha256": sha256_file(trace_dir / "trace_manifest.json"),
        "pipeline_version": PIPELINE_VERSION,
        "served_models": ["qwen-plus"],
        "call_count": LOGICAL_CALL_COUNT,
        "logical_call_count": LOGICAL_CALL_COUNT,
        "physical_attempt_count": LOGICAL_CALL_COUNT,
        "max_retries_per_logical_call": 0,
        "derivation_count": QUESTION_COUNT,
        "errors": [],
    }
    mismatches = {
        key: (receipt.get(key), value)
        for key, value in expected_receipt.items()
        if receipt.get(key) != value
    }
    if mismatches:
        raise ValueError(f"E012 receipt mismatch: {mismatches}")
    if (
        int(receipt.get("prompt_tokens") or 0)
        + int(receipt.get("completion_tokens") or 0)
        != int(receipt.get("total_tokens") or 0)
        or int(receipt.get("total_tokens") or 0) <= 0
    ):
        raise ValueError("E012 receipt token arithmetic mismatch")
    official = {str(item["qid"]): item for item in load_all_questions()}
    for row in rows:
        qid = str(row.get("qid") or "")
        question = official[qid]
        if any(row.get(field) != question.get(field) for field in (
            "domain", "question", "options", "answer_format", "doc_ids",
        )):
            raise ValueError(f"E012 observation question metadata mismatch: {qid}")
        if (
            row.get("answer_format") != "multi"
            or row.get("mode") != "qwen"
            or row.get("model") != REQUESTED_MODEL
            or row.get("pipeline_version") != PIPELINE_VERSION
            or row.get("experiment_id") != EXPERIMENT_ID
            or int(row.get("prompt_tokens") or 0)
            + int(row.get("completion_tokens") or 0)
            != int(row.get("total_tokens") or 0)
        ):
            raise ValueError(f"E012 observation identity/token mismatch: {qid}")
    return observations, receipt, trace_dir, trace_report


def _write_rerun_bundle(
    observations: dict[str, Any], receipt: dict[str, Any], trace_dir: Path
) -> None:
    RERUN_BUNDLE_DIR.mkdir(parents=True, exist_ok=False)
    results: list[dict[str, Any]] = []
    trace_run_id = str((observations.get("agent_trace") or {}).get("trace_run_id") or "")
    for source in observations["observations"]:
        record = dict(source)
        record["evidence"] = []
        record["source_kind"] = "fresh"
        record["source_pipeline_version"] = PIPELINE_VERSION
        record["source_run_id"] = trace_run_id
        results.append(record)
    write_answer_csv(results, RERUN_BUNDLE_DIR / "answer.csv")
    write_evidence_json(results, RERUN_BUNDLE_DIR / "evidence.json")
    prompt = sum(int(row["prompt_tokens"]) for row in results)
    completion = sum(int(row["completion_tokens"]) for row in results)
    total = sum(int(row["total_tokens"]) for row in results)
    manifest = {
        "run_started_at": str((json.loads((trace_dir / "trace_manifest.json").read_text(encoding="utf-8"))).get("started_at") or ""),
        "run_finished_at": str(observations.get("completed_at") or ""),
        "run_id": trace_run_id,
        "mode": "qwen",
        "model": REQUESTED_MODEL,
        "pipeline_version": PIPELINE_VERSION,
        "submission_scope": "rerun_subset",
        "qid": None,
        "qids": list(_official_multi_qids()),
        "requested_scope": "e012_full_multi_65",
        "success_count": QUESTION_COUNT,
        "failure_count": 0,
        "failures": [],
        "low_confidence_count": sum(bool(row.get("low_confidence")) for row in results),
        "low_confidence_qids": [str(row["qid"]) for row in results if row.get("low_confidence")],
        "total_prompt_tokens": prompt,
        "total_completion_tokens": completion,
        "total_tokens": total,
        "average_total_tokens": round(total / QUESTION_COUNT, 2),
        "experiment_id": EXPERIMENT_ID,
        "api_calls": LOGICAL_CALL_COUNT,
        "physical_attempts": LOGICAL_CALL_COUNT,
        "max_retries": 0,
        "trace_run_id": trace_run_id,
        "trace_manifest_sha256": sha256_file(trace_dir / "trace_manifest.json"),
        "run_receipt_sha256": sha256_file(OUTPUT_DIR / "run_receipt.json"),
        "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
    }
    write_run_manifest(manifest, RERUN_BUNDLE_DIR / "run_manifest.json")
    report = validate_submission_files(*bundle_paths(RERUN_BUNDLE_DIR))
    if not report["ok"] or report["question_count"] != QUESTION_COUNT or report["total_tokens"] != int(receipt["total_tokens"]):
        raise ValueError(f"E012 rerun bundle validation failed: {report}")


def _augment_candidate_manifest(trace_dir: Path) -> None:
    manifest_path = CANDIDATE_DIR / "run_manifest.json"
    manifest = _load_json(manifest_path)
    official_qids = [str(item["qid"]) for item in load_all_questions()]
    multi_qids = list(_official_multi_qids())
    inherited = [qid for qid in official_qids if qid not in set(multi_qids)]
    manifest["agent_trace_gate"] = {
        "status": "PASS",
        "trace_run_id": str((_load_json(OUTPUT_DIR / "observations.json").get("agent_trace") or {}).get("trace_run_id") or ""),
        "trace_manifest_sha256": sha256_file(trace_dir / "trace_manifest.json"),
        "run_receipt_sha256": sha256_file(OUTPUT_DIR / "run_receipt.json"),
        "fresh_traced_qids": multi_qids,
        "legacy_inherited_qids": inherited,
        "served_models": ["qwen-plus"],
        "logical_calls": LOGICAL_CALL_COUNT,
        "physical_attempts": LOGICAL_CALL_COUNT,
        "max_retries": 0,
    }
    manifest["prospective_gate"] = {
        "experiment_id": "E011",
        "scored_result_sha256": FROZEN_INPUT_SHA256["e011_scored_result"],
        "N": 2,
        "M": 0,
        "C": 0,
        "projected_correct": PROJECTED_CORRECT,
        "projected_score_before_full_run": 69.36777264,
        "required_above": PARENT_SCORE,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _audit_candidate(
    observations: dict[str, Any], receipt: dict[str, Any], trace_dir: Path
) -> dict[str, Any]:
    errors: list[str] = []
    checks: dict[str, bool] = {}

    def check(name: str, condition: bool, detail: str) -> None:
        checks[name] = bool(condition)
        if not condition:
            errors.append(f"{name}: {detail}")

    parent_answer_order, parent_answers = _read_answer_rows(PARENT_DIR / "answer.csv")
    parent_evidence_order, parent_evidence = _read_evidence(PARENT_DIR / "evidence.json")
    rerun_answer_order, rerun_answers = _read_answer_rows(RERUN_BUNDLE_DIR / "answer.csv")
    rerun_evidence_order, rerun_evidence = _read_evidence(RERUN_BUNDLE_DIR / "evidence.json")
    candidate_answer_order, candidate_answers = _read_answer_rows(CANDIDATE_DIR / "answer.csv")
    candidate_evidence_order, candidate_evidence = _read_evidence(CANDIDATE_DIR / "evidence.json")
    official_qids = [str(item["qid"]) for item in load_all_questions()]
    multi_qids = list(_official_multi_qids())
    multi_set = set(multi_qids)
    inherited = [qid for qid in official_qids if qid not in multi_set]
    validation = validate_submission_files(*bundle_paths(CANDIDATE_DIR))
    check("general_submission_validator", validation["ok"] and validation["question_count"] == 100, str(validation))
    check("candidate_inventory_exact_three", {path.name for path in CANDIDATE_DIR.iterdir()} == {"answer.csv", "evidence.json", "run_manifest.json"}, "candidate dir must contain exactly three files")
    check("official_qid_order", candidate_answer_order == candidate_evidence_order == official_qids, "candidate qid order mismatch")
    check("parent_qid_order", parent_answer_order == parent_evidence_order == official_qids, "parent qid order mismatch")
    check("rerun_qid_order", rerun_answer_order == rerun_evidence_order == multi_qids, "rerun qid order mismatch")
    check("inherited_records_exact_parent", all(candidate_answers[qid] == parent_answers[qid] and candidate_evidence[qid] == parent_evidence[qid] for qid in inherited), "TF/MCQ changed from v2s1 parent")
    check("multi_records_exact_rerun", all(candidate_answers[qid] == rerun_answers[qid] and candidate_evidence[qid] == rerun_evidence[qid] for qid in multi_qids), "Multi record differs from traced rerun")
    manifest = _load_json(CANDIDATE_DIR / "run_manifest.json")
    trace_gate = manifest.get("agent_trace_gate") or {}
    check("candidate_lineage", manifest.get("parent_version") == PARENT_VERSION and set(map(str, manifest.get("rerun_qids") or [])) == multi_set and manifest.get("pipeline_version") == PIPELINE_VERSION, "candidate lineage mismatch")
    check("trace_gate", trace_gate.get("status") == "PASS" and trace_gate.get("served_models") == ["qwen-plus"] and trace_gate.get("logical_calls") == LOGICAL_CALL_COUNT and trace_gate.get("physical_attempts") == LOGICAL_CALL_COUNT and trace_gate.get("max_retries") == 0 and trace_gate.get("trace_manifest_sha256") == sha256_file(trace_dir / "trace_manifest.json"), "candidate Trace gate mismatch")
    check("run_receipt", receipt.get("status") == "PASS" and receipt.get("served_models") == ["qwen-plus"] and receipt.get("errors") == [], "full run receipt mismatch")
    candidate_total = int(manifest.get("total_tokens") or 0)
    token_factor = 0.7 + 0.3 * (TOKEN_BUDGET - candidate_total) / TOKEN_BUDGET
    projected_score = PROJECTED_CORRECT * token_factor
    check("token_penalized_projection", candidate_total > 0 and projected_score > PARENT_SCORE, f"projected score {projected_score} <= {PARENT_SCORE}")
    answer_diff = [
        {"qid": qid, "from": parent_answers[qid]["answer"], "to": candidate_answers[qid]["answer"]}
        for qid in official_qids
        if parent_answers[qid]["answer"] != candidate_answers[qid]["answer"]
    ]
    return {
        "schema_version": "e012-candidate-audit/v1",
        "experiment_id": EXPERIMENT_ID,
        "status": "PASS" if not errors else "FAIL",
        "decision": "FREEZE_CANDIDATE_THREE_FILE_BUNDLE" if not errors else "CANDIDATE_NO_GO",
        "checks": checks,
        "errors": errors,
        "summary": {
            "question_count": len(candidate_answers),
            "full_multi_count": len(multi_qids),
            "inherited_tf_mcq_count": len(inherited),
            "answer_diff_count": len(answer_diff),
            "candidate_total_tokens": candidate_total,
            "token_factor": token_factor,
            "prospective_projected_correct": PROJECTED_CORRECT,
            "token_penalized_projected_score": projected_score,
            "required_above": PARENT_SCORE,
            "actual_served_model": "qwen-plus",
            "logical_calls": LOGICAL_CALL_COUNT,
            "physical_attempts": LOGICAL_CALL_COUNT,
            "retries": 0,
        },
        "answer_diff": answer_diff,
        "artifacts": {
            "parent": PARENT_HASHES,
            "rerun": _bundle_hashes(RERUN_BUNDLE_DIR),
            "candidate": _bundle_hashes(CANDIDATE_DIR),
            "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
            "claim_sha256": sha256_file(CLAIM_PATH),
            "observations_sha256": sha256_file(OUTPUT_DIR / "observations.json"),
            "run_receipt_sha256": sha256_file(OUTPUT_DIR / "run_receipt.json"),
            "trace_manifest_sha256": sha256_file(trace_dir / "trace_manifest.json"),
        },
        "candidate_authorized": not errors,
        "submission_authorized": False,
        "upload_authorized": False,
        "created_at": now_iso(),
    }


def main() -> int:
    occupied = [path for path in (FULL_MULTI_RESULT_PATH, RERUN_BUNDLE_DIR, CANDIDATE_DIR, CANDIDATE_AUDIT_PATH, CANDIDATE_FREEZE_PATH) if path.exists()]
    if occupied:
        raise ValueError(f"E012 candidate one-shot slots occupied: {[display_path(path) for path in occupied]}")
    _verify_parent()
    observations, receipt, trace_dir, _ = _verify_full_run()
    _write_rerun_bundle(observations, receipt, trace_dir)
    merge_submission_bundles(
        PARENT_DIR, RERUN_BUNDLE_DIR, CANDIDATE_DIR, set(_official_multi_qids()),
        parent_version=PARENT_VERSION,
        experiment_id=EXPERIMENT_ID,
        experiment_pipeline_version=PIPELINE_VERSION,
    )
    _augment_candidate_manifest(trace_dir)
    audit = _audit_candidate(observations, receipt, trace_dir)
    CANDIDATE_AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if audit["status"] != "PASS":
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return 1
    result = {
        "schema_version": "e012-full-multi-result/v1",
        "experiment_id": EXPERIMENT_ID,
        "status": "PASS",
        "decision": "CANDIDATE_BUILD_AUTHORIZED",
        "question_count": QUESTION_COUNT,
        "logical_calls": LOGICAL_CALL_COUNT,
        "physical_attempts": LOGICAL_CALL_COUNT,
        "retries": 0,
        "actual_served_models": ["qwen-plus"],
        "tokens": {
            "prompt": int(receipt["prompt_tokens"]),
            "completion": int(receipt["completion_tokens"]),
            "total": int(receipt["total_tokens"]),
        },
        "artifacts": {
            "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
            "claim_sha256": sha256_file(CLAIM_PATH),
            "observations_sha256": sha256_file(OUTPUT_DIR / "observations.json"),
            "run_receipt_sha256": sha256_file(OUTPUT_DIR / "run_receipt.json"),
            "trace_manifest_sha256": sha256_file(trace_dir / "trace_manifest.json"),
            "rerun_bundle": _bundle_hashes(RERUN_BUNDLE_DIR),
            "candidate_audit_sha256": sha256_file(CANDIDATE_AUDIT_PATH),
        },
        "candidate_authorized": True,
        "submission_authorized": False,
        "upload_authorized": False,
        "created_at": now_iso(),
    }
    FULL_MULTI_RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    freeze = {
        "schema_version": "e012-candidate-freeze/v1",
        "experiment_id": EXPERIMENT_ID,
        "status": "FROZEN_READY_FOR_USER_SUBMISSION",
        "candidate_dir": display_path(CANDIDATE_DIR),
        "artifacts": {
            path.name: {"path": display_path(path), "sha256": sha256_file(path)}
            for path in bundle_paths(CANDIDATE_DIR)
        },
        "artifact_inventory": ["answer.csv", "evidence.json", "run_manifest.json"],
        "parent_dir": str(PARENT_DIR),
        "parent_artifacts": PARENT_HASHES,
        "rerun_bundle_dir": display_path(RERUN_BUNDLE_DIR),
        "rerun_artifacts": _bundle_hashes(RERUN_BUNDLE_DIR),
        "governance": {
            "run_freeze_sha256": sha256_file(RUN_FREEZE_PATH),
            "full_multi_result_sha256": sha256_file(FULL_MULTI_RESULT_PATH),
            "candidate_audit_sha256": sha256_file(CANDIDATE_AUDIT_PATH),
            "e011_scored_result_sha256": FROZEN_INPUT_SHA256["e011_scored_result"],
            "trace_manifest_sha256": sha256_file(trace_dir / "trace_manifest.json"),
        },
        "candidate_frozen_at": now_iso(),
        "candidate_ready_for_user": True,
        "submission_authorized": False,
        "upload_authorized": False,
        "push_authorized": False,
        "merge_authorized": False,
    }
    CANDIDATE_FREEZE_PATH.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "candidate_dir": display_path(CANDIDATE_DIR),
        "candidate_hashes": _bundle_hashes(CANDIDATE_DIR),
        "candidate_total_tokens": audit["summary"]["candidate_total_tokens"],
        "projected_score": audit["summary"]["token_penalized_projected_score"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
