"""Run controlled O2 Gold Evidence and O3 Current Evidence observations."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.gold_oracle import build_gold_retrieval
from agent.load_questions import load_all_questions
from agent.qwen_client import MissingApiKeyError, QwenClient
from agent.reason_qwen import reason_question_with_qwen, reason_tf_question_with_qwen
from agent.retrieve import load_chunks, retrieve_for_question, retrieve_for_tf_question


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def run_oracle_case(
    case: dict[str, Any],
    question: dict[str, Any],
    chunks: list[dict[str, Any]],
    client: QwenClient,
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    """Run gold and current evidence without passing gold_answer to either call."""
    required_chunk_ids = case.get("required_chunk_ids")
    if not isinstance(required_chunk_ids, list) or not required_chunk_ids:
        raise ValueError(f"{case.get('qid')}: required_chunk_ids missing")

    gold_retrieval = build_gold_retrieval(question, required_chunk_ids, chunks)
    if question.get("answer_format") == "tf":
        current_retrieval = retrieve_for_tf_question(question, chunks, top_k=top_k)
        gold_result = reason_tf_question_with_qwen(question, gold_retrieval, client=client)
        current_result = reason_tf_question_with_qwen(
            question, current_retrieval, client=client
        )
    else:
        current_retrieval = retrieve_for_question(question, chunks, top_k=top_k)
        gold_result = reason_question_with_qwen(question, gold_retrieval, client=client)
        current_result = reason_question_with_qwen(
            question, current_retrieval, client=client
        )

    return {
        "qid": question["qid"],
        "pipeline_version": gold_result.get("pipeline_version"),
        "model": gold_result.get("model"),
        "observed_at": _now_iso(),
        "gold_evidence_answer": gold_result["answer"],
        "current_reasoning_answer": current_result["answer"],
        "current_final_answer": current_result["answer"],
        "gold_total_tokens": gold_result.get("total_tokens", 0),
        "current_total_tokens": current_result.get("total_tokens", 0),
        "gold_result": gold_result,
        "current_result": current_result,
        "gold_retrieval_source": "required_chunk_ids",
        "current_retrieval_source": "production_retrieval",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qids", help="comma-separated subset; default is every O1-ready case")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    payload = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = payload.get("cases", [])
    requested = (
        {qid.strip() for qid in args.qids.split(",") if qid.strip()}
        if args.qids
        else None
    )
    selected = [
        case
        for case in cases
        if (requested is None or case.get("qid") in requested)
        and case.get("gold_answer")
        and case.get("required_chunk_ids")
        and case.get("raw_source_contains_all_required_facts") is True
        and case.get("chunks_contain_all_required_facts") is True
    ]
    if requested is not None:
        selected_qids = {str(case.get("qid")) for case in selected}
        missing = requested - selected_qids
        if missing:
            raise ValueError(f"requested cases are not O1-ready: {', '.join(sorted(missing))}")
    if not selected:
        raise ValueError("no O1-ready cases selected")

    try:
        client = QwenClient()
    except MissingApiKeyError as exc:
        print(f"[error] {exc}")
        return 1
    questions = {question["qid"]: question for question in load_all_questions()}
    chunks = load_chunks()
    observations = [
        run_oracle_case(case, questions[case["qid"]], chunks, client, top_k=args.top_k)
        for case in selected
    ]
    result = {
        "experiment_id": "S3_GOLD_ORACLE_O2_O3",
        "case_source": str(args.cases),
        "case_count": len(observations),
        "total_tokens": sum(
            item["gold_total_tokens"] + item["current_total_tokens"]
            for item in observations
        ),
        "observations": observations,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"cases={len(observations)} tokens={result['total_tokens']} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
