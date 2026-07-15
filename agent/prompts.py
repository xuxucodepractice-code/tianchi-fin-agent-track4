"""Evidence-grounded 逐选项判断 prompt（Task 5）。

原则：Qwen 只能依据给定 evidence 判断，禁止外部知识与猜测；
每次只判断一个选项；输出严格 JSON。
"""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = (
    "你是金融文档核查助手。你的唯一信息来源是用户提供的证据片段。"
    "禁止使用任何外部知识，禁止猜测。证据不足时必须回答 insufficient。"
    "你每次只判断一个选项，并只输出一个严格合法的 JSON 对象，不输出其他文字。"
)

_JUDGMENT_INSTRUCTION = """请判断下面这个选项的陈述是否被证据支持。

判断规则：
- support：证据明确支持该选项的全部关键内容（主体、数值、条件都要对得上）。
- refute：证据明确与该选项矛盾。
- insufficient：证据缺失、不完整或无法确认主体/数值/条件时，必须选 insufficient。
- 不得使用证据之外的任何知识。部分匹配不等于 support。

输出格式（严格 JSON，不要 markdown 代码块，不要多余文字）：
{{"option": "{option_key}", "judgment": "support|refute|insufficient", "rationale": "不超过50字的简短理由", "evidence_refs": [证据编号列表，如 [1, 2]，没有可引用证据则为 []]}}"""

_TF_JUDGMENT_INSTRUCTION = """请判断下面这条判断题陈述是否被证据支持。

判断规则：
- true：整条陈述被证据支持；若陈述包含多个事实点，必须全部为真。
- false：任一关键事实点被证据明确否定，或题干的比较/数值方向与证据矛盾。
- uncertain：证据缺失、不完整，或无法同时覆盖所有关键事实点。
- 复合陈述必须先拆点，逐点判断；不得因为只验证了一半事实点就输出 true。
- 不得使用证据之外的任何知识。

输出格式（严格 JSON，不要 markdown 代码块，不要多余文字）：
{"verdict": "true|false|uncertain", "fact_checks": [{"claim": "拆出的事实点", "verdict": "true|false|uncertain", "evidence_refs": [证据编号列表]}], "rationale": "不超过80字的简短理由"}"""


def format_evidence_block(evidence: list[dict[str, Any]]) -> str:
    """把 evidence 列表格式化为编号引用块（编号从 1 开始，供 evidence_refs 引用）。"""
    if not evidence:
        return "（无证据）"
    lines = []
    for i, ev in enumerate(evidence, start=1):
        loc = ev.get("source_header")
        if not loc:
            loc = f"doc_id={ev['doc_id']}"
            if ev.get("page") is not None:
                loc += f" 第{ev['page']}页"
            if ev.get("section"):
                loc += f" [{ev['section'][:40]}]"
        lines.append(f"[证据{i}] {loc}\n{ev['text']}")
    return "\n\n".join(lines)


def build_option_judgment_messages(
    question: dict[str, Any],
    option_key: str,
    option_text: str,
    evidence: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """构造单选项判断的 messages。"""
    user_content = (
        f"题目（仅供理解选项语境，不作为证据）：{question.get('question', '')}\n\n"
        f"待判断选项 {option_key}：{option_text}\n\n"
        f"证据片段：\n{format_evidence_block(evidence)}\n\n"
        f"{_JUDGMENT_INSTRUCTION.format(option_key=option_key)}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def build_tf_judgment_messages(
    question: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    extra_instruction: str | None = None,
) -> list[dict[str, str]]:
    """构造 tf 题干级判断 messages。"""
    instruction = _TF_JUDGMENT_INSTRUCTION
    if extra_instruction:
        instruction = f"{instruction}\n\n补充要求：{extra_instruction}"
    user_content = (
        f"判断题陈述：{question.get('question', '')}\n\n"
        f"证据片段：\n{format_evidence_block(evidence)}\n\n"
        f"{instruction}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
