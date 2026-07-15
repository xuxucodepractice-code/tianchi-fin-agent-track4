"""Audit S2 labeling selections for coverage, type safety, and card integrity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent.generate_labeling_packets import QUESTIONS_DIR, load_questions
from agent.paths import REPO_ROOT


DEFAULT_EVALUATION_DIR = (
    REPO_ROOT / "workspace" / "03_baseline_improvement" / "evaluation"
)
DEFAULT_PLAN = DEFAULT_EVALUATION_DIR / "labeling_plan.json"
FORBIDDEN_CARD_MARKERS = (
    "v0 answer",
    "v1_s1 answer",
    "v2 answer",
    "gold_answer",
    "A→B",
    "KEEP_SCORE",
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _selection_qids(evaluation_dir: Path, relative_path: str) -> list[str]:
    payload = _load_json(evaluation_dir / relative_path)
    qids = payload.get("qids")
    if not isinstance(qids, list) or not all(isinstance(qid, str) for qid in qids):
        raise ValueError(f"invalid qids list: {relative_path}")
    if len(qids) != len(set(qids)):
        raise ValueError(f"duplicate qids in selection: {relative_path}")
    return qids


def audit_plan(
    plan_path: Path = DEFAULT_PLAN,
    questions_dir: Path = QUESTIONS_DIR,
) -> dict[str, Any]:
    evaluation_dir = plan_path.parent
    plan = _load_json(plan_path)
    questions = load_questions(questions_dir)
    by_qid = {question["qid"]: question for question in questions}

    historical_tf = list(plan["historical_tf_qids"])
    s2a_tf = list(plan["s2a_tf_qids"])
    remaining_tf = _selection_qids(evaluation_dir, plan["remaining_tf_selection"])
    mcq = _selection_qids(evaluation_dir, plan["mcq_selection"])
    multi = _selection_qids(evaluation_dir, plan["multi_selection"])

    errors: list[str] = []
    all_tf = {qid for qid, question in by_qid.items() if question["answer_format"] == "tf"}
    planned_tf = historical_tf + s2a_tf + remaining_tf
    if len(planned_tf) != len(set(planned_tf)):
        errors.append("TF groups overlap")
    if set(planned_tf) != all_tf:
        errors.append(
            f"TF coverage mismatch missing={sorted(all_tf - set(planned_tf))} "
            f"extra={sorted(set(planned_tf) - all_tf)}"
        )

    all_mcq = {qid for qid, question in by_qid.items() if question["answer_format"] == "mcq"}
    if set(mcq) != all_mcq:
        errors.append(
            f"MCQ coverage mismatch missing={sorted(all_mcq - set(mcq))} "
            f"extra={sorted(set(mcq) - all_mcq)}"
        )

    for label, qids, expected_format in (
        ("remaining_tf", remaining_tf, "tf"),
        ("mcq", mcq, "mcq"),
        ("multi", multi, "multi"),
    ):
        if any(qid not in by_qid for qid in qids):
            errors.append(f"{label} contains unknown qid")
            continue
        wrong = [qid for qid in qids if by_qid[qid]["answer_format"] != expected_format]
        if wrong:
            errors.append(f"{label} has wrong answer_format: {wrong}")

    if len(mcq) != 15:
        errors.append(f"MCQ count must be 15, got {len(mcq)}")
    if len(remaining_tf) != 10:
        errors.append(f"remaining TF count must be 10, got {len(remaining_tf)}")
    if len(multi) != 15:
        errors.append(f"Multi count must be 15, got {len(multi)}")
    multi_domains = {by_qid[qid]["domain"] for qid in multi if qid in by_qid}
    if len(multi_domains) != 5:
        errors.append(f"Multi selection must cover five domains, got {sorted(multi_domains)}")

    card_groups = {
        "remaining_tf": (
            evaluation_dir / "blind_labeling" / "tf_remaining",
            remaining_tf,
        ),
        "mcq": (evaluation_dir / "blind_labeling" / "tier1_mcq", mcq),
        "multi": (evaluation_dir / "blind_labeling" / "multi_tier1", multi),
    }
    for label, (folder, qids) in card_groups.items():
        expected = {f"{qid}_blind.md" for qid in qids}
        actual = {path.name for path in folder.glob("*_blind.md")}
        if actual != expected:
            errors.append(
                f"{label} card mismatch missing={sorted(expected - actual)} "
                f"extra={sorted(actual - expected)}"
            )
        for path in folder.glob("*_blind.md"):
            text = path.read_text(encoding="utf-8")
            leaked = [marker for marker in FORBIDDEN_CARD_MARKERS if marker in text]
            if leaked:
                errors.append(f"answer leakage marker in {path.name}: {leaked}")

    return {
        "plan_id": plan.get("plan_id"),
        "valid": not errors,
        "errors": errors,
        "counts": {
            "all_tf": len(all_tf),
            "historical_tf": len(historical_tf),
            "s2a_tf": len(s2a_tf),
            "remaining_tf": len(remaining_tf),
            "mcq": len(mcq),
            "multi": len(multi),
            "multi_domains": len(multi_domains),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--questions-dir", type=Path, default=QUESTIONS_DIR)
    args = parser.parse_args()
    result = audit_plan(args.plan, args.questions_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
