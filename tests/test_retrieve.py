"""检索模块测试（Task 4）。

前置：需先存在 processed_data/chunks.jsonl（Task 3 产物）。
运行：python -m pytest tests/test_retrieve.py -q
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys

import pytest

from agent.load_questions import find_question_by_qid
from agent.paths import PROCESSED_DATA_DIR, REPO_ROOT
from agent.query_terms import extract_terms_from_text
from agent.retrieve import (
    CHUNKS_PATH,
    load_chunks,
    retrieve_for_question,
)

PARSE_REPORT_PATH = PROCESSED_DATA_DIR / "parse_report.json"
SAMPLE_OUTPUT = PROCESSED_DATA_DIR / "retrieval_samples" / "ins_a_007.json"

EVIDENCE_REQUIRED_FIELDS = [
    "chunk_id", "doc_id", "source_type", "source_path",
    "page", "section", "text", "score", "matched_terms",
]


def _md5(path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def task3_md5_snapshot():
    """快照 Task 3 产物指纹，模块级测试结束后校验未被修改。"""
    before = {"chunks": _md5(CHUNKS_PATH), "report": _md5(PARSE_REPORT_PATH)}
    yield before
    assert _md5(CHUNKS_PATH) == before["chunks"], "chunks.jsonl 被修改！"
    assert _md5(PARSE_REPORT_PATH) == before["report"], "parse_report.json 被修改！"


@pytest.fixture(scope="module")
def chunks(task3_md5_snapshot):
    return load_chunks()


@pytest.fixture(scope="module")
def ins_a_007_result(chunks):
    question = find_question_by_qid("ins_a_007")
    return retrieve_for_question(question, chunks, top_k=5)


# ------------------------------------------------- 1. query terms


def test_query_terms_extracts_loan_and_percentage():
    terms = extract_terms_from_text("保单贷款，最高为现金价值的80%")
    assert "保单贷款" in terms or "贷款" in terms
    assert "80%" in terms


# ------------------------------------------------- 2. load_chunks


def test_load_chunks_returns_non_empty(chunks):
    assert isinstance(chunks, list)
    assert len(chunks) > 0


# ------------------------------------------------- 3-8. 检索结果


def test_every_option_has_evidence_field(ins_a_007_result):
    options = ins_a_007_result["options"]
    assert set(options) == {"A", "B", "C", "D"}
    for opt in options.values():
        assert "evidence" in opt
        assert "query_terms" in opt and opt["query_terms"]
        assert "option_text" in opt


def test_ins_a_007_evidence_only_from_given_doc_ids(ins_a_007_result):
    assert ins_a_007_result["doc_ids"] == ["1", "2", "16"]
    for opt in ins_a_007_result["options"].values():
        for ev in opt["evidence"]:
            assert ev["doc_id"] in {"1", "2", "16"}


def test_ins_a_007_matches_loan_terms(ins_a_007_result):
    loan_terms = {"保单贷款", "贷款", "借款"}
    hit = any(
        loan_terms & set(ev["matched_terms"])
        for opt in ins_a_007_result["options"].values()
        for ev in opt["evidence"]
    )
    assert hit, "应至少有一个选项的 matched_terms 命中 保单贷款/贷款/借款"


def test_evidence_sorted_by_score_desc(ins_a_007_result):
    for opt in ins_a_007_result["options"].values():
        scores = [ev["score"] for ev in opt["evidence"]]
        assert scores == sorted(scores, reverse=True)


def test_evidence_has_required_fields(ins_a_007_result):
    for opt in ins_a_007_result["options"].values():
        for ev in opt["evidence"]:
            for field in EVIDENCE_REQUIRED_FIELDS:
                assert field in ev, f"evidence 缺少字段 {field}"
            assert ev["text"].strip()
            assert ev["matched_terms"], "matched_terms 为空的 chunk 不应进入结果"


def test_top_k_respected(chunks):
    question = find_question_by_qid("ins_a_007")
    result = retrieve_for_question(question, chunks, top_k=2)
    for opt in result["options"].values():
        assert len(opt["evidence"]) <= 2


# ------------------------------------------------- 9-11. CLI 行为


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "agent.retrieve", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_cli_unknown_qid_returns_nonzero():
    proc = _run_cli("--qid", "no_such_qid_xyz")
    assert proc.returncode != 0
    assert "no_such_qid_xyz" in proc.stderr


def test_cli_missing_chunks_returns_nonzero_with_hint(tmp_path):
    proc = _run_cli("--qid", "ins_a_007", "--chunks", str(tmp_path / "nope.jsonl"))
    assert proc.returncode != 0
    assert "parse_documents" in proc.stderr  # 提示先运行解析


def test_cli_writes_valid_sample_json():
    proc = _run_cli(
        "--qid", "ins_a_007", "--top-k", "5",
        "--output", "processed_data/retrieval_samples/ins_a_007.json",
    )
    assert proc.returncode == 0
    assert SAMPLE_OUTPUT.is_file()
    with SAMPLE_OUTPUT.open("r", encoding="utf-8") as f:
        data = json.load(f)  # 必须是合法 JSON
    assert data["qid"] == "ins_a_007"
    assert data["top_k"] == 5


# ------------------------------------------------- 12. Task 3 产物不变
# 由 task3_md5_snapshot fixture 在模块级自动校验（teardown 时断言 md5 未变）。
