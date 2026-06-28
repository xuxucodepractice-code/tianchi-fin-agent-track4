#!/usr/bin/env python3
"""Print one group_a question by qid."""

import argparse
import json
from pathlib import Path


def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "public_dataset_upload").exists():
            return parent
    raise FileNotFoundError("Cannot find project root with public_dataset_upload/")


def load_group_a_questions(repo_root: Path) -> list[dict]:
    questions_dir = repo_root / "public_dataset_upload" / "questions" / "group_a"
    questions = []

    for json_path in sorted(questions_dir.glob("*.json")):
        with json_path.open("r", encoding="utf-8") as file:
            questions.extend(json.load(file))

    return questions


def find_question(questions: list[dict], qid: str) -> dict | None:
    for question in questions:
        if question.get("qid") == qid:
            return question
    return None


def print_question(question: dict) -> None:
    print(f"qid: {question.get('qid')}")
    print(f"domain: {question.get('domain')}")
    print(f"answer_format: {question.get('answer_format')}")
    print()

    print("question:")
    print(question.get("question"))
    print()

    print("options:")
    for key, value in question.get("options", {}).items():
        print(f"{key}. {value}")
    print()

    print("doc_ids:")
    for doc_id in question.get("doc_ids", []):
        print(f"- {doc_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a group_a question by qid.")
    parser.add_argument("qid", help="Question id, for example: ins_a_007")
    args = parser.parse_args()

    repo_root = find_repo_root()
    questions = load_group_a_questions(repo_root)
    question = find_question(questions, args.qid)

    if question is None:
        print(f"Question not found: {args.qid}")
        return 1

    print_question(question)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
