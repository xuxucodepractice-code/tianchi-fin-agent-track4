"""Generate blind local-labeling cards from the public question files.

The generated cards deliberately exclude pipeline answers, cached rationales, and
historical labels.  They are evaluation inputs, never inference inputs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Sequence

from agent.paths import REPO_ROOT


QUESTIONS_DIR = REPO_ROOT / "public_dataset_upload" / "questions" / "group_a"
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "workspace"
    / "03_baseline_improvement"
    / "evaluation"
    / "blind_labeling"
    / "tier1_mcq"
)


def load_questions(questions_dir: Path = QUESTIONS_DIR) -> list[dict]:
    questions: list[dict] = []
    for path in sorted(questions_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"Question file must contain a list: {path}")
        questions.extend(payload)
    return questions


def render_card(question: dict) -> str:
    qid = question["qid"]
    options = question.get("options", {})
    doc_ids = question.get("doc_ids", [])

    option_lines = "\n".join(f"- {key}：{value}" for key, value in options.items())
    doc_lines = "\n".join(f"- `{doc_id}`" for doc_id in doc_ids)
    answer_format = question.get("answer_format")
    if answer_format == "tf":
        audit_heading = "题干逐事实核对"
        audit_table = """| fact_id | 待核事实（标定人拆分） | 支持 / 反驳 | 证据定位 | 备注 |
| --- | --- | --- | --- | --- |
| F1 |  |  |  |  |
| F2 |  |  |  |  |
| F3 |  |  |  |  |
| F4 |  |  |  |  |"""
    else:
        audit_heading = "逐选项逐要素核对"
        audit_rows = "\n".join(
            f"| {key} | {value} |  |  |  |" for key, value in options.items()
        )
        audit_table = f"""| 选项 | 原文 | 支持 / 排除 | 证据定位（doc_id + 页码/chunk_id） | 理由或计算 |
| --- | --- | --- | --- | --- |
{audit_rows}"""

    return f"""# Blind Label Card: {qid}

> 提交答案前，不得查看历史提交、推理缓存、审查报告、既有本地标签或任何 pipeline 答案。

## 题目

{question['question']}

{option_lines}

## 必查原始文档

{doc_lines}

## {audit_heading}

{audit_table}

## 独立结论（标定人填写）

- 答案：
- 置信度（high / medium / low）：
- 决定性证据：
- 简短理由：
- 标定人：
- 完成时间：
"""


def write_packets(
    questions: Iterable[dict],
    output_dir: Path,
    *,
    answer_format: str = "mcq",
    qids: Sequence[str] | None = None,
    overwrite: bool = False,
) -> list[Path]:
    question_by_qid = {question["qid"]: question for question in questions}
    if qids is not None:
        missing = sorted(set(qids) - set(question_by_qid))
        if missing:
            raise ValueError(f"Unknown qids in selection: {', '.join(missing)}")
        selected = [question_by_qid[qid] for qid in qids]
    else:
        selected = sorted(
            (
                question
                for question in question_by_qid.values()
                if question.get("answer_format") == answer_format
            ),
            key=lambda question: question["qid"],
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for question in selected:
        path = output_dir / f"{question['qid']}_blind.md"
        if path.exists() and not overwrite:
            raise FileExistsError(
                f"Refusing to overwrite a possibly completed labeling card: {path}"
            )
        path.write_text(render_card(question), encoding="utf-8")
        written.append(path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions-dir", type=Path, default=QUESTIONS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--answer-format",
        choices=("mcq", "tf", "multi"),
        default="mcq",
        help="generate every question of this format when no selection file is given",
    )
    parser.add_argument(
        "--selection-file",
        type=Path,
        help="JSON object with an ordered qids list; overrides --answer-format filtering",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing cards (unsafe after labeling has started)",
    )
    args = parser.parse_args()

    qids = None
    if args.selection_file:
        selection = json.loads(args.selection_file.read_text(encoding="utf-8"))
        qids = selection.get("qids")
        if not isinstance(qids, list) or not all(isinstance(qid, str) for qid in qids):
            raise ValueError("selection file must contain an ordered string list named 'qids'")

    written = write_packets(
        load_questions(args.questions_dir),
        args.output_dir,
        answer_format=args.answer_format,
        qids=qids,
        overwrite=args.force,
    )
    print(f"generated={len(written)} output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
