"""按题型把逐选项 judgment 合成合法答案（Task 5）。

规则见比赛提交格式：
- mcq / tf：单个大写字母。
- multi：多个大写字母，去重、按字母序、无分隔符。
- 无 support 时 fallback 到排序最前合法选项，标记 low_confidence 并写 warning。
fallback 只保证格式合法，不代表高置信答案。
"""

from __future__ import annotations

import re
from typing import Any


def _valid_letters(options: dict[str, Any]) -> list[str]:
    return sorted(options.keys())


def validate_answer_format(
    answer: str, answer_format: str, options: dict[str, Any]
) -> None:
    """校验答案是否符合提交格式，不合法抛 ValueError。"""
    letters = _valid_letters(options)
    if not answer or not re.fullmatch(r"[A-Z]+", answer):
        raise ValueError(f"答案必须是非空大写字母串，不允许空格/逗号/中文: {answer!r}")
    for ch in answer:
        if ch not in letters:
            raise ValueError(f"答案包含非法选项字母 {ch!r}，合法范围 {letters}")
    if answer_format in ("mcq", "tf"):
        if len(answer) != 1:
            raise ValueError(f"{answer_format} 答案必须是单个字母: {answer!r}")
    elif answer_format == "multi":
        if len(set(answer)) != len(answer):
            raise ValueError(f"multi 答案不允许重复字母: {answer!r}")
        if list(answer) != sorted(answer):
            raise ValueError(f"multi 答案必须按字母排序: {answer!r}")
    else:
        raise ValueError(f"未知 answer_format: {answer_format!r}")


def normalize_answer(
    answer_format: str,
    option_judgments: dict[str, dict[str, Any]],
    options: dict[str, Any],
) -> dict[str, Any]:
    """合成最终答案。返回 {"answer", "warnings", "low_confidence"}。"""
    letters = _valid_letters(options)
    warnings: list[str] = []
    low_confidence = False

    supported = sorted(
        k for k, j in option_judgments.items()
        if j.get("judgment") == "support" and k in letters
    )
    errored = sorted(
        k for k, j in option_judgments.items() if j.get("judgment") == "error"
    )
    if errored:
        warnings.append(f"选项 {','.join(errored)} 判断阶段出错，按非 support 处理")
        low_confidence = True

    if answer_format == "multi":
        if supported:
            answer = "".join(supported)  # 已排序去重
        else:
            answer = letters[0]
            warnings.append("multi 无 support 选项，fallback 到排序最前合法选项")
            low_confidence = True

    elif answer_format == "mcq":
        if len(supported) == 1:
            answer = supported[0]
        elif len(supported) > 1:
            # 多个 support：取 evidence_refs 最多者；仍并列取字母序最前
            answer = min(
                supported,
                key=lambda k: (-len(option_judgments[k].get("evidence_refs") or []), k),
            )
            warnings.append(f"mcq 出现多个 support（{','.join(supported)}），按 evidence_refs 数量选 {answer}")
            low_confidence = True
        else:
            answer = letters[0]
            warnings.append("mcq 无 support 选项，fallback 到排序最前合法选项")
            low_confidence = True

    elif answer_format == "tf":
        a_sup = option_judgments.get("A", {}).get("judgment") == "support"
        b_sup = option_judgments.get("B", {}).get("judgment") == "support"
        if a_sup and not b_sup:
            answer = "A"
        elif b_sup and not a_sup:
            answer = "B"
        else:
            answer = "A"
            warnings.append("tf 无法确定（双 support 或无 support），fallback 到 A")
            low_confidence = True
    else:
        raise ValueError(f"未知 answer_format: {answer_format!r}")

    validate_answer_format(answer, answer_format, options)
    return {"answer": answer, "warnings": warnings, "low_confidence": low_confidence}
