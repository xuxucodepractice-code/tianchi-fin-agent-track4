"""加载 A 榜题目 JSON，并按 qid 查找题目。

数据来源：public_dataset_upload/questions/group_a/*.json
每个文件是一个 list，元素字段：
    qid, domain, split, question, options, answer_format, type, doc_ids

B 榜预留：B 榜题目不含 doc_ids，本模块不假设 doc_ids 一定存在，
缺失时以空列表兜底。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.paths import QUESTIONS_GROUP_A_DIR

Question = dict[str, Any]


def load_all_questions(questions_dir: Path = QUESTIONS_GROUP_A_DIR) -> list[Question]:
    """加载目录下所有题目 JSON，返回题目列表（按文件名、文件内顺序稳定排列）。"""
    if not questions_dir.is_dir():
        raise FileNotFoundError(f"题目目录不存在: {questions_dir}")

    questions: list[Question] = []
    for json_path in sorted(questions_dir.glob("*.json")):
        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"题目文件格式异常（应为 list）: {json_path}")
        for item in data:
            item.setdefault("doc_ids", [])  # B 榜无 doc_ids 时兜底
            item["_source_file"] = json_path.name
            questions.append(item)

    if not questions:
        raise ValueError(f"题目目录下没有加载到任何题目: {questions_dir}")
    return questions


def find_question_by_qid(
    qid: str, questions_dir: Path = QUESTIONS_GROUP_A_DIR
) -> Question:
    """按 qid 查找单道题目，找不到时报错并提示可用 qid 示例。"""
    questions = load_all_questions(questions_dir)
    for q in questions:
        if q.get("qid") == qid:
            return q
    sample = ", ".join(q["qid"] for q in questions[:5])
    raise KeyError(f"未找到 qid={qid}。示例可用 qid: {sample} ...（共 {len(questions)} 题）")


def load_questions_by_domain(
    domain: str, questions_dir: Path = QUESTIONS_GROUP_A_DIR
) -> list[Question]:
    """按 domain 加载题目，保持题目 JSON 内原始顺序。"""
    questions = [q for q in load_all_questions(questions_dir) if q.get("domain") == domain]
    if not questions:
        available = sorted({str(q.get("domain", "")) for q in load_all_questions(questions_dir)})
        raise KeyError(f"未找到 domain={domain}。可用 domain: {', '.join(available)}")
    return questions
