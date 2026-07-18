"""E007R1 Multi option judgments with control numeric refs or opaque EV refs."""

from __future__ import annotations

import json
from typing import Any

from agent.normalize_answer import normalize_answer
from agent.qwen_client import QwenClient
from agent.reason_qwen import MODE_QWEN, VALID_JUDGMENTS, _parse_judgment
from agent.reason_multi_v0_compat import V0_SYSTEM_PROMPT

E007_PIPELINE_VERSION = "v2s1-e006-route-e007r1-reference-integrity"
PROMPT_PROFILE = "e007r1-v0-judgment-reference-ablation"

CONTROL_INSTRUCTION = """请判断下面这个选项的陈述是否被证据支持。

判断规则：
- support：证据明确支持该选项的全部关键内容（主体、数值、条件都要对得上）。
- refute：证据明确与该选项矛盾。
- insufficient：证据缺失、不完整或无法确认主体/数值/条件时，必须选 insufficient。
- 不得使用证据之外的任何知识。部分匹配不等于 support。

输出格式（严格 JSON，不要 markdown 代码块，不要多余文字）：
{{"option": "{option_key}", "judgment": "support|refute|insufficient", "rationale": "不超过50字的简短理由", "evidence_refs": [证据编号列表，如 [1, 2]，没有可引用证据则为 []]}}"""

TREATMENT_INSTRUCTION = """请判断下面这个选项的陈述是否被证据支持。

判断规则：
- support：证据明确支持该选项的全部关键内容（主体、数值、条件都要对得上）。
- refute：证据明确与该选项矛盾。
- insufficient：证据缺失、不完整或无法确认主体/数值/条件时，必须选 insufficient。
- 不得使用证据之外的任何知识。部分匹配不等于 support。

输出格式（严格 JSON，不要 markdown 代码块，不要多余文字）：
{{"option": "{option_key}", "judgment": "support|refute|insufficient", "rationale": "不超过50字的简短理由", "evidence_refs": [证据ID字符串列表，如 ["EV1", "EV2"]，没有可引用证据则为 []]}}"""


def format_evidence_block(
    evidence: list[dict[str, Any]], *, arm: str
) -> str:
    if arm not in {"control", "treatment"}:
        raise ValueError(f"unknown E007R1 arm: {arm!r}")
    if not evidence:
        return "（无证据）"
    lines: list[str] = []
    for index, item in enumerate(evidence, start=1):
        location = f"doc_id={item['doc_id']}"
        if item.get("page") is not None:
            location += f" 第{item['page']}页"
        if item.get("section"):
            location += f" [{item['section'][:40]}]"
        marker = f"证据{index}" if arm == "control" else f"EV{index}"
        lines.append(f"[{marker}] ({location})\n{item['text']}")
    return "\n\n".join(lines)


