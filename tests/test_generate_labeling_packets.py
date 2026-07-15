import json
from pathlib import Path

import pytest

from agent.generate_labeling_packets import load_questions, render_card, write_packets


def test_load_and_generate_blind_mcq_packets(tmp_path: Path) -> None:
    questions_dir = tmp_path / "questions"
    questions_dir.mkdir()
    questions = [
        {
            "qid": "sample_mcq",
            "domain": "sample",
            "question": "Which option?",
            "options": {"A": "one", "B": "two"},
            "answer_format": "mcq",
            "doc_ids": ["doc_1"],
        },
        {
            "qid": "sample_tf",
            "domain": "sample",
            "question": "True?",
            "options": {"A": "yes", "B": "no"},
            "answer_format": "tf",
            "doc_ids": ["doc_2"],
        },
    ]
    (questions_dir / "sample.json").write_text(
        json.dumps(questions, ensure_ascii=False), encoding="utf-8"
    )

    output_dir = tmp_path / "packets"
    written = write_packets(load_questions(questions_dir), output_dir)

    assert [path.name for path in written] == ["sample_mcq_blind.md"]
    content = written[0].read_text(encoding="utf-8")
    assert "Which option?" in content
    assert "`doc_1`" in content
    assert "pipeline 答案" in content
    assert "gold_answer" not in content

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        write_packets(load_questions(questions_dir), output_dir)


def test_render_card_does_not_include_unrelated_answer_fields() -> None:
    card = render_card(
        {
            "qid": "sample_mcq",
            "question": "Question",
            "options": {"A": "one"},
            "doc_ids": ["doc"],
            "answer": "A",
        }
    )

    assert "Question" in card
    assert "- A：one" in card
    assert "answer: A" not in card


def test_selected_packets_preserve_order_and_reject_unknown_qids(tmp_path: Path) -> None:
    questions = [
        {
            "qid": "tf_1",
            "question": "Claim",
            "options": {"A": "correct", "B": "incorrect"},
            "answer_format": "tf",
            "doc_ids": ["doc"],
        },
        {
            "qid": "multi_1",
            "question": "Select",
            "options": {"A": "one", "B": "two"},
            "answer_format": "multi",
            "doc_ids": ["doc"],
        },
    ]

    written = write_packets(questions, tmp_path, qids=["multi_1", "tf_1"])
    assert [path.name for path in written] == ["multi_1_blind.md", "tf_1_blind.md"]
    assert "题干逐事实核对" in written[1].read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown qids"):
        write_packets(questions, tmp_path / "other", qids=["missing"])
