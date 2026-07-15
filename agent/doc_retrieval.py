"""Document-card retrieval for questions without doc_ids (B-mode preparation)."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from agent.doc_meta import build_doc_meta
from agent.load_questions import load_all_questions
from agent.paths import PROCESSED_DATA_DIR
from agent.query_terms import extract_terms_from_text, is_numeric_term, normalize_text
from agent.retrieve import load_chunks


DOC_CARDS_PATH = PROCESSED_DATA_DIR / "doc_cards.json"
DOC_RECALL_REPORT_PATH = PROCESSED_DATA_DIR / "doc_recall_report.json"
MAX_KEYWORDS = 180

TYPE_TERMS = (
    "保险条款",
    "养老年金",
    "医疗保险",
    "财产保险",
    "年度报告",
    "募集说明书",
    "公司债券",
    "可转换债券",
    "管理办法",
    "实施细则",
    "反洗钱法",
    "证券研究报告",
    "行业研究",
    "深度报告",
)

YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def _group_chunks(chunks: Iterable[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for chunk in chunks:
        key = (str(chunk["domain"]), str(chunk["doc_id"]))
        grouped.setdefault(key, []).append(chunk)
    return grouped


def build_document_cards(
    chunks: list[dict[str, Any]], *, max_keywords: int = MAX_KEYWORDS
) -> list[dict[str, Any]]:
    """Build deterministic title/entity/year/type/keyword cards for every document."""
    grouped = _group_chunks(chunks)
    meta = build_doc_meta(chunks)
    term_counts: dict[tuple[str, str], Counter[str]] = {}
    doc_frequency: Counter[tuple[str, str]] = Counter()

    for key, doc_chunks in grouped.items():
        domain, doc_id = key
        info = meta.get(domain, {}).get(doc_id, {})
        counts: Counter[str] = Counter()
        title_terms = extract_terms_from_text(
            f"{info.get('title', '')} {info.get('entity', '')}"
        )
        counts.update({term: 8 for term in title_terms})
        for chunk in doc_chunks:
            # Per-chunk uniqueness prevents boilerplate repetitions from dominating.
            counts.update(set(extract_terms_from_text(str(chunk.get("text", "")))))
        term_counts[key] = counts
        for term in counts:
            doc_frequency[(domain, term)] += 1

    domain_sizes = Counter(domain for domain, _ in grouped)
    cards: list[dict[str, Any]] = []
    for (domain, doc_id), doc_chunks in sorted(grouped.items()):
        info = meta.get(domain, {}).get(doc_id, {})
        title = str(info.get("title") or doc_id)
        entity = str(info.get("entity") or title)
        joined = "\n".join(str(chunk.get("text", "")) for chunk in doc_chunks)
        years = sorted(set(YEAR_RE.findall(f"{title}\n{joined}")))
        normalized = normalize_text(f"{title}\n{joined}")
        type_keywords = [term for term in TYPE_TERMS if normalize_text(term) in normalized]

        scored_terms: list[tuple[float, str]] = []
        for term, count in term_counts[(domain, doc_id)].items():
            df = doc_frequency[(domain, term)]
            idf = math.log(1.0 + (domain_sizes[domain] + 0.5) / (df + 0.5))
            numeric_bonus = 2.5 if is_numeric_term(term) else 1.0
            score = math.log1p(count) * idf * min(len(term), 6) * numeric_bonus
            scored_terms.append((score, term))
        scored_terms.sort(key=lambda item: (-item[0], -len(item[1]), item[1]))
        keywords = [term for _, term in scored_terms[:max_keywords]]
        cards.append(
            {
                "domain": domain,
                "doc_id": doc_id,
                "title": title,
                "entity": entity,
                "years": years,
                "type_keywords": type_keywords,
                "keywords": keywords,
                "source_path": str(doc_chunks[0].get("source_path", "")),
            }
        )
    return cards


def _query_text(question: dict[str, Any]) -> str:
    options = " ".join(str(value) for value in question.get("options", {}).values())
    return f"{question.get('question', '')} {options}"


def score_document_card(question: dict[str, Any], card: dict[str, Any]) -> float:
    query_terms = extract_terms_from_text(_query_text(question))
    title = normalize_text(str(card.get("title", "")))
    entity = normalize_text(str(card.get("entity", "")))
    years = set(card.get("years", []))
    type_terms = {normalize_text(term) for term in card.get("type_keywords", [])}
    keyword_rank = {
        normalize_text(term): rank for rank, term in enumerate(card.get("keywords", []))
    }
    keyword_count = max(len(keyword_rank), 1)

    score = 0.0
    for term in query_terms:
        norm = normalize_text(term)
        base = min(len(norm), 6) * (3.0 if is_numeric_term(norm) else 1.0)
        if norm in title:
            score += base * 7.0
        if norm in entity:
            score += base * 5.0
        if norm in years:
            score += base * 4.0
        if norm in type_terms:
            score += base * 3.0
        if norm in keyword_rank:
            rank_weight = 1.0 + 2.0 * (keyword_count - keyword_rank[norm]) / keyword_count
            score += base * rank_weight
    return score


def select_documents(
    question: dict[str, Any], cards: list[dict[str, Any]], *, top_k: int
) -> list[dict[str, Any]]:
    domain = str(question.get("domain") or "")
    candidates = [card for card in cards if not domain or card["domain"] == domain]
    scored = [
        {**card, "score": round(score_document_card(question, card), 6)}
        for card in candidates
    ]
    scored.sort(key=lambda card: (-card["score"], card["doc_id"]))
    return scored[:top_k]


def evaluate_hidden_doc_recall(
    questions: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    ks: Iterable[int],
) -> dict[str, Any]:
    evaluated = [question for question in questions if question.get("doc_ids")]
    results: dict[str, Any] = {}
    for top_k in sorted(set(ks)):
        complete = 0
        doc_hits = 0
        doc_total = 0
        per_question: list[dict[str, Any]] = []
        domain_counts: dict[str, dict[str, int]] = {}
        for question in evaluated:
            expected = {str(doc_id) for doc_id in question["doc_ids"]}
            hidden = {**question, "doc_ids": []}
            selected = select_documents(hidden, cards, top_k=top_k)
            predicted = {card["doc_id"] for card in selected}
            hits = len(expected & predicted)
            is_complete = expected <= predicted
            complete += int(is_complete)
            doc_hits += hits
            doc_total += len(expected)
            domain = str(question.get("domain") or "unknown")
            domain_result = domain_counts.setdefault(
                domain,
                {"complete_count": 0, "question_count": 0, "doc_hits": 0, "doc_total": 0},
            )
            domain_result["complete_count"] += int(is_complete)
            domain_result["question_count"] += 1
            domain_result["doc_hits"] += hits
            domain_result["doc_total"] += len(expected)
            per_question.append(
                {
                    "qid": question["qid"],
                    "domain": domain,
                    "expected_doc_ids": sorted(expected),
                    "selected_doc_ids": [card["doc_id"] for card in selected],
                    "complete": is_complete,
                    "doc_hits": hits,
                }
            )
        by_domain = {
            domain: {
                **counts,
                "complete_recall": counts["complete_count"] / counts["question_count"],
                "micro_recall": counts["doc_hits"] / counts["doc_total"],
            }
            for domain, counts in sorted(domain_counts.items())
        }
        results[str(top_k)] = {
            "top_k": top_k,
            "question_count": len(evaluated),
            "complete_recall": complete / len(evaluated) if evaluated else 0.0,
            "micro_recall": doc_hits / doc_total if doc_total else 0.0,
            "complete_count": complete,
            "doc_hits": doc_hits,
            "doc_total": doc_total,
            "by_domain": by_domain,
            "per_question": per_question,
        }
    recommended_k = next(
        (
            int(key)
            for key, result in results.items()
            if result["complete_recall"] >= 0.90
        ),
        None,
    )
    recommended_k_all_domains = next(
        (
            int(key)
            for key, result in results.items()
            if all(
                domain_result["complete_recall"] >= 0.90
                for domain_result in result["by_domain"].values()
            )
        ),
        None,
    )
    return {
        "document_count": len(cards),
        "question_count": len(evaluated),
        "target_complete_recall": 0.90,
        "recommended_k": recommended_k,
        "recommended_k_all_domains": recommended_k_all_domains,
        "by_k": results,
    }


def load_document_cards(path: Path = DOC_CARDS_PATH) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cards-output", type=Path, default=DOC_CARDS_PATH)
    parser.add_argument("--report-output", type=Path, default=DOC_RECALL_REPORT_PATH)
    parser.add_argument("--ks", default="1,3,5,8,10,11,12,13,14,15")
    args = parser.parse_args()

    ks = [int(value) for value in args.ks.split(",") if value.strip()]
    cards = build_document_cards(load_chunks())
    report = evaluate_hidden_doc_recall(load_all_questions(), cards, ks)
    args.cards_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.cards_output.write_text(
        json.dumps(cards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.report_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for key, result in report["by_k"].items():
        print(
            f"K={key} complete={result['complete_recall']:.3%} "
            f"micro={result['micro_recall']:.3%}"
        )
    print(f"recommended_k={report['recommended_k']}")
    print(f"recommended_k_all_domains={report['recommended_k_all_domains']}")
    print(f"documents={report['document_count']} cards={args.cards_output}")
    print(f"report={args.report_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