def build_option_messages(
    question: dict[str, Any],
    option_key: str,
    option_text: str,
    evidence: list[dict[str, Any]],
    *,
    arm: str,
) -> list[dict[str, str]]:
    instruction = CONTROL_INSTRUCTION if arm == "control" else TREATMENT_INSTRUCTION
    user_content = (
        f"题目（仅供理解选项语境，不作为证据）：{question.get('question', '')}\n\n"
        f"待判断选项 {option_key}：{option_text}\n\n"
        f"证据片段：\n{format_evidence_block(evidence, arm=arm)}\n\n"
        f"{instruction.format(option_key=option_key)}"
    )
    return [
        {"role": "system", "content": V0_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def parse_treatment_judgment(
    content: str, option_key: str, *, evidence_count: int
) -> tuple[dict[str, Any], str | None]:
    """Strictly parse one standalone treatment JSON object without repair."""
    try:
        obj = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        return (
            {"judgment": "error", "rationale": "", "evidence_refs": []},
            f"standalone JSON required: {exc}",
        )
    if not isinstance(obj, dict):
        return (
            {"judgment": "error", "rationale": "", "evidence_refs": []},
            "standalone JSON must be an object",
        )
    required_keys = {"option", "judgment", "rationale", "evidence_refs"}
    if set(obj) != required_keys:
        return (
            {"judgment": "error", "rationale": "", "evidence_refs": []},
            f"schema keys differ: {sorted(map(str, obj))}",
        )
    if obj["option"] != option_key:
        return (
            {"judgment": "error", "rationale": "", "evidence_refs": []},
            f"option identity mismatch: {obj['option']!r} != {option_key!r}",
        )
    if not isinstance(obj["judgment"], str) or obj["judgment"] not in VALID_JUDGMENTS:
        return (
            {"judgment": "error", "rationale": "", "evidence_refs": []},
            f"invalid judgment: {obj['judgment']!r}",
        )
    if not isinstance(obj["rationale"], str):
        return (
            {"judgment": "error", "rationale": "", "evidence_refs": []},
            "rationale must be a string",
        )
    refs = obj["evidence_refs"]
    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
        return (
            {"judgment": "error", "rationale": obj["rationale"], "evidence_refs": []},
            "evidence_refs must be a string array",
        )
    if len(refs) != len(set(refs)):
        return (
            {"judgment": "error", "rationale": obj["rationale"], "evidence_refs": refs},
            f"duplicate evidence_refs are forbidden: {refs!r}",
        )
    allowed = {f"EV{index}" for index in range(1, evidence_count + 1)}
    unknown = [ref for ref in refs if ref not in allowed]
    if unknown:
        return (
            {"judgment": "error", "rationale": obj["rationale"], "evidence_refs": refs},
            f"unknown or unrendered evidence_refs: {unknown!r}",
        )
    return (
        {
            "judgment": obj["judgment"],
            "rationale": obj["rationale"],
            "evidence_refs": refs,
        },
        None,
    )


def judge_option(
    client: QwenClient,
    question: dict[str, Any],
    option_key: str,
    option_text: str,
    evidence: list[dict[str, Any]],
    *,
    arm: str,
) -> dict[str, Any]:
    messages = build_option_messages(
        question, option_key, option_text, evidence, arm=arm
    )
    try:
        response = client.chat(
            messages,
            temperature=0.0,
            trace_context={
                "qid": question.get("qid", ""),
                "answer_format": question.get("answer_format", ""),
                "stage": f"e007r1_{arm}_option_judgment",
                "option_key": option_key,
                "option_text": option_text,
                "evidence": evidence,
                "prompt_profile": PROMPT_PROFILE,
                "reference_profile": (
                    "numeric_evidence_refs" if arm == "control" else "opaque_ev_refs"
                ),
            },
        )
    except Exception as exc:
        return {
            "judgment": "error",
            "rationale": "",
            "evidence_refs": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "error": f"Qwen call failed: {exc}",
        }
    if arm == "control":
        parsed, error = _parse_judgment(response["content"], option_key)
    elif arm == "treatment":
        parsed, error = parse_treatment_judgment(
            response["content"], option_key, evidence_count=len(evidence)
        )
    else:
        raise ValueError(f"unknown E007R1 arm: {arm!r}")
    return {
        **parsed,
        "prompt_tokens": response["prompt_tokens"],
        "completion_tokens": response["completion_tokens"],
        "total_tokens": response["total_tokens"],
        "trace_call_id": response.get("trace_call_id"),
        "trace_run_id": response.get("trace_run_id"),
        "local_request_id": response.get("local_request_id"),
        "provider_request_id": response.get("provider_request_id"),
        "retry_count": int(response.get("retry_count") or 0),
        "error": error,
    }


def build_question_result(
    question: dict[str, Any],
    judgments: dict[str, dict[str, Any]],
    *,
    arm: str,
) -> dict[str, Any]:
    normalized = normalize_answer("multi", judgments, question["options"])
    warnings = list(normalized["warnings"])
    for option_key, judgment in sorted(judgments.items()):
        if judgment.get("error"):
            warnings.append(f"选项 {option_key}: {judgment['error']}")
    trace_run_ids = sorted(
        {
            str(judgment.get("trace_run_id"))
            for judgment in judgments.values()
            if judgment.get("trace_run_id")
        }
    )
    return {
        "qid": question["qid"],
        "domain": question.get("domain", ""),
        "answer_format": "multi",
        "mode": MODE_QWEN,
        "model": "qwen-plus",
        "pipeline_version": E007_PIPELINE_VERSION,
        "experiment_id": "E007R1",
        "experiment_arm": arm,
        "prompt_profile": PROMPT_PROFILE,
        "question": question.get("question", ""),
        "options": question.get("options", {}),
        "doc_ids": question.get("doc_ids", []),
        "option_judgments": judgments,
        "answer": normalized["answer"],
        "answer_derivation": {
            "method": "agent.normalize_answer.normalize_answer",
            "answer_format": "multi",
            "input_judgments": {
                key: {
                    "judgment": judgment.get("judgment"),
                    "evidence_refs": judgment.get("evidence_refs", []),
                    "error": judgment.get("error"),
                }
                for key, judgment in sorted(judgments.items())
            },
            "output_answer": normalized["answer"],
            "warnings": warnings,
            "low_confidence": normalized["low_confidence"],
        },
        "trace_run_id": trace_run_ids[0] if len(trace_run_ids) == 1 else None,
        "warnings": warnings,
        "low_confidence": normalized["low_confidence"],
        "prompt_tokens": sum(int(item.get("prompt_tokens") or 0) for item in judgments.values()),
        "completion_tokens": sum(
            int(item.get("completion_tokens") or 0) for item in judgments.values()
        ),
        "total_tokens": sum(int(item.get("total_tokens") or 0) for item in judgments.values()),
    }
