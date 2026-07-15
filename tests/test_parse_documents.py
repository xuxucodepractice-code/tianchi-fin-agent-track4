"""文档解析测试。

前置：需先运行
    python -m agent.check_doc_map
    python -m agent.parse_documents --group group_a
运行：python -m pytest tests/test_parse_documents.py -q
"""

from __future__ import annotations

import json

import pytest

from agent.chunk_schema import make_chunk, validate_chunk
from agent.parse_documents import (
    CHUNKS_PATH,
    PARSE_REPORT_PATH,
    load_doc_map,
    merge_char_lines,
    parse_all,
)


# ---------------------------------------------------------------- schema


def _legal_chunk() -> dict:
    return make_chunk(
        domain="insurance",
        doc_id="1",
        source_type="pdf",
        source_path="public_dataset_upload/raw/insurance/1.pdf",
        page=1,
        section="",
        text="这是一个用于测试的合法文本内容，长度超过二十个字符以通过校验。",
        chunk_index=0,
    )


def test_validate_chunk_accepts_legal_chunk():
    chunk = _legal_chunk()
    validate_chunk(chunk)  # 不应抛异常
    assert chunk["chunk_id"] == "insurance:1:1:0"


def test_validate_chunk_rejects_empty_text():
    chunk = _legal_chunk()
    chunk["text"] = "   "
    with pytest.raises(ValueError):
        validate_chunk(chunk)


# ---------------------------------------------------------------- doc map 输入


def test_load_doc_map_reads_doc_id_map():
    doc_map = load_doc_map()
    assert doc_map["group"] == "group_a"
    assert doc_map["unique_doc_count"] == len(doc_map["mappings"]) > 0


# ---------------------------------------------------------------- 生成产物

def _load_chunks() -> list[dict]:
    assert CHUNKS_PATH.is_file(), (
        f"缺少 {CHUNKS_PATH}，请先运行 python -m agent.parse_documents --group group_a"
    )
    with CHUNKS_PATH.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f]  # 每行必须是合法 JSON


def test_pdf_chunks_have_page():
    chunks = _load_chunks()
    pdf_insurance = [
        c for c in chunks if c["source_type"] == "pdf" and c["domain"] == "insurance"
    ]
    assert pdf_insurance, "insurance 应有 pdf chunk"
    assert all(isinstance(c["page"], int) and c["page"] >= 1 for c in pdf_insurance)


def test_html_chunks_page_is_null():
    chunks = _load_chunks()
    html = [c for c in chunks if c["source_type"] == "html"]
    assert html, "regulatory 应有 html chunk"
    assert all(c["page"] is None for c in html)
    assert all(c["domain"] == "regulatory" for c in html)


def test_txt_chunks_page_is_null():
    chunks = _load_chunks()
    txt = [c for c in chunks if c["source_type"] == "txt"]
    assert txt, "regulatory 应有 strict_v3 txt chunk"
    assert all(c["page"] is None for c in txt)
    assert all(c["doc_id"].startswith("strict_v3_") for c in txt)


def test_chunks_jsonl_every_line_valid_json_and_schema():
    chunks = _load_chunks()  # json.loads 已保证每行合法 JSON
    for c in chunks:
        validate_chunk(c)


def test_all_chunk_texts_non_empty():
    chunks = _load_chunks()
    assert all(c["text"].strip() for c in chunks)


def test_chunk_ids_unique():
    chunks = _load_chunks()
    ids = [c["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids))


def test_parse_report_chunk_count_matches_jsonl():
    assert PARSE_REPORT_PATH.is_file()
    with PARSE_REPORT_PATH.open("r", encoding="utf-8") as f:
        report = json.load(f)
    chunks = _load_chunks()
    assert report["chunk_count"] == len(chunks)
    assert report["parsed_document_count"] + report["failed_document_count"] == report["document_count"]


def test_merge_char_lines_repairs_pdf_single_character_lines():
    raw = "上\n市\n公\n司\n信\n息\n披\n露\n管\n理\n办\n法\n第\n一\n章\n总\n则\n董\n事\n会\n审\n议\n通\n过 。"

    repaired = merge_char_lines(raw)

    assert "上市公司信息披露管理办法" in repaired
    assert "董事会审议通过" in repaired
    assert "\n市\n" not in repaired


def test_merge_char_lines_leaves_normal_paragraphs_unchanged():
    raw = "第一条 为了规范上市公司信息披露行为。\n第二条 信息披露义务人应当真实、准确、完整。"

    assert merge_char_lines(raw) == raw


def test_parse_all_can_refresh_only_requested_doc_id(monkeypatch):
    doc_map = {
        "mappings": [
            {"domain": "regulatory", "doc_id": "csrc_0009_att1", "source_type": "pdf", "path": "a.pdf"},
            {"domain": "insurance", "doc_id": "1", "source_type": "pdf", "path": "b.pdf"},
        ]
    }
    calls = []

    def fake_parse_one(mapping, refresh=False):
        calls.append((mapping["doc_id"], refresh))
        return [], []

    monkeypatch.setattr("agent.parse_documents._parse_one_cached", fake_parse_one)

    parse_all(doc_map, refresh_doc_ids={"csrc_0009_att1"})

    assert calls == [("csrc_0009_att1", True), ("1", False)]
