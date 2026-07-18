"""Score E010 primary after the frozen E011 audit and independent blind labels."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.evaluate_e010_prospective_scored import (
    PARENT_MULTI_ANSWERS_PATH,
    evaluate_scored,
    _load_parent_answers,
)
from agent.evaluate_e011_e010_churn_audit import (
    E011_AUDIT_ID,
    E011_AUDIT_REPORT_PATH,
    E011_EXPERIMENT_DIR,
    E011_LABELS_PATH,
    E011_SCORED_RESULT_PATH,
)
from agent.run_e010_prospective_arm import (
    EXPECTED_OUTPUT_DIRS,
    PAIR_ID as E010_PAIR_ID,
    PROSPECTIVE_QIDS,
    PROSPECTIVE_SELECTION_PATH,
)
from agent.trace_gate import display_path, now_iso, sha256_file

E011_AUDIT_RESULT_PATH = E011_EXPERIMENT_DIR / "audit_result.json"
E011_SCORE_RUN_FREEZE_PATH = E011_EXPERIMENT_DIR / "score_run_freeze.json"
E011_SCORER_PATH = Path(__file__).resolve()


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _validate_score_freeze() -> dict[str, Any]:
    freeze = _load(E011_SCORE_RUN_FREEZE_PATH)
    errors: list[str] = []
    if (
        freeze.get("schema_version") != "e011-score-run-freeze/v1"
        or freeze.get("experiment_id") != "E011"
        or freeze.get("audit_id") != E011_AUDIT_ID
        or freeze.get("status") != "AUTHORIZED_FOR_BLIND_LABEL_SCORING"
    ):
        errors.append("score freeze identity/status mismatch")
    if re.fullmatch(r"[0-9a-f]{40}", str(freeze.get("source_code_commit") or "")) is None:
        errors.append("score freeze source commit invalid")
    if freeze.get("scorer") != {
        "path": display_path(E011_SCORER_PATH),
        "sha256": sha256_file(E011_SCORER_PATH),
    }:
        errors.append("score freeze scorer hash mismatch")
    if freeze.get("frozen_inputs") != {
        "audit_report_sha256": sha256_file(E011_AUDIT_REPORT_PATH),
        "audit_result_sha256": sha256_file(E011_AUDIT_RESULT_PATH),
        "selection_sha256": sha256_file(PROSPECTIVE_SELECTION_PATH),
        "primary_observations_sha256": sha256_file(
            EXPECTED_OUTPUT_DIRS["primary"] / "observations.json"
        ),
        "primary_receipt_sha256": sha256_file(
            EXPECTED_OUTPUT_DIRS["primary"] / "run_receipt.json"
        ),
        "parent_multi_answers_sha256": sha256_file(PARENT_MULTI_ANSWERS_PATH),
    }:
        errors.append("score freeze input hashes mismatch")
    if freeze.get("registered_paths") != {
        "labels": display_path(E011_LABELS_PATH),
        "scored_result": display_path(E011_SCORED_RESULT_PATH),
    }:
        errors.append("score freeze output paths mismatch")
    if freeze.get("gate") != {
        "N_minus_M_strictly_greater_than_C": True,
        "token_penalized_projected_score_strictly_above": 65.0912,
        "parent_correct": 70,
        "parent_total_tokens": 1168763,
        "full_multi_question_count": 65,
    }:
        errors.append("score freeze gate mismatch")
    if freeze.get("initial_state") != {
        "labels_created": False,
        "scored_result_exists": False,
    }:
        errors.append("score freeze initial-state mismatch")
    if freeze.get("candidate_authorized") is not False or freeze.get(
        "submission_authorized"
    ) is not False:
        errors.append("score freeze must not authorize candidate/submission")
    if errors:
        raise ValueError(f"E011 score freeze invalid: {errors}")
    return freeze


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if E011_SCORED_RESULT_PATH.exists():
        raise ValueError(f"fixed scored result exists: {E011_SCORED_RESULT_PATH}")
    freeze = _validate_score_freeze()
    audit = _load(E011_AUDIT_REPORT_PATH)
    audit_result = _load(E011_AUDIT_RESULT_PATH)
    labels = _load(E011_LABELS_PATH)
    observations_path = EXPECTED_OUTPUT_DIRS["primary"] / "observations.json"
    receipt_path = EXPECTED_OUTPUT_DIRS["primary"] / "run_receipt.json"
    observations = _load(observations_path)
    receipt = _load(receipt_path)
    if (
        audit.get("status") != "PASS"
        or audit.get("decision") != "READY_FOR_BLIND_LABELING"
        or audit.get("scoring_arm") != "primary"
        or audit.get("bundle_errors") != []
        or not all((audit.get("checks") or {}).values())
        or audit_result.get("status") != "PASS"
        or audit_result.get("artifacts", {}).get("audit_report_sha256")
        != sha256_file(E011_AUDIT_REPORT_PATH)
    ):
        raise ValueError("E011 audit does not authorize scoring")
    if (
        labels.get("schema_version") != "e011-prospective-labels/v1"
        or labels.get("experiment_id") != "E011"
        or labels.get("audit_id") != E011_AUDIT_ID
        or tuple(map(str, labels.get("qids") or [])) != PROSPECTIVE_QIDS
        or labels.get("created_after_audit_freeze") is not True
        or labels.get("revealed_to_generation") is not False
        or labels.get("audit_report_sha256") != sha256_file(E011_AUDIT_REPORT_PATH)
        or labels.get("selection_sha256") != sha256_file(PROSPECTIVE_SELECTION_PATH)
        or labels.get("independent_labeling") is not True
    ):
        raise ValueError("E011 labels schema/isolation binding mismatch")
    try:
        audit_time = datetime.fromisoformat(str(audit["created_at"]))
        label_time = datetime.fromisoformat(str(labels["created_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid audit/label timestamps: {exc}") from exc
    if label_time < audit_time:
        raise ValueError("labels predate frozen audit")
    gold = {str(k): str(v) for k, v in (labels.get("answers") or {}).items()}
    if set(gold) != set(PROSPECTIVE_QIDS):
        raise ValueError("blind labels differ from frozen qids")
    rows = observations.get("observations") or []
    primary = {str(row.get("qid") or ""): str(row.get("answer") or "") for row in rows}
    if tuple(primary) != PROSPECTIVE_QIDS:
        raise ValueError("primary qids/order mismatch")
    if (
        receipt.get("status") != "PASS"
        or receipt.get("pair_id") != E010_PAIR_ID
        or receipt.get("attempt") != "primary"
        or receipt.get("observations_sha256") != sha256_file(observations_path)
    ):
        raise ValueError("E010 primary receipt binding mismatch")
    scored = evaluate_scored(
        primary_answers=primary,
        parent_answers=_load_parent_answers(),
        gold_answers=gold,
        churn_c=int(audit.get("primary_repeat_answer_churn_C") or 0),
        primary_tokens=int(receipt.get("total_tokens") or 0),
    )
    report = {
        "schema_version": "e011-prospective-scored-result/v1",
        "experiment_id": "E011",
        "audit_id": E011_AUDIT_ID,
        "scoring_source_pair_id": E010_PAIR_ID,
        "status": "PASS" if scored["allow_full_65_multi_expansion"] else "NO_GO",
        "decision": (
            "ALLOW_FULL_65_MULTI_EXPANSION"
            if scored["allow_full_65_multi_expansion"]
            else "PROSPECTIVE_SCORED_NO_GO"
        ),
        **scored,
        "artifacts": {
            "score_run_freeze_sha256": sha256_file(E011_SCORE_RUN_FREEZE_PATH),
            "audit_report_sha256": sha256_file(E011_AUDIT_REPORT_PATH),
            "labels_sha256": sha256_file(E011_LABELS_PATH),
            "primary_observations_sha256": sha256_file(observations_path),
            "primary_receipt_sha256": sha256_file(receipt_path),
            "parent_multi_answers_sha256": sha256_file(PARENT_MULTI_ANSWERS_PATH),
        },
        "candidate_authorized": False,
        "submission_authorized": False,
        "created_at": now_iso(),
    }
    with E011_SCORED_RESULT_PATH.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
