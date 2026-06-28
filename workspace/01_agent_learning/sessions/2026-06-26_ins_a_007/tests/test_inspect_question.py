import subprocess
import sys
from pathlib import Path


def test_prints_ins_a_007_key_fields():
    session_dir = Path(__file__).resolve().parents[1]
    script_path = session_dir / "scripts" / "inspect_question.py"

    result = subprocess.run(
        [sys.executable, str(script_path), "ins_a_007"],
        cwd=session_dir.parents[3],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "qid: ins_a_007" in result.stdout
    assert "domain: insurance" in result.stdout
    assert "answer_format: multi" in result.stdout
    assert "关于“保单贷款”，以下哪些说法正确？" in result.stdout
    assert "A. 平安智盈金生允许保单贷款，最高为现金价值的80%" in result.stdout
    assert "doc_ids:" in result.stdout
    assert "- 1" in result.stdout
    assert "- 2" in result.stdout
    assert "- 16" in result.stdout
