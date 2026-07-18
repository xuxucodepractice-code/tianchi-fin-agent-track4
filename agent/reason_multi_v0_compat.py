"""Fresh traced Multi reasoning with the exact v0 option prompt.

E006 uses this compatibility layer for both paired arms.  The control and
treatment therefore differ only in their selected evidence chunks; prompt
format, model parameters, parser, answer normalization, and call topology are
identical.  Trace metadata is additive and is not shown to the model.
"""

from __future__ import annotations

from typing import Any

from agent.normalize_answer import normalize_answer
from agent.qwen_client import QwenClient
from agent.reason_qwen import MODE_QWEN, _parse_judgment

E006_PIPELINE_VERSION = "v2s1-e006-option-doc-route"
V0_PROMPTS_COMMIT = "82041d0"
V0_PROMPTS_SOURCE_SHA256 = (
    "161392afcd1528f7bb2b0c8b04df08614aded2d8d6898bd0deae9f0cda35738d"
)

V0_SYSTEM_PROMPT = (
    "你是金融文档核查助手。你的唯一信息来源是用户提供的证据片段。"
    "禁止使用任何外部知识，禁止猜测。证据不足时必须回答 insufficient。"
    "你每次只判断一个选项，并只输出一个严格合法的 JSON 对象，不输出其他文字。"
)

V0_JUDGMENT_INSTRUCTION = """请判断下面这个选项的陈述是否被证据支持。

判断规则：
- support：证据明确支持该选项的全部关键内容（主体、数值、条件都要对得上）。
- refute：证据明确与该选项矛盾。
- insufficient：证据缺失、不完整或无法确认主体/数值/条件时，必须选 insufficient。
- 不得使用证据之外的任何知识。部分匹配不等于 support。

输出格式（严格 JSON，不要 markdown 代码块，不要多余文字）：
{{"option": "{option_key}", "judgment": "support|refute|insufficient", "rationale": "不超过50字的简短理由", "evidence_refs": [证据编号列表，如 [1, 2]，没有可引用证据则为 []]}}"""


def format_evidence_block_v0(evidence: list[dict[str, Any]]) -> str:
    """Reproduce commit 82041d0's evidence block byte-for-byte."""
    if not evidence:
        return "（无证据）"
    lines: list[str] = []
    for index, item in enumerate(evidence, start=1):
        location = f"doc_id={item['doc_id']}"
        if item.get("page") is not None:
            location += f" 第{item['page']}页"
        if item.get("section"):
            location += f" [{item['section'][:40]}]"
        lines.append(f"[证据{index}] ({location})\n{item['text']}")
    return "\n\n".join(lines)


def build_option_judgment_messages_v0(
    question: dict[str, Any],
    option_key: str,
    option_text: str,
    evidence: list[dict[str, Any]],
) -> list[dict[str, str]]:
    user_content = (
        f"题目（仅供理解选项语境，不作为证据）：{question.get('question', '')}\n\n"
        f"待判断选项 {option_key}：{option_text}\n\n"
        f"证据片段：\n{format_evidence_block_v0(evidence)}\n\n"
        f"{V0_JUDGMENT_INSTRUCTION.format(option_key=option_key)}"
    )
    return [
        {"role": "system", "content": V0_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _judge_option_with_v0_prompt(
    client: QwenClient,
    question: dict[str, Any],
    option_key: str,
    option_text: str,
    evidence: list[dict[str, Any]],
    *,
    arm: str,
) -> dict[str, Any]:
    messages = build_option_judgment_messages_v0(
        question, option_key, option_text, evidence
    )
    try:
        response = client.chat(
            messages,
            temperature=0.0,
            trace_context={
                "qid": question.get("qid", ""),
                "answer_format": question.get("answer_format", ""),
                "stage": f"e006_{arm}_v0_option_judgment",
                "option_key": option_key,
                "option_text": option_text,
                "evidence": evidence,
                "prompt_profile": "v0-82041d0",
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
            "error": f"Qwen 调用失败: {exc}",
        }
    parsed, error = _parse_judgment(response["content"], option_key)
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


def reason_multi_with_v0_prompt(
    question: dict[str, Any],
    retrieval: dict[str, Any],
    *,
    client: QwenClient,
    arm: str,
) -> dict[str, Any]:
    """Run exactly four independent option calls for one Multi question."""
    if arm not in {"control", "treatment"}:
        raise ValueError("E006 arm must be control or treatment")
    if question.get("answer_format") != "multi":
        raise ValueError("E006 v0 prompt compatibility runner is Multi-only")
    if sorted(question.get("options", {})) != list("ABCD"):
        raise ValueError("E006 requires exactly A/B/C/D options")

    judgments: dict[str, dict[str, Any]] = {}
    for option_key in sorted(question["options"]):
        option = retrieval["options"][option_key]
        judgments[option_key] = _judge_option_with_v0_prompt(
            client,
            question,
            option_key,
            option["option_text"],
            option["evidence"],
            arm=arm,
        )

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
        "model": client.model,
        "pipeline_version": E006_PIPELINE_VERSION,
        "experiment_id": "E006",
        "experiment_arm": arm,
        "prompt_profile": "v0-82041d0",
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
        "prompt_tokens": sum(int(item["prompt_tokens"]) for item in judgments.values()),
        "completion_tokens": sum(
            int(item["completion_tokens"]) for item in judgments.values()
        ),
        "total_tokens": sum(int(item["total_tokens"]) for item in judgments.values()),
    }
