"""Exact v0 Multi retrieval control plus the E006 routing treatment.

The online v2s1 submission inherited every Multi record from v0.  Those
records were produced by ``agent/retrieve.py`` at commit ``82041d0`` rather
than by the later quota/neighbor implementation on the current branch.

This module intentionally keeps the v0 retrieval and evidence rendering
contract byte-compatible:

* one BM25 index over the question's supplied ``doc_ids``;
* exactly the global top five hits per option;
* one chunk per evidence item (no neighbor merge or document quota);
* the original 1,200-character earliest-match window;
* no source header or other post-v0 evidence fields.

E006 changes only which five already-scored hits are selected.  When an
option has one high-confidence document-title match, the treatment takes the
top five hits from that document while preserving scores from the full index.
Ambiguous and low-confidence options fall back to the exact v0 selection.
"""

from __future__ import annotations

from typing import Any

from agent.doc_meta import load_doc_meta
from agent.query_terms import (
    build_option_query_terms,
    build_term_weights,
    extract_terms_from_text,
    normalize_text,
)
from agent.retrieve import (
    Bm25LiteIndex,
    build_bm25_index,
    filter_chunks_for_question,
    score_chunk,
)

V0_RETRIEVE_COMMIT = "82041d0"
V0_RETRIEVE_SOURCE_SHA256 = (
    "1e55d7f8c725805fd4b752c2bab929119cb39ee3409275b45b1cdd782484dc3c"
)
V0_MAX_EVIDENCE_TEXT = 1200
V0_TOP_K = 5

ROUTE_MIN_TITLE_SCORE = 12
ROUTE_MIN_LONGEST_MATCH = 4
ROUTE_MIN_SCORE_RATIO = 3.0
ROUTE_MIN_SCORE_MARGIN = 8


