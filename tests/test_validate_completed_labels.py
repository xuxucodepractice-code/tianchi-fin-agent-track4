import json
from pathlib import Path

from agent.validate_completed_labels import validate_batch


def _write_fixture(tmp_path: Path, *, completed: bool) -> tuple[Path, Path, Path]:
    questions_dir = tmp_path / "questions"
    cards_dir = tmp_path / "cards"
    questions_dir.mkdir()
    cards_dir.mkdir()
    question = {
        "qid": "q1",
        "answer_format": "multi",
        "options": {"A": "one", "B": "two", "C": "three"},
    }
    (questions_dir / "questions.json").write_text(json.dumps([question]), encoding="utf-8")
    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps({"selection_id": "batch", "qids": ["q1"]}), encoding="utf-8"
    )
    values = (
        "- 答案：CA\n"
        "- 置信度（high / medium / low）：high\n"
        "- 决定性证据：doc 第 1 页\n"
        "- 简短理由：逐项核对完成\n"
        "- 标定人：Alice\n"
        "- 完成时间：2026-07-14\n"
        if completed
        else "- 答案：\n- 置信度（high / medium / low）：\n"
    )
    (cards_dir / "q1_blind.md").write_text(values, encoding="utf-8")
    return cards_dir, selection, questions_dir


def test_completed_batch_is_canonicalized_and_accepted(tmp_path: Path):
    cards, selection, questions = _write_fixture(tmp_path, completed=True)
    result = validate_batch(cards, selection, questions)
    assert result["complete"] is True
    assert result["results"][0]["answer"] == "AC"


def test_incomplete_batch_fails_closed(tmp_path: Path):
    cards, selection, questions = _write_fixture(tmp_path, completed=False)
    result = validate_batch(cards, selection, questions)
    assert result["complete"] is False
    assert result["errors"]
