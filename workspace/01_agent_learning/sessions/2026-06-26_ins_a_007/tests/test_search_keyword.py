import subprocess
import sys
from pathlib import Path


def test_searches_keyword_in_pdf_and_prints_page_context():
    session_dir = Path(__file__).resolve().parents[1]
    repo_root = session_dir.parents[3]
    script_path = session_dir / "scripts" / "search_keyword.py"
    pdf_path = repo_root / "public_dataset_upload" / "raw" / "insurance" / "16.pdf"

    result = subprocess.run(
        [sys.executable, str(script_path), str(pdf_path), "保单贷款"],
        cwd=repo_root,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "keyword: 保单贷款" in result.stdout
    assert "page: 9" in result.stdout
    assert "经被保险人书面同意" in result.stdout
    assert "您可申请保单贷款功能" in result.stdout


def test_returns_error_when_keyword_has_no_matches():
    session_dir = Path(__file__).resolve().parents[1]
    repo_root = session_dir.parents[3]
    script_path = session_dir / "scripts" / "search_keyword.py"
    pdf_path = repo_root / "public_dataset_upload" / "raw" / "insurance" / "16.pdf"

    result = subprocess.run(
        [sys.executable, str(script_path), str(pdf_path), "不存在的关键词"],
        cwd=repo_root,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "No matches found" in result.stdout
