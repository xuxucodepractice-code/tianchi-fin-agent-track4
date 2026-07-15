"""写出提交产物：answer.csv、evidence.json、run_manifest.json。

answer.csv 官方格式：
    qid,answer,prompt_tokens,completion_tokens,total_tokens
    第一行数据为 summary 行（qid=summary, answer 为空），统计全局 Token。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from agent.paths import ANSWER_CSV_PATH, EVIDENCE_JSON_PATH, RUN_MANIFEST_PATH

ANSWER_CSV_COLUMNS = ["qid", "answer", "prompt_tokens", "completion_tokens", "total_tokens"]

# 每题结果记录的最小字段（由 run_submission 组装）：
#   qid, domain, question, options, answer_format, doc_ids,
#   answer, evidence, prompt_tokens, completion_tokens, total_tokens, mode
ResultRecord = dict[str, Any]


def write_answer_csv(
    results: list[ResultRecord], path: Path = ANSWER_CSV_PATH
) -> Path:
    """写 answer.csv，包含 summary 行 + 每题行。"""
    total_prompt = sum(r["prompt_tokens"] for r in results)
    total_completion = sum(r["completion_tokens"] for r in results)
    total = sum(r["total_tokens"] for r in results)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(ANSWER_CSV_COLUMNS)
        writer.writerow(["summary", "", total_prompt, total_completion, total])
        for r in results:
            writer.writerow(
                [r["qid"], r["answer"], r["prompt_tokens"], r["completion_tokens"], r["total_tokens"]]
            )
    return path


def write_evidence_json(
    results: list[ResultRecord], path: Path = EVIDENCE_JSON_PATH
) -> Path:
    """写 evidence.json：每题一条记录，保留题目上下文、检索证据、
    逐选项判断、答案与 Token。Task 1 基本字段保持不变，Task 5 起
    追加 retrieval / option_judgments / warnings / low_confidence / model。"""
    records = [
        {
            "qid": r["qid"],
            "domain": r["domain"],
            "question": r["question"],
            "options": r["options"],
            "answer_format": r["answer_format"],
            "doc_ids": r["doc_ids"],
            "answer": r["answer"],
            "evidence": r["evidence"],
            "retrieval": r.get("retrieval", {}),
            "option_judgments": r.get("option_judgments", {}),
            "warnings": r.get("warnings", []),
            "low_confidence": r.get("low_confidence", False),
            "prompt_tokens": r["prompt_tokens"],
            "completion_tokens": r["completion_tokens"],
            "total_tokens": r["total_tokens"],
            "mode": r["mode"],
            "model": r.get("model", ""),
            "pipeline_version": r.get("pipeline_version", "v0"),
            "tf_judgment": r.get("tf_judgment"),
            "source_kind": r.get("source_kind", "fresh"),
            "source_pipeline_version": r.get(
                "source_pipeline_version", r.get("pipeline_version", "v0")
            ),
            "source_run_id": r.get("source_run_id", ""),
        }
        for r in results
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return path


def write_run_manifest(manifest: dict[str, Any], path: Path = RUN_MANIFEST_PATH) -> Path:
    """写 run_manifest.json：单次运行的元数据。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return path
