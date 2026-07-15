"""Validate completed Markdown label cards and export a structured result batch."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from agent.generate_labeling_packets import QUESTIONS_DIR, load_questions


FIELD_PATTERNS = {
    "answer": re.compile(r"^- 答案(?:（.*?）)?[：:][ \t]*([^\r\n]*)$", re.MULTILINE),
    "confidence": re.compile(r"^- 置信度(?:（.*?）)?[：:][ \t]*([^\r\n]*)$", re.MULTILINE),
    "evidence": re.compile(r"^- 决定性证据[：:][ \t]*([^\r\n]*)$", re.MULTILINE),
    "reason": re.compile(r"^- 简短理由[：:][ \t]*([^\r\n]*)$", re.MULTILINE),
    "labeler": re.compile(r"^- 标定人[：:][ \t]*([^\r\n]*)$", re.MULTILINE),
    "completed_at": re.compile(r"^- 完成时间[：:][ \t]*([^\r\n]*)$", re.MULTILINE),
}

VALID_CONFIDENCE = {"high", "medium", "low"}


def _field(text: str, name: str) -> str:
    match = FIELD_PATTERNS[name].search(text)
    return match.group(1).strip() if match else ""


def _canonical_answer(answer: str) -> str:
    answer = re.sub(r"[\s,，、;/]+", "", answer.upper())
    return "".join(sorted(set(answer))) if answer else ""


def validate_card(path: Path, question: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    text = path.read_text(encoding="utf-8")
    values = {name: _field(text, name) for name in FIELD_PATTERNS}
    errors: list[str] = []
    for name in ("answer", "confidence", "evidence", "reason", "labeler", "completed_at"):
        if not values[name]:
            errors.append(f"{path.name}: missing {name}")

    answer = _canonical_answer(values["answer"])
    valid_letters = set(question.get("options", {}))
    if not answer or not set(answer) <= valid_letters:
        errors.append(f"{path.name}: invalid answer {values['answer']!r}")
    elif question.get("answer_format") in {"tf", "mcq"} and len(answer) != 1:
        errors.append(f"{path.name}: {question.get('answer_format')} answer must be one letter")

    confidence = values["confidence"].lower()
    if confidence not in VALID_CONFIDENCE:
        errors.append(f"{path.name}: invalid confidence {values['confidence']!r}")

    return (
        {
            "qid": question["qid"],
            "answer_format": question.get("answer_format"),
            "answer": answer,
            "confidence": confidence,
            "decisive_evidence": values["evidence"],
            "reason": values["reason"],
            "labeler": values["labeler"],
            "completed_at": values["completed_at"],
            "source_card": path.name,
        },
        errors,
    )


def validate_batch(
    cards_dir: Path,
    selection_file: Path,
    questions_dir: Path = QUESTIONS_DIR,
) -> dict[str, Any]:
    selection = json.loads(selection_file.read_text(encoding="utf-8"))
    qids = selection.get("qids")
    if not isinstance(qids, list) or not all(isinstance(qid, str) for qid in qids):
        raise ValueError("selection file must contain a string qids list")
    questions = {question["qid"]: question for question in load_questions(questions_dir)}
    unknown = [qid for qid in qids if qid not in questions]
    if unknown:
        raise ValueError(f"unknown qids: {', '.join(unknown)}")

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    expected_cards = {f"{qid}_blind.md" for qid in qids}
    actual_cards = {path.name for path in cards_dir.glob("*_blind.md")}
    if actual_cards != expected_cards:
        errors.append(
            f"card set mismatch missing={sorted(expected_cards - actual_cards)} "
            f"extra={sorted(actual_cards - expected_cards)}"
        )
    for qid in qids:
        path = cards_dir / f"{qid}_blind.md"
        if not path.is_file():
            continue
        result, card_errors = validate_card(path, questions[qid])
        results.append(result)
        errors.extend(card_errors)
    return {
        "selection_id": selection.get("selection_id"),
        "complete": not errors and len(results) == len(qids),
        "expected_count": len(qids),
        "validated_count": len(results),
        "errors": errors,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cards-dir", type=Path, required=True)
    parser.add_argument("--selection-file", type=Path, required=True)
    parser.add_argument("--questions-dir", type=Path, default=QUESTIONS_DIR)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = validate_batch(args.cards_dir, args.selection_file, args.questions_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"selection={report['selection_id']} complete={report['complete']} "
        f"validated={report['validated_count']}/{report['expected_count']} "
        f"errors={len(report['errors'])}"
    )
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
