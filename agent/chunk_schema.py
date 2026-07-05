"""统一 chunk 结构：构造与校验。

chunk 字段：
    chunk_id     稳定 ID，格式 domain:doc_id:page:chunk_index（无页码时 page 位为 "na"）
    domain       insurance|financial_contracts|financial_reports|regulatory|research
    doc_id       原始 doc_id
    source_type  pdf|html|txt
    source_path  repo 相对路径
    page         PDF 为页码（int，从 1 开始），HTML/TXT 为 None
    section      标题、条款号或空字符串
    text         非空正文
    char_count   len(text)
"""

from __future__ import annotations

from typing import Any

VALID_DOMAINS = {
    "insurance",
    "financial_contracts",
    "financial_reports",
    "regulatory",
    "research",
}
VALID_SOURCE_TYPES = {"pdf", "html", "txt"}

REQUIRED_FIELDS = [
    "chunk_id",
    "domain",
    "doc_id",
    "source_type",
    "source_path",
    "page",
    "section",
    "text",
    "char_count",
]


def make_chunk(
    domain: str,
    doc_id: str,
    source_type: str,
    source_path: str,
    page: int | None,
    section: str,
    text: str,
    chunk_index: int,
) -> dict[str, Any]:
    """构造一个 chunk。chunk_id 由输入确定性生成，重复运行结果一致。"""
    text = text.strip()
    page_key = str(page) if page is not None else "na"
    chunk = {
        "chunk_id": f"{domain}:{doc_id}:{page_key}:{chunk_index}",
        "domain": domain,
        "doc_id": doc_id,
        "source_type": source_type,
        "source_path": source_path,
        "page": page,
        "section": section or "",
        "text": text,
        "char_count": len(text),
    }
    validate_chunk(chunk)
    return chunk


def validate_chunk(chunk: dict[str, Any]) -> None:
    """校验 chunk 结构，不合法抛 ValueError。"""
    for field in REQUIRED_FIELDS:
        if field not in chunk:
            raise ValueError(f"chunk 缺少字段: {field}")
    if chunk["domain"] not in VALID_DOMAINS:
        raise ValueError(f"非法 domain: {chunk['domain']!r}")
    if chunk["source_type"] not in VALID_SOURCE_TYPES:
        raise ValueError(f"非法 source_type: {chunk['source_type']!r}")
    if not isinstance(chunk["text"], str) or not chunk["text"].strip():
        raise ValueError(f"chunk text 不能为空: chunk_id={chunk.get('chunk_id')!r}")
    if chunk["page"] is not None and (
        not isinstance(chunk["page"], int) or chunk["page"] < 1
    ):
        raise ValueError(f"page 必须为 None 或正整数: {chunk['page']!r}")
    if chunk["source_type"] == "pdf" and chunk["page"] is None:
        raise ValueError(f"pdf chunk 必须有页码: chunk_id={chunk['chunk_id']!r}")
    if chunk["source_type"] in ("html", "txt") and chunk["page"] is not None:
        raise ValueError(
            f"{chunk['source_type']} chunk 的 page 必须为 null: chunk_id={chunk['chunk_id']!r}"
        )
    if chunk["char_count"] != len(chunk["text"]):
        raise ValueError(f"char_count 与 text 长度不一致: chunk_id={chunk['chunk_id']!r}")
    if not isinstance(chunk["source_path"], str) or chunk["source_path"].startswith("/"):
        raise ValueError(f"source_path 必须为 repo 相对路径: {chunk['source_path']!r}")