def _truncate_v0(text: str, matched_terms: list[str]) -> str:
    """Reproduce v0's 1,200-character earliest-match window exactly."""
    if len(text) <= V0_MAX_EVIDENCE_TEXT:
        return text
    norm = normalize_text(text)
    first_pos = min(
        (norm.find(term) for term in matched_terms if norm.find(term) >= 0),
        default=0,
    )
    start = max(0, first_pos - V0_MAX_EVIDENCE_TEXT // 3)
    return text[start : start + V0_MAX_EVIDENCE_TEXT]


def _score_option_against_title(option_text: str, title: str) -> dict[str, Any]:
    """Return the frozen E006 title-overlap score for one document."""
    normalized_title = normalize_text(title)
    matched_terms = [
        term
        for term in extract_terms_from_text(option_text)
        if term in normalized_title
    ]
    return {
        "score": sum(min(len(term), 6) for term in matched_terms),
        "longest_match": max((len(term) for term in matched_terms), default=0),
        "matched_terms": matched_terms,
    }


def decide_option_document_route(
    question: dict[str, Any],
    option_key: str,
    option_text: str,
    doc_meta: dict[str, dict[str, dict[str, str]]] | None,
) -> dict[str, Any]:
    """Choose one supplied document only when the frozen route gate passes.

    The result is diagnostic metadata and is never inserted into the model
    prompt.  Missing metadata, ties, weak matches, and comparison-like options
    all fail safely to the unchanged v0 global top-five selection.
    """
    thresholds = {
        "minimum_title_score": ROUTE_MIN_TITLE_SCORE,
        "minimum_longest_match": ROUTE_MIN_LONGEST_MATCH,
        "minimum_score_ratio": ROUTE_MIN_SCORE_RATIO,
        "minimum_score_margin": ROUTE_MIN_SCORE_MARGIN,
    }
    diagnostic: dict[str, Any] = {
        "option_key": option_key,
        "decision": "fallback",
        "reason": "",
        "target_doc_id": None,
        "thresholds": thresholds,
        "document_scores": [],
    }
    if question.get("answer_format") != "multi":
        diagnostic["reason"] = "non_multi"
        return diagnostic

    doc_ids = [str(doc_id) for doc_id in question.get("doc_ids") or []]
    if len(doc_ids) < 2:
        diagnostic["reason"] = "fewer_than_two_documents"
        return diagnostic

    domain = str(question.get("domain") or "")
    domain_meta = (doc_meta or {}).get(domain, {})
    if any(doc_id not in domain_meta for doc_id in doc_ids):
        diagnostic["reason"] = "missing_document_metadata"
        return diagnostic

    scored_docs: list[dict[str, Any]] = []
    for doc_id in doc_ids:
        info = domain_meta[doc_id]
        title = str(info.get("title") or info.get("entity") or "")
        title_score = _score_option_against_title(option_text, title)
        scored_docs.append(
            {
                "doc_id": doc_id,
                "title": title,
                **title_score,
            }
        )
    scored_docs.sort(
        key=lambda row: (-row["score"], -row["longest_match"], row["doc_id"])
    )
    diagnostic["document_scores"] = scored_docs

    top = scored_docs[0]
    second = scored_docs[1]
    second_denominator = max(int(second["score"]), 1)
    ratio = float(top["score"]) / second_denominator
    margin = int(top["score"]) - int(second["score"])
    diagnostic.update(
        {
            "top_score": int(top["score"]),
            "second_score": int(second["score"]),
            "score_ratio": ratio,
            "score_margin": margin,
        }
    )

    if int(top["longest_match"]) < ROUTE_MIN_LONGEST_MATCH:
        diagnostic["reason"] = "longest_match_below_threshold"
    elif int(top["score"]) < ROUTE_MIN_TITLE_SCORE:
        diagnostic["reason"] = "title_score_below_threshold"
    elif ratio < ROUTE_MIN_SCORE_RATIO:
        diagnostic["reason"] = "score_ratio_below_threshold"
    elif margin < ROUTE_MIN_SCORE_MARGIN:
        diagnostic["reason"] = "score_margin_below_threshold"
    else:
        diagnostic.update(
            {
                "decision": "route",
                "reason": "high_confidence_unique_title_match",
                "target_doc_id": str(top["doc_id"]),
            }
        )
    return diagnostic


def _score_option(
    index: Bm25LiteIndex,
    question: dict[str, Any],
    option_key: str,
    option_text: str,
) -> list[tuple[float, int, list[str]]]:
    weights = build_term_weights(question, option_key, option_text)
    scored: list[tuple[float, int, list[str]]] = []
    for pos in range(index.n):
        score, matched = score_chunk(index, pos, weights)
        if matched:
            scored.append((score, pos, matched))
    scored.sort(key=lambda row: (-row[0], index.chunks[row[1]]["chunk_id"]))
    return scored


def _render_v0_evidence(
    index: Bm25LiteIndex,
    selected: list[tuple[float, int, list[str]]],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for score, pos, matched in selected:
        chunk = index.chunks[pos]
        evidence.append(
            {
                "chunk_id": chunk["chunk_id"],
                "doc_id": chunk["doc_id"],
                "source_type": chunk["source_type"],
                "source_path": chunk["source_path"],
                "page": chunk["page"],
                "section": chunk.get("section", ""),
                "score": round(score, 4),
                "matched_terms": sorted(matched, key=lambda term: (-len(term), term))[:20],
                "text": _truncate_v0(chunk["text"], matched),
            }
        )
    return evidence


def retrieve_multi_v0_compatible(
    question: dict[str, Any],
    chunks: list[dict[str, Any]],
    *,
    enable_option_document_route: bool,
    top_k: int = V0_TOP_K,
    doc_meta: dict[str, dict[str, dict[str, str]]] | None = None,
    diagnostics_out: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the exact v0 Multi control or the E006 one-variable treatment."""
    if question.get("answer_format") != "multi":
        raise ValueError("v0-compatible E006 retrieval is Multi-only")
    if top_k != V0_TOP_K:
        raise ValueError(f"v0-compatible E006 retrieval freezes top_k={V0_TOP_K}")
    if not question.get("doc_ids"):
        raise ValueError("v0-compatible E006 retrieval requires supplied doc_ids")

    candidates = filter_chunks_for_question(chunks, question)
    index = build_bm25_index(candidates)
    resolved_meta = doc_meta
    if enable_option_document_route and resolved_meta is None:
        resolved_meta = load_doc_meta()

    route_diagnostics: dict[str, Any] = {}
    options_out: dict[str, Any] = {}
    for option_key in sorted(question.get("options", {})):
        option_text = str(question["options"][option_key])
        scored = _score_option(index, question, option_key, option_text)
        control_selected = scored[:top_k]
        selected = control_selected
        diagnostic = {
            "option_key": option_key,
            "decision": "fallback",
            "reason": "route_disabled_control",
            "target_doc_id": None,
            "control_chunk_ids": [
                index.chunks[pos]["chunk_id"] for _, pos, _ in control_selected
            ],
        }

        if enable_option_document_route:
            diagnostic = decide_option_document_route(
                question, option_key, option_text, resolved_meta
            )
            target_doc_id = diagnostic.get("target_doc_id")
            if diagnostic.get("decision") == "route" and target_doc_id is not None:
                routed = [
                    row
                    for row in scored
                    if str(index.chunks[row[1]]["doc_id"]) == str(target_doc_id)
                ]
                if len(routed) >= top_k:
                    selected = routed[:top_k]
                else:
                    diagnostic.update(
                        {
                            "decision": "fallback",
                            "reason": "target_document_has_fewer_than_top_k_hits",
                            "target_doc_id": None,
                        }
                    )
            diagnostic["control_chunk_ids"] = [
                index.chunks[pos]["chunk_id"] for _, pos, _ in control_selected
            ]

        diagnostic["selected_chunk_ids"] = [
            index.chunks[pos]["chunk_id"] for _, pos, _ in selected
        ]
        route_diagnostics[option_key] = diagnostic
        options_out[option_key] = {
            "option_text": option_text,
            "query_terms": build_option_query_terms(question, option_key, option_text),
            "evidence": _render_v0_evidence(index, selected),
        }

    if diagnostics_out is not None:
        diagnostics_out.clear()
        diagnostics_out.update(
            {
                "schema_version": "e006-route-diagnostics/v1",
                "enabled": enable_option_document_route,
                "qid": str(question.get("qid") or ""),
                "options": route_diagnostics,
            }
        )

    return {
        "qid": question["qid"],
        "domain": question.get("domain", ""),
        "question": question.get("question", ""),
        "answer_format": question.get("answer_format", ""),
        "doc_ids": question.get("doc_ids", []),
        "top_k": top_k,
        "candidate_chunk_count": len(candidates),
        "options": options_out,
    }
