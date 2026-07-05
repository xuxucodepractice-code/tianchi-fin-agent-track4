"""无 embedding 证据检索（Task 4）。

用法：
    python -m agent.retrieve --qid ins_a_007 --top-k 5
    python -m agent.retrieve --qid ins_a_007 --top-k 5 --output processed_data/retrieval_samples/ins_a_007.json

策略：
- A 榜：候选 chunks 严格限定在题目 doc_ids 内（domain + doc_id 双重过滤）。
- B 榜预留：无 doc_ids 时按 domain 全域检索（fallback，本任务不优化）。
- 逐选项检索：每个选项独立构建 query terms 并打分，返回 top_k evidence。
- 计分：BM25 风格 —— 权重(来源/长度/数字加成) × idf × tf 饱和，section 命中轻微加分。
- matched_terms 为空的 chunk 不进入结果。

不使用 embedding，不调用任何模型；只读 chunks.jsonl，不修改 Task 3 产物。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from agent.load_questions import find_question_by_qid
from agent.paths import PROCESSED_DATA_DIR, REPO_ROOT
from agent.query_terms import (
    build_option_query_terms,
    build_term_weights,
    normalize_text,
)

CHUNKS_PATH = PROCESSED_DATA_DIR / "chunks.jsonl"
RETRIEVAL_SAMPLES_DIR = PROCESSED_DATA_DIR / "retrieval_samples"

MAX_EVIDENCE_TEXT = 1200  # evidence text 截断上限（字符）


# ---------------------------------------------------------------- 加载与过滤


def load_chunks(chunks_path: Path = CHUNKS_PATH) -> list[dict[str, Any]]:
    if not chunks_path.is_file():
        raise FileNotFoundError(
            f"缺少 {chunks_path}。请先运行: python -m agent.parse_documents --group group_a"
        )
    chunks: list[dict[str, Any]] = []
    with chunks_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                chunks.append(json.loads(line))
    if not chunks:
        raise ValueError(f"{chunks_path} 为空。请重新运行 parse_documents。")
    return chunks


def filter_chunks_for_question(
    chunks: list[dict[str, Any]], question: dict[str, Any]
) -> list[dict[str, Any]]:
    """A 榜：按 doc_ids 限定候选；B 榜 fallback：按 domain 全域（本任务不优化）。"""
    domain = question.get("domain", "")
    doc_ids = question.get("doc_ids") or []
    if doc_ids:
        wanted = set(doc_ids)
        return [c for c in chunks if c["domain"] == domain and c["doc_id"] in wanted]
    # B 榜 fallback：无 doc_ids 时退化为领域内全部 chunks
    return [c for c in chunks if c["domain"] == domain]


# ---------------------------------------------------------------- 索引与计分


class Bm25LiteIndex:
    """轻量 BM25 风格索引：缓存归一化文本与按需计算的 term 文档频次。

    不做分词倒排（查询词是动态 n-gram，用子串匹配统计 tf/df），
    候选集已被 doc_ids 限定到百量级，纯 Python 足够快。
    """

    K1 = 1.2
    B = 0.4

    def __init__(self, chunks: list[dict[str, Any]]):
        self.chunks = chunks
        self.norm_texts = [normalize_text(c["text"]) for c in chunks]
        self.norm_sections = [normalize_text(c.get("section", "")) for c in chunks]
        self.n = len(chunks)
        self.avg_len = (sum(len(t) for t in self.norm_texts) / self.n) if self.n else 1.0
        self._df_cache: dict[str, int] = {}

    def df(self, term: str) -> int:
        if term not in self._df_cache:
            self._df_cache[term] = sum(1 for t in self.norm_texts if term in t)
        return self._df_cache[term]

    def idf(self, term: str) -> float:
        return math.log(1.0 + (self.n - self.df(term) + 0.5) / (self.df(term) + 0.5))


def build_bm25_index(chunks: list[dict[str, Any]]) -> Bm25LiteIndex:
    return Bm25LiteIndex(chunks)


def score_chunk(
    index: Bm25LiteIndex, chunk_pos: int, weights: dict[str, float]
) -> tuple[float, list[str]]:
    """对候选集中第 chunk_pos 个 chunk 计分，返回 (score, matched_terms)。"""
    text = index.norm_texts[chunk_pos]
    section = index.norm_sections[chunk_pos]
    len_norm = 1.0 - Bm25LiteIndex.B + Bm25LiteIndex.B * len(text) / index.avg_len

    score = 0.0
    matched: list[str] = []
    for term, weight in weights.items():
        tf = text.count(term)
        if tf == 0:
            continue
        matched.append(term)
        tf_sat = tf * (Bm25LiteIndex.K1 + 1) / (tf + Bm25LiteIndex.K1 * len_norm)
        term_score = weight * index.idf(term) * tf_sat
        if term in section:
            term_score *= 1.1  # section 命中轻微加分
        score += term_score
    return score, matched


def _truncate_around_match(text: str, matched_terms: list[str]) -> str:
    """超长文本围绕最早命中的 term 截取窗口，保留上下文。"""
    if len(text) <= MAX_EVIDENCE_TEXT:
        return text
    norm = normalize_text(text)
    first_pos = min(
        (norm.find(t) for t in matched_terms if norm.find(t) >= 0),
        default=0,
    )
    start = max(0, first_pos - MAX_EVIDENCE_TEXT // 3)
    return text[start : start + MAX_EVIDENCE_TEXT]


# ---------------------------------------------------------------- 检索主流程


def retrieve_for_option(
    chunks: list[dict[str, Any]],
    question: dict[str, Any],
    option_key: str,
    option_text: str,
    top_k: int = 5,
    index: Bm25LiteIndex | None = None,
) -> list[dict[str, Any]]:
    """对单个选项检索，返回按 score 降序的 evidence 列表（不超过 top_k）。"""
    if index is None:
        index = build_bm25_index(chunks)
    weights = build_term_weights(question, option_key, option_text)

    scored: list[tuple[float, int, list[str]]] = []
    for pos in range(index.n):
        score, matched = score_chunk(index, pos, weights)
        if matched:  # matched_terms 为空不进入结果
            scored.append((score, pos, matched))
    # score 降序；同分按 chunk_id 升序，保证确定性
    scored.sort(key=lambda x: (-x[0], index.chunks[x[1]]["chunk_id"]))

    evidence = []
    for score, pos, matched in scored[:top_k]:
        c = index.chunks[pos]
        evidence.append(
            {
                "chunk_id": c["chunk_id"],
                "doc_id": c["doc_id"],
                "source_type": c["source_type"],
                "source_path": c["source_path"],
                "page": c["page"],
                "section": c.get("section", ""),
                "score": round(score, 4),
                "matched_terms": sorted(matched, key=lambda t: (-len(t), t))[:20],
                "text": _truncate_around_match(c["text"], matched),
            }
        )
    return evidence


def retrieve_for_question(
    question: dict[str, Any],
    chunks: list[dict[str, Any]],
    top_k: int = 5,
) -> dict[str, Any]:
    """对一道题的全部选项检索，输出可供 Task 5 Qwen 逐项判断直接消费的结构。"""
    candidates = filter_chunks_for_question(chunks, question)
    index = build_bm25_index(candidates)

    options_out: dict[str, Any] = {}
    for option_key in sorted(question.get("options", {})):
        option_text = question["options"][option_key]
        options_out[option_key] = {
            "option_text": option_text,
            "query_terms": build_option_query_terms(question, option_key, option_text),
            "evidence": retrieve_for_option(
                candidates, question, option_key, option_text, top_k=top_k, index=index
            ),
        }

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


# ---------------------------------------------------------------- CLI


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agent.retrieve",
        description="无 embedding 证据检索（不调用模型，不判断答案）",
    )
    parser.add_argument("--qid", required=True, help="题目 qid，例如 ins_a_007")
    parser.add_argument("--top-k", type=int, default=5, dest="top_k")
    parser.add_argument("--output", default=None, help="检索结果 JSON 输出路径（可选）")
    parser.add_argument(
        "--chunks", default=str(CHUNKS_PATH), help="chunks.jsonl 路径（默认 processed_data/chunks.jsonl）"
    )
    args = parser.parse_args()

    try:
        chunks = load_chunks(Path(args.chunks))
        question = find_question_by_qid(args.qid)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    result = retrieve_for_question(question, chunks, top_k=args.top_k)

    print(
        f"[retrieve] qid={result['qid']} domain={result['domain']} "
        f"format={result['answer_format']} doc_ids={result['doc_ids']} "
        f"candidates={result['candidate_chunk_count']}"
    )
    for key, opt in result["options"].items():
        ev = opt["evidence"]
        top = ev[0] if ev else None
        top_desc = (
            f"top1={top['chunk_id']} score={top['score']} matched={top['matched_terms'][:3]}"
            if top
            else "top1=<无召回>"
        )
        print(f"[retrieve]   option {key}: evidence={len(ev)} {top_desc}")

    if args.output:
        out_path = Path(args.output)
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[out] {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
