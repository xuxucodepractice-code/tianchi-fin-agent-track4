"""基于检索证据的 Qwen 逐选项判断（Task 5）。

流程：question + retrieval(Task 4) -> 每个选项一次 Qwen 调用 ->
解析 JSON 判断 -> normalize_answer 合成答案 -> 汇总 token。

模式：
    MODE_QWEN     = "qwen"          正式推理，必须真实调用 Qwen API
    MODE_DRY_RUN  = "dry_run_mock"  接口联调用，不调用 API，不是正式答案
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent.normalize_answer import normalize_answer
from agent.paths import PROCESSED_DATA_DIR
from agent.prompts import build_option_judgment_messages
from agent.qwen_client import QwenClient

MODE_QWEN = "qwen"
MODE_DRY_RUN = "dry_run_mock"

REASONING_SAMPLES_DIR = PROCESSED_DATA_DIR / "reasoning_samples"

VALID_JUDGMENTS = {"support", "refute", "insufficient"}


# ---------------------------------------------------------------- JSON 解析


def extract_json_from_text(text: str) -> dict[str, Any] | None:
    """从模型输出提取 JSON 对象：先直接 loads，失败再扫描首个平衡大括号块。"""
    text = text.strip()
    # 去掉可能的 markdown 代码块
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                        return obj if isinstance(obj, dict) else None
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def _parse_judgment(content: str, option_key: str) -> tuple[dict[str, Any], str | None]:
    """解析单选项判断输出。返回 (judgment_dict, error)。解析失败不抛异常。"""
    obj = extract_json_from_text(content)
    if obj is None:
        return (
            {"judgment": "error", "rationale": "", "evidence_refs": []},
            f"模型输出不是合法 JSON: {content[:200]!r}",
        )
    judgment = str(obj.get("judgment", "")).strip().lower()
    if judgment not in VALID_JUDGMENTS:
        return (
            {"judgment": "error", "rationale": str(obj.get("rationale", ""))[:100], "evidence_refs": []},
            f"judgment 取值非法: {judgment!r}",
        )
    refs = obj.get("evidence_refs") or []
    if not isinstance(refs, list):
        refs = []
    refs = [int(r) for r in refs if isinstance(r, (int, float, str)) and str(r).isdigit()]
    return (
        {
            "judgment": judgment,
            "rationale": str(obj.get("rationale", ""))[:200],
            "evidence_refs": refs,
        },
        None,
    )


# ---------------------------------------------------------------- 单选项判断


def judge_option_with_qwen(
    client: QwenClient,
    question: dict[str, Any],
    option_key: str,
    option_text: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """调用 Qwen 判断单个选项。API/解析失败记入 error，不抛异常。"""
    messages = build_option_judgment_messages(question, option_key, option_text, evidence)
    try:
        resp = client.chat(messages, temperature=0.0)
    except Exception as exc:
        return {
            "judgment": "error",
            "rationale": "",
            "evidence_refs": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "error": f"Qwen 调用失败: {exc}",
        }
    parsed, error = _parse_judgment(resp["content"], option_key)
    return {
        **parsed,
        "prompt_tokens": resp["prompt_tokens"],
        "completion_tokens": resp["completion_tokens"],
        "total_tokens": resp["total_tokens"],
        "error": error,
    }


# ---------------------------------------------------------------- 整题推理


def _assemble_result(
    question: dict[str, Any],
    retrieval: dict[str, Any],
    option_judgments: dict[str, dict[str, Any]],
    mode: str,
    model: str,
) -> dict[str, Any]:
    normalized = normalize_answer(
        question["answer_format"], option_judgments, question.get("options", {})
    )
    warnings = list(normalized["warnings"])
    for key, j in sorted(option_judgments.items()):
        if j.get("error"):
            warnings.append(f"选项 {key}: {j['error']}")
    return {
        "qid": question["qid"],
        "domain": question.get("domain", ""),
        "answer_format": question.get("answer_format", ""),
        "mode": mode,
        "model": model,
        "question": question.get("question", ""),
        "options": question.get("options", {}),
        "doc_ids": question.get("doc_ids", []),
        "option_judgments": option_judgments,
        "answer": normalized["answer"],
        "warnings": warnings,
        "low_confidence": normalized["low_confidence"],
        "prompt_tokens": sum(j["prompt_tokens"] for j in option_judgments.values()),
        "completion_tokens": sum(j["completion_tokens"] for j in option_judgments.values()),
        "total_tokens": sum(j["total_tokens"] for j in option_judgments.values()),
    }


def reason_question_with_qwen(
    question: dict[str, Any],
    retrieval: dict[str, Any],
    client: QwenClient | None = None,
) -> dict[str, Any]:
    """正式模式：对每个选项调用 Qwen，合成答案。client 可注入（测试用 fake）。"""
    if client is None:
        client = QwenClient()
    option_judgments: dict[str, dict[str, Any]] = {}
    for key in sorted(question.get("options", {})):
        opt = retrieval["options"][key]
        option_judgments[key] = judge_option_with_qwen(
            client, question, key, opt["option_text"], opt["evidence"]
        )
    return _assemble_result(question, retrieval, option_judgments, MODE_QWEN, client.model)


def reason_question_dry_run(
    question: dict[str, Any], retrieval: dict[str, Any]
) -> dict[str, Any]:
    """DRY-RUN：不调用任何 API。所有选项 judgment=insufficient、token=0。
    产出仅用于接口联调，mode=dry_run_mock，不是正式答案。"""
    option_judgments = {
        key: {
            "judgment": "insufficient",
            "rationale": "dry-run 占位：未调用 Qwen",
            "evidence_refs": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "error": None,
        }
        for key in sorted(question.get("options", {}))
    }
    return _assemble_result(question, retrieval, option_judgments, MODE_DRY_RUN, "none")


def save_reasoning_sample(result: dict[str, Any], path: Path | None = None) -> Path:
    if path is None:
        path = REASONING_SAMPLES_DIR / f"{result['qid']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return path
