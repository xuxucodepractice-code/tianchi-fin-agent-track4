"""doc_id 映射测试。运行：python -m pytest tests/test_doc_id_map.py -q"""

from __future__ import annotations

import pytest

from agent.doc_id_map import (
    DocMapError,
    build_group_doc_map,
    resolve_doc_path,
)
from agent.load_questions import load_all_questions
from agent.paths import REPO_ROOT

RAW = "public_dataset_upload/raw"


def _rel(path) -> str:
    return str(path.relative_to(REPO_ROOT))


def test_insurance_numeric_id():
    p = resolve_doc_path(REPO_ROOT, "insurance", "1")
    assert _rel(p) == f"{RAW}/insurance/1.pdf"
    assert p.is_file()


def test_financial_contracts_text_id():
    p = resolve_doc_path(REPO_ROOT, "financial_contracts", "text01")
    assert _rel(p) == f"{RAW}/financial_contracts/text01.pdf"
    assert p.is_file()


def test_research_pack_id():
    p = resolve_doc_path(REPO_ROOT, "research", "pack2_text04")
    assert _rel(p) == f"{RAW}/research/pack2_text04.pdf"
    assert p.is_file()


def test_financial_reports_uppercase_pdf():
    p = resolve_doc_path(REPO_ROOT, "financial_reports", "annual_byd_2024_report")
    assert p.suffix == ".PDF"
    assert p.is_file()


def test_financial_reports_lowercase_pdf():
    p = resolve_doc_path(REPO_ROOT, "financial_reports", "annual_cscec_2024_report")
    assert p.suffix == ".pdf"
    assert p.is_file()


def test_regulatory_html():
    p = resolve_doc_path(REPO_ROOT, "regulatory", "csrc_0262")
    assert _rel(p) == f"{RAW}/regulatory/html/csrc_0262.html"
    assert p.is_file()


def test_regulatory_attachment_pdf():
    p = resolve_doc_path(REPO_ROOT, "regulatory", "csrc_0009_att1")
    assert _rel(p) == f"{RAW}/regulatory/attachments/csrc_0009_att1.pdf"
    assert p.is_file()


def test_regulatory_strict_v3_txt_prefix_glob():
    p = resolve_doc_path(REPO_ROOT, "regulatory", "strict_v3_017_中华人民共和国反洗钱法")
    assert p.name.startswith("strict_v3_017_")
    assert p.suffix == ".txt"
    assert p.is_file()


def test_unknown_doc_id_raises_clear_error():
    with pytest.raises(DocMapError) as exc_info:
        resolve_doc_path(REPO_ROOT, "insurance", "does_not_exist_999")
    msg = str(exc_info.value)
    assert "insurance" in msg
    assert "does_not_exist_999" in msg
    assert "insurance/does_not_exist_999.pdf" in msg  # 包含尝试路径


def test_all_group_a_doc_ids_resolve():
    questions = load_all_questions()
    assert len(questions) == 100
    result = build_group_doc_map(REPO_ROOT, questions)
    assert result["missing"] == []
    assert result["errors"] == []
    assert result["unique_doc_count"] > 0
    # 每条 mapping 字段齐全且指向存在的文件
    for m in result["mappings"]:
        assert m["source_type"] in ("pdf", "html", "txt")
        assert (REPO_ROOT / m["path"]).is_file()
