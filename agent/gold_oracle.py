"""Classify pipeline failures from completed Gold Oracle case records.

This module does not call a model and never changes submission artifacts.  Human
auditors fill the O1/O2/O3 observations; the classifier applies the predeclared
decision tree consistently and emits an error-map summary.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from agent.prompts import format_evidence_block


FAILURE_LAYERS = (
    "data_or_question",
    "parsing",
    "retrieval",
    "evidence_organization",
    "reasoning_or_prompt",
    "answer_synthesis",
    "no_failure",
)

BOOLEAN_FIELDS = (
    "raw_source_contains_all_required_facts",
    "chunks_contain_all_required_facts",
    "current_retrieval_contains_all_required_facts",
    "current_evidence_rendering_preserves_all_required_facts",
)

ANSWER_FIELDS = (
    "gold_answer",
    "gold_evidence_answer",
    "current_reasoning_answer",
    "current_final_answer",
)


def canonical_answer(value: Any) -> str:
    text = "" if value is None else str(value).strip().upper()
    if not text:
        return ""
    if all(char in "ABCD" for char in text):
        return "".join(sorted(set(text)))
    return text


def build_gold_evidence(
    required_chunk_ids: list[str], chunks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Build evidence objects from exact chunk ids without injecting an answer."""
    by_id = {str(chunk.get("chunk_id")): chunk for chunk in chunks}
    missing = [chunk_id for chunk_id in required_chunk_ids if chunk_id not in by_id]
    if missing:
        raise ValueError(f"Gold chunk ids not found: {', '.join(missing)}")
    evidence: list[dict[str, Any]] = []
    for chunk_id in required_chunk_ids:
        chunk = by_id[chunk_id]
        evidence.append(
            {
                "chunk_id": chunk_id,
                "doc_id": chunk["doc_id"],
                "page": chunk.get("page"),
                "section": chunk.get("section", ""),
                "text": chunk["text"],
            }
        )
    return evidence


def render_gold_evidence(
    required_chunk_ids: list[str], chunks: list[dict[str, Any]]
) -> str:
    """Render gold evidence through the exact production prompt formatter."""
    return format_evidence_block(build_gold_evidence(required_chunk_ids, chunks))


def build_gold_retrieval(
    question: dict[str, Any],
    required_chunk_ids: list[str],
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a retrieval payload accepted by the production reasoning functions."""
    evidence = build_gold_evidence(required_chunk_ids, chunks)
    base = {
        "qid": question["qid"],
        "domain": question.get("domain", ""),
        "question": question.get("question", ""),
        "answer_format": question.get("answer_format", ""),
        "doc_ids": question.get("doc_ids", []),
        "top_k": len(evidence),
        "candidate_chunk_count": len(evidence),
        "oracle_source": "gold_chunk_ids",
    }
    if question.get("answer_format") == "tf":
        return {**base, "tf": {"query_terms": [], "evidence": evidence}}
    return {
        **base,
        "options": {
            key: {
                "option_text": option_text,
                "query_terms": [],
                "evidence": evidence,
            }
            for key, option_text in sorted(question.get("options", {}).items())
        },
    }


def incomplete_fields(case: dict[str, Any]) -> list[str]:
    missing = [field for field in BOOLEAN_FIELDS if not isinstance(case.get(field), bool)]
    missing.extend(
        field for field in ANSWER_FIELDS if not canonical_answer(case.get(field))
    )
    if not str(case.get("qid") or "").strip():
        missing.append("qid")
    return missing


def classify_case(case: dict[str, Any]) -> dict[str, Any]:
    missing = incomplete_fields(case)
    if missing:
        return {
            **case,
            "oracle_status": "incomplete",
            "missing_fields": sorted(missing),
            "primary_failure": None,
        }

    gold = canonical_answer(case["gold_answer"])
    gold_evidence = canonical_answer(case["gold_evidence_answer"])
    current_reasoning = canonical_answer(case["current_reasoning_answer"])
    current_final = canonical_answer(case["current_final_answer"])

    risk_flags: list[str] = []
    if not case["current_retrieval_contains_all_required_facts"]:
        risk_flags.append("retrieval")
    if not case["current_evidence_rendering_preserves_all_required_facts"]:
        risk_flags.append("evidence_organization")
    if gold_evidence != gold:
        risk_flags.append("reasoning_or_prompt")

    if not case["raw_source_contains_all_required_facts"]:
        layer = "data_or_question"
    elif not case["chunks_contain_all_required_facts"]:
        layer = "parsing"
    elif gold_evidence != gold:
        # O2 is decisive: complete gold evidence still failing isolates reasoning.
        layer = "reasoning_or_prompt"
    elif current_final == gold:
        # Missing current evidence may remain a risk, but a correct observed answer
        # is not counted as a lost question in the primary error map.
        layer = "no_failure"
    elif not case["current_retrieval_contains_all_required_facts"]:
        layer = "retrieval"
    elif not case["current_evidence_rendering_preserves_all_required_facts"]:
        layer = "evidence_organization"
    elif current_reasoning != gold:
        layer = "reasoning_or_prompt"
    elif current_final != gold:
        layer = "answer_synthesis"
    else:
        layer = "no_failure"

    return {
        **case,
        "gold_answer": gold,
        "gold_evidence_answer": gold_evidence,
        "current_reasoning_answer": current_reasoning,
        "current_final_answer": current_final,
        "oracle_status": "complete",
        "missing_fields": [],
        "primary_failure": layer,
        "risk_flags": risk_flags,
    }


def classify_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    classified: list[dict[str, Any]] = []
    for case in cases:
        qid = str(case.get("qid") or "").strip()
        if qid and qid in seen:
            raise ValueError(f"duplicate qid: {qid}")
        if qid:
            seen.add(qid)
        classified.append(classify_case(case))

    counts = Counter(
        case["primary_failure"]
        for case in classified
        if case["oracle_status"] == "complete"
    )
    return {
        "case_count": len(classified),
        "complete_count": sum(case["oracle_status"] == "complete" for case in classified),
        "incomplete_count": sum(case["oracle_status"] == "incomplete" for case in classified),
        "failure_counts": {layer: counts.get(layer, 0) for layer in FAILURE_LAYERS},
        "cases": classified,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list) or not all(isinstance(case, dict) for case in cases):
        raise ValueError("input must be a case list or an object containing a case list")

    result = classify_cases(cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"cases={result['case_count']} complete={result['complete_count']} "
        f"incomplete={result['incomplete_count']} output={args.output}"
    )
    return 0 if result["incomplete_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
