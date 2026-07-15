"""Document metadata tests for v1-S1 evidence headers."""

from __future__ import annotations

from agent.doc_meta import build_doc_meta, format_source_header
from agent.retrieve import load_chunks


def test_build_doc_meta_extracts_insurance_product_title():
    meta = build_doc_meta(load_chunks())

    assert meta["insurance"]["1"]["title"]
    assert "平安" in meta["insurance"]["1"]["title"]
    assert meta["insurance"]["1"]["entity"] == meta["insurance"]["1"]["title"]


def test_build_doc_meta_uses_regulatory_title_override():
    meta = build_doc_meta(load_chunks())

    assert meta["regulatory"]["csrc_0009_att1"]["title"] == "上市公司信息披露管理办法"


def test_build_doc_meta_uses_key_title_overrides():
    meta = build_doc_meta(load_chunks())

    assert meta["insurance"]["2"]["title"] == "国寿增益宝终身寿险（万能型）（2025版）"
    assert meta["insurance"]["16"]["title"] == "平安富鸿金生（悦享版）养老年金保险（分红型）"
    assert meta["regulatory"]["csrc_0027_att1"]["title"] == "关于修改《证券公司分类监管规定》的决定"
    assert (
        meta["financial_reports"]["annual_byd_2024_report"]["title"]
        == "比亚迪股份有限公司 2024 年年度报告"
    )


def test_build_doc_meta_overrides_all_actual_insurance_docs():
    meta = build_doc_meta(load_chunks())

    expected_doc_ids = {str(i) for i in range(1, 17)}
    assert set(meta["insurance"]) == expected_doc_ids
    for doc_id in expected_doc_ids:
        title = meta["insurance"][doc_id]["title"]
        assert "险" in title
        assert "承担以下保险责任" not in title
        assert "阅读指引" not in title


def test_format_source_header_includes_title_doc_page_and_section():
    meta = {
        "insurance": {
            "1": {
                "title": "平安智盈金生专属商业养老保险",
                "entity": "平安智盈金生专属商业养老保险",
                "source_path": "public_dataset_upload/raw/insurance/1.pdf",
            }
        }
    }
    chunk = {
        "domain": "insurance",
        "doc_id": "1",
        "page": 12,
        "section": "身故保险金",
    }

    assert (
        format_source_header(chunk, meta)
        == "【平安智盈金生专属商业养老保险 · doc_id=1 · 第12页 · 身故保险金】"
    )
