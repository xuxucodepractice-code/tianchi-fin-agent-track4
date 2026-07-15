"""Rule-based document metadata for evidence source headers.

The metadata is deterministic and model-free. It is used only to label evidence
with human-readable source names; it must not summarize or judge content.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent.paths import PROCESSED_DATA_DIR

DOC_META_PATH = PROCESSED_DATA_DIR / "doc_meta.json"

TITLE_OVERRIDES: dict[tuple[str, str], str] = {
    ("insurance", "1"): "平安智盈金生专属商业养老保险",
    ("insurance", "2"): "国寿增益宝终身寿险（万能型）（2025版）",
    ("insurance", "3"): "个人急性白血病复发医疗保险条款（互联网2026版A款）",
    ("insurance", "4"): "平安安佑福重大疾病保险",
    ("insurance", "5"): "平安e生保住院7.0医疗保险A款",
    ("insurance", "6"): "太保团体百万医疗保险（2022版）",
    ("insurance", "7"): "平安产险预防接种意外伤害保险（E款）（互联网版）",
    ("insurance", "8"): "营运交通工具团体意外伤害保险条款（互联网版2025A款）",
    ("insurance", "9"): "中国平安财产保险股份有限公司特种车商业保险示范条款（2020版）",
    ("insurance", "10"): "众安在线财产保险股份有限公司特种车商业保险示范条款（2020版）",
    ("insurance", "11"): "平安产险家庭财产保险（家庭版）（2025版）",
    ("insurance", "12"): "家庭财产综合保险条款（互联网2023版）",
    ("insurance", "13"): "食品安全责任保险条款（互联网2026版）",
    ("insurance", "14"): "平安产险食品安全责任保险（2021版）",
    ("insurance", "15"): "国寿鑫享添盈养老年金保险",
    ("insurance", "16"): "平安富鸿金生（悦享版）养老年金保险（分红型）",
    ("regulatory", "csrc_0009_att1"): "上市公司信息披露管理办法",
    ("regulatory", "csrc_0027_att1"): "关于修改《证券公司分类监管规定》的决定",
    ("financial_reports", "annual_byd_2024_report"): "比亚迪股份有限公司 2024 年年度报告",
    ("financial_reports", "annual_byd_2025_report"): "比亚迪股份有限公司 2025 年年度报告",
    ("financial_reports", "annual_catl_2024_report"): "宁德时代新能源科技股份有限公司 2024 年年度报告",
    ("financial_reports", "annual_catl_2025_report"): "宁德时代新能源科技股份有限公司 2025 年年度报告",
    ("financial_reports", "annual_chinamobile_2025_report"): "中国移动有限公司 2025 年年度报告",
    ("financial_reports", "annual_cscec_2024_report"): "中国建筑股份有限公司 2024 年年度报告",
    ("financial_reports", "annual_cscec_2025_report"): "中国建筑股份有限公司 2025 年年度报告",
    ("financial_reports", "annual_midea_2024_report"): "美的集团股份有限公司 2024 年年度报告",
    ("financial_reports", "annual_midea_2025_report"): "美的集团股份有限公司 2025 年年度报告",
}


def _clean_line(line: str) -> str:
    line = re.sub(r"[\uf000-\uf8ff]", "", line)
    line = re.sub(r"\s+", " ", line).strip(" -\t\r\n")
    return line


def _title_score(line: str) -> int:
    score = 0
    if "保险" in line:
        score += 4
    if any(word in line for word in ("合同", "条款", "办法", "报告", "募集说明书")):
        score += 2
    if any(word in line for word in ("目录", "阅读指引", "提示", "释义", "第一章")):
        score -= 3
    if 6 <= len(line) <= 80:
        score += 1
    if len(line) > 100:
        score -= 3
    return score


def _extract_title(chunks: list[dict[str, Any]]) -> str:
    candidates: list[str] = []
    for chunk in chunks[:4]:
        for raw_line in str(chunk.get("text", "")).splitlines()[:20]:
            line = _clean_line(raw_line)
            if not line or len(line) < 4:
                continue
            candidates.append(line)
    if not candidates:
        return ""
    candidates.sort(key=lambda line: (-_title_score(line), len(line), line))
    return candidates[0]


def build_doc_meta(chunks: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, str]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for chunk in chunks:
        grouped.setdefault((str(chunk["domain"]), str(chunk["doc_id"])), []).append(chunk)

    meta: dict[str, dict[str, dict[str, str]]] = {}
    for (domain, doc_id), doc_chunks in sorted(grouped.items()):
        doc_chunks.sort(key=lambda c: (c.get("page") or 0, c.get("chunk_id", "")))
        source_path = str(doc_chunks[0].get("source_path", ""))
        title = TITLE_OVERRIDES.get((domain, doc_id)) or _extract_title(doc_chunks)
        if not title:
            title = Path(source_path).stem or doc_id
        meta.setdefault(domain, {})[doc_id] = {
            "title": title,
            "entity": title,
            "source_path": source_path,
        }
    return meta


def write_doc_meta(
    chunks: list[dict[str, Any]],
    path: Path = DOC_META_PATH,
) -> Path:
    meta = build_doc_meta(chunks)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, sort_keys=True)
    return path


def load_doc_meta(path: Path = DOC_META_PATH) -> dict[str, dict[str, dict[str, str]]]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def format_source_header(
    chunk: dict[str, Any],
    meta: dict[str, dict[str, dict[str, str]]] | None = None,
) -> str:
    meta = meta or {}
    domain = str(chunk.get("domain", ""))
    doc_id = str(chunk.get("doc_id", ""))
    info = meta.get(domain, {}).get(doc_id, {})
    title = info.get("title") or Path(str(chunk.get("source_path", ""))).stem or doc_id
    parts = [title, f"doc_id={doc_id}"]
    if chunk.get("page") is not None:
        parts.append(f"第{chunk['page']}页")
    section = str(chunk.get("section", "")).strip()
    if section:
        parts.append(section[:40])
    return f"【{' · '.join(parts)}】"
