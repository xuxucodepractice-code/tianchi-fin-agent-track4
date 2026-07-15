"""Build an offline v1-S1 rerun qid list without calling Qwen."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agent.load_questions import load_all_questions
from agent.paths import REPO_ROOT
from agent.retrieve import load_chunks, retrieve_for_question

DEFAULT_BASELINE_EVIDENCE = (
    REPO_ROOT
    / "workspace/03_baseline_improvement/submissions/a_leaderboard_v0/"
    / "2026-07-05_score_63_2607/evidence.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "workspace/03_baseline_improvement/submissions/a_leaderboard_v0/"
    / "v1_s1/rerun_qids.txt"
)

S1_SEED_QIDS = {"reg_a_006", "reg_a_015", "reg_a_018", "fin_a_005", "fin_a_006"}


def _evidence_chunk_ids(record: dict[str, Any], retrieval_key: str) -> set[str]:
    ids: set[str] = set()
    retrieval = record.get(retrieval_key, {})
    options = retrieval.get("options", retrieval)
    if not isinstance(options, dict):
        return ids
    for opt in options.values():
        if not isinstance(opt, dict):
            continue
        for ev in opt.get("evidence", []):
            if not isinstance(ev, dict):
                continue
            if ev.get("chunk_id"):
                ids.add(str(ev["chunk_id"]))
    return ids


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


def _is_multi_entity_doc_coverage_question(question: dict[str, Any]) -> bool:
    return (
        question.get("domain") in {"insurance", "financial_reports"}
        and len(question.get("doc_ids") or []) >= 3
    )


def select_rerun_qids(
    questions: list[dict[str, Any]],
    baseline_by_qid: dict[str, dict[str, Any]],
    current_by_qid: dict[str, dict[str, Any]],
    jaccard_threshold: float = 0.6,
) -> tuple[list[str], dict[str, list[str]]]:
    reasons: dict[str, list[str]] = {}
    for question in questions:
        qid = str(question["qid"])
        if qid in S1_SEED_QIDS:
            reasons.setdefault(qid, []).append("s1_seed")
        if _is_multi_entity_doc_coverage_question(question):
            reasons.setdefault(qid, []).append("multi_entity_doc_coverage")

        baseline = baseline_by_qid.get(qid)
        current = current_by_qid.get(qid)
        if baseline is None or current is None:
            continue
        baseline_ids = _evidence_chunk_ids(baseline, "retrieval")
        current_ids = _evidence_chunk_ids(current, "options")
        score = _jaccard(baseline_ids, current_ids)
        if score < jaccard_threshold:
            reasons.setdefault(qid, []).append(f"retrieval_jaccard={score:.3f}")

    return sorted(reasons), {qid: reasons[qid] for qid in sorted(reasons)}


def _load_baseline(path: Path) -> dict[str, dict[str, Any]]:
    records = json.loads(path.read_text(encoding="utf-8"))
    return {str(record["qid"]): record for record in records}


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agent.build_rerun_list",
        description="Build an offline rerun qid list for v1-S1 evidence-quality changes.",
    )
    parser.add_argument("--baseline-evidence", default=str(DEFAULT_BASELINE_EVIDENCE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--top-k", type=int, default=5, dest="top_k")
    parser.add_argument("--threshold", type=float, default=0.6)
    args = parser.parse_args()

    baseline_path = Path(args.baseline_evidence)
    output_path = Path(args.output)
    if not baseline_path.is_absolute():
        baseline_path = REPO_ROOT / baseline_path
    if not output_path.is_absolute():
        output_path = REPO_ROOT / output_path

    try:
        baseline = _load_baseline(baseline_path)
        questions = load_all_questions()
        chunks = load_chunks()
    except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    current = {
        str(question["qid"]): retrieve_for_question(question, chunks, top_k=args.top_k)
        for question in questions
    }
    qids, reasons = select_rerun_qids(
        questions, baseline, current, jaccard_threshold=args.threshold
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(qids) + ("\n" if qids else ""), encoding="utf-8")
    report_path = output_path.with_suffix(".json")
    report_path.write_text(
        json.dumps(
            {
                "baseline_evidence": str(baseline_path.relative_to(REPO_ROOT)),
                "top_k": args.top_k,
                "jaccard_threshold": args.threshold,
                "rerun_count": len(qids),
                "rerun_qids": qids,
                "reasons": reasons,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[rerun] qids={len(qids)}")
    print(f"[out] {output_path}")
    print(f"[out] {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
