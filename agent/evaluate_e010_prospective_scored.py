"""Score the frozen E010 primary arm only after label-free churn is frozen."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.run_e010_prospective_arm import (
    CHURN_REPORT_PATH,
    EXPECTED_OUTPUT_DIRS,
    FROZEN_INPUT_SHA256,
    PAIR_ID,
    PROSPECTIVE_LABELS_PATH,
    PROSPECTIVE_QIDS,
    PROSPECTIVE_SCORED_RESULT_PATH,
)
from agent.trace_gate import now_iso, sha256_file

PARENT_SCORE = 65.0912
PARENT_CORRECT = 70
PARENT_TOTAL_TOKENS = 1_168_763
MULTI_QUESTION_COUNT = 65
TOKEN_BUDGET = 5_000_000
PARENT_MULTI_ANSWERS_PATH = (
    Path(__file__).resolve().parents[1]
    / "workspace/03_baseline_improvement/submissions/a_leaderboard_v0/2026-07-05_score_63_2607/answer.csv"
)


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def token_factor(total_tokens: float) -> float:
    token_score = max(0.0, (TOKEN_BUDGET - float(total_tokens)) / TOKEN_BUDGET)
    return 0.7 + 0.3 * token_score


def evaluate_scored(
    *,
    primary_answers: dict[str, str],
    parent_answers: dict[str, str],
    gold_answers: dict[str, str],
    churn_c: int,
    primary_tokens: int,
) -> dict[str, Any]:
    improved: list[str] = []
    regressed: list[str] = []
    unchanged: list[str] = []
    for qid in PROSPECTIVE_QIDS:
        parent_ok = parent_answers[qid] == gold_answers[qid]
        primary_ok = primary_answers[qid] == gold_answers[qid]
        if primary_ok and not parent_ok:
            improved.append(qid)
        elif parent_ok and not primary_ok:
            regressed.append(qid)
        else:
            unchanged.append(qid)
    n = len(improved)
    m = len(regressed)
    net = n - m
    projected_multi_tokens = primary_tokens / len(PROSPECTIVE_QIDS) * MULTI_QUESTION_COUNT
    projected_total_tokens = PARENT_TOTAL_TOKENS + projected_multi_tokens
    projected_correct = PARENT_CORRECT + net / len(PROSPECTIVE_QIDS) * MULTI_QUESTION_COUNT
    projected_score = projected_correct * token_factor(projected_total_tokens)
    checks = {
        "N_minus_M_greater_than_C": net > churn_c,
        "projected_token_penalized_score_above_parent": projected_score > PARENT_SCORE,
    }
    return {
        "N": n,
        "M": m,
        "C": churn_c,
        "N_minus_M": net,
        "improved_qids": improved,
        "regressed_qids": regressed,
        "unchanged_qids": unchanged,
        "tokens": {
            "primary_holdout": primary_tokens,
            "parent_total": PARENT_TOTAL_TOKENS,
            "projected_65_multi": projected_multi_tokens,
            "projected_candidate_total": projected_total_tokens,
        },
        "score_projection": {
            "parent_correct": PARENT_CORRECT,
            "projected_correct": projected_correct,
            "token_factor": token_factor(projected_total_tokens),
            "projected_score": projected_score,
            "required_above": PARENT_SCORE,
        },
        "checks": checks,
        "allow_full_65_multi_expansion": all(checks.values()),
    }


def _load_parent_answers() -> dict[str, str]:
    with PARENT_MULTI_ANSWERS_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    answers = {str(row["qid"]): str(row["answer"]) for row in rows}
    missing = [qid for qid in PROSPECTIVE_QIDS if qid not in answers]
    if missing:
        raise ValueError(f"parent answer.csv lacks prospective qids: {missing}")
    return answers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if PROSPECTIVE_SCORED_RESULT_PATH.exists():
        raise ValueError(f"fixed scored result already exists: {PROSPECTIVE_SCORED_RESULT_PATH}")
    churn = _load(CHURN_REPORT_PATH)
    labels = _load(PROSPECTIVE_LABELS_PATH)
    observations_path = EXPECTED_OUTPUT_DIRS["primary"] / "observations.json"
    receipt_path = EXPECTED_OUTPUT_DIRS["primary"] / "run_receipt.json"
    observations = _load(observations_path)
    receipt = _load(receipt_path)
    if (
        churn.get("status") != "PASS"
        or churn.get("decision") != "READY_FOR_BLIND_LABELING"
        or churn.get("scoring_arm") != "primary"
    ):
        raise ValueError("frozen churn does not authorize blind scoring")
    if (
        labels.get("schema_version") != "e010-prospective-labels/v1"
        or labels.get("experiment_id") != "E010"
        or tuple(map(str, labels.get("qids") or [])) != PROSPECTIVE_QIDS
        or labels.get("created_after_churn_freeze") is not True
        or labels.get("revealed_to_generation") is not False
        or labels.get("churn_sha256") != sha256_file(CHURN_REPORT_PATH)
        or labels.get("selection_sha256") != FROZEN_INPUT_SHA256["selection"]
    ):
        raise ValueError("prospective labels schema/isolation binding mismatch")
    try:
        churn_time = datetime.fromisoformat(str(churn["created_at"]))
        labels_time = datetime.fromisoformat(str(labels["created_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid churn/label timestamps: {exc}") from exc
    if labels_time < churn_time:
        raise ValueError("labels predate churn freeze")
    gold = {str(k): str(v) for k, v in (labels.get("answers") or {}).items()}
    if set(gold) != set(PROSPECTIVE_QIDS):
        raise ValueError("prospective labels qids differ from frozen selection")
    rows = observations.get("observations") or []
    primary = {str(row.get("qid") or ""): str(row.get("answer") or "") for row in rows}
    if tuple(primary) != PROSPECTIVE_QIDS:
        raise ValueError("primary observations order/qids differ from selection")
    if (
        receipt.get("status") != "PASS"
        or receipt.get("pair_id") != PAIR_ID
        or receipt.get("attempt") != "primary"
        or receipt.get("observations_sha256") != sha256_file(observations_path)
    ):
        raise ValueError("primary receipt no longer binds scoring observations")
    scored = evaluate_scored(
        primary_answers=primary,
        parent_answers=_load_parent_answers(),
        gold_answers=gold,
        churn_c=int(churn.get("primary_repeat_answer_churn_C") or 0),
        primary_tokens=int(receipt.get("total_tokens") or 0),
    )
    report = {
        "schema_version": "e010-prospective-scored-result/v1",
        "experiment_id": "E010",
        "pair_id": PAIR_ID,
        "status": "PASS" if scored["allow_full_65_multi_expansion"] else "NO_GO",
        "decision": (
            "ALLOW_FULL_65_MULTI_EXPANSION"
            if scored["allow_full_65_multi_expansion"]
            else "PROSPECTIVE_SCORED_NO_GO"
        ),
        **scored,
        "artifacts": {
            "selection_sha256": FROZEN_INPUT_SHA256["selection"],
            "churn_sha256": sha256_file(CHURN_REPORT_PATH),
            "labels_sha256": sha256_file(PROSPECTIVE_LABELS_PATH),
            "primary_observations_sha256": sha256_file(observations_path),
            "primary_receipt_sha256": sha256_file(receipt_path),
            "parent_multi_answers_sha256": sha256_file(PARENT_MULTI_ANSWERS_PATH),
        },
        "candidate_authorized": False,
        "submission_authorized": False,
        "created_at": now_iso(),
    }
    with PROSPECTIVE_SCORED_RESULT_PATH.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
