import subprocess
import sys
from pathlib import Path


def test_maps_insurance_doc_id_to_raw_pdf_path():
    session_dir = Path(__file__).resolve().parents[1]
    script_path = session_dir / "scripts" / "map_doc_id.py"

    result = subprocess.run(
        [sys.executable, str(script_path), "insurance", "1"],
        cwd=session_dir.parents[3],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "public_dataset_upload/raw/insurance/1.pdf" in result.stdout


def test_returns_error_when_raw_file_does_not_exist():
    session_dir = Path(__file__).resolve().parents[1]
    script_path = session_dir / "scripts" / "map_doc_id.py"

    result = subprocess.run(
        [sys.executable, str(script_path), "insurance", "999"],
        cwd=session_dir.parents[3],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "Raw file not found" in result.stdout
