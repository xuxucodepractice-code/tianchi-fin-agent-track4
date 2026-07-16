"""基于检索证据的 Qwen 推理（Task 5 / M1）。

Multi：逐选项判断后由 normalize_answer 合成。
TF：题干级直接判断。
MCQ（v2s2 / M1）：保留四次逐选项判断作诊断，再以第五次统一比较直接选答案。

模式：
    MODE_QWEN     = "qwen"          正式推理，必须真实调用 Qwen API
    MODE_DRY_RUN  = "dry_run_mock"  接口联调用，不调用 API，不是正式答案
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent.normalize_answer import (
    normalize_answer,
    normalize_mcq_global_choice,
    normalize_tf_verdict,
)
from agent.paths import REASONING_SAMPLES_ROOT, VERSIONED_REASONING_SAMPLES_DIR
from agent.prompts import (
    build_mcq_global_comparison_messages,
    build_option_judgment_messages,
    build_tf_judgment_messages,
)
from agent.qwen_client import QwenClient

MODE_QWEN = "qwen"
MODE_DRY_RUN = "dry_run_mock"
PIPELINE_VERSION = "v2s2"

REASONING_SAMPLES_DIR = VERSIONED_REASONING_SAMPLES_DIR / PIPELINE_VERSION
REASONING_ARCHIVE_DIR = REASONING_SAMPLES_ROOT / "archive_v0"  # 历史只读兼容

VALID_JUDGMENTS = {"support", "refute", "insufficient"}
VALID_TF_VERDICTS = {"true", "false", "uncertain"}
MCQ_GLOBAL_METHOD = "agent.normalize_answer.normalize_mcq_global_choice"


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
    reported_option = obj.get("option")
    if reported_option != option_key:
        return (
            {
                "judgment": "error",
                "rationale": str(obj.get("rationale", ""))[:100],
                "evidence_refs": [],
            },
            f"option 字段不匹配: expected {option_key!r}, got {reported_option!r}",
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


def _strict_json_object(content: str) -> dict[str, Any]:
    """解析严格 JSON 对象：拒绝包裹文字、重复 key 与 NaN/Infinity。"""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError(f"duplicate JSON key: {key}")
            obj[key] = value
        return obj

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-standard JSON constant: {value}")

    parsed = json.loads(
        content.strip(),
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_constant,
    )
    if not isinstance(parsed, dict):
        raise ValueError("top-level JSON must be an object")
    return parsed


def parse_mcq_global_comparison_response(
    content: str,
    option_keys: list[str],
) -> tuple[dict[str, Any], str | None]:
    """严格解析 M1 统一比较输出；任何 schema 偏差均返回 error。"""
    empty = {
        "answer": "",
        "eliminated": {},
        "calculations": [],
        "confidence": "",
        "rationale": "",
    }
    expected_options = sorted(map(str, option_keys))
    if expected_options != ["A", "B", "C", "D"]:
        return empty, f"M1 只接受 A/B/C/D 四选项，实际为 {expected_options}"
    try:
        obj = _strict_json_object(content)
        expected_fields = {
            "answer",
            "eliminated",
            "calculations",
            "confidence",
            "rationale",
        }
        if set(obj) != expected_fields:
            raise ValueError(
                f"fields must be exactly {sorted(expected_fields)}, got {sorted(obj)}"
            )
        answer = obj["answer"]
        if not isinstance(answer, str) or answer not in expected_options:
            raise ValueError(f"answer must be exactly one of {expected_options}")
        eliminated = obj["eliminated"]
        expected_eliminated = set(expected_options) - {answer}
        if not isinstance(eliminated, dict) or set(eliminated) != expected_eliminated:
            raise ValueError(
                "eliminated must contain exactly the three non-answer options"
            )
        normalized_eliminated: dict[str, str] = {}
        for key in sorted(eliminated):
            reason = eliminated[key]
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"eliminated[{key}] must be a non-empty string")
            normalized_eliminated[key] = reason.strip()[:300]
        calculations = obj["calculations"]
        if not isinstance(calculations, list) or not all(
            isinstance(item, str) and item.strip() for item in calculations
        ):
            raise ValueError("calculations must be a list of non-empty strings")
        confidence = obj["confidence"]
        if confidence not in {"high", "low"}:
            raise ValueError("confidence must be high or low")
        rationale = obj["rationale"]
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("rationale must be a non-empty string")
        return (
            {
                "answer": answer,
                "eliminated": normalized_eliminated,
                "calculations": [item.strip()[:300] for item in calculations],
                "confidence": confidence,
                "rationale": rationale.strip()[:500],
            },
            None,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return empty, f"MCQ 统一比较输出非法: {exc}"


def _rationale_consistent_with_tf_verdict(verdict: str, rationale: str) -> bool:
    """拦截 v0 审计里出现过的「理由说真、标签打假」这类自相矛盾。"""
    rationale = rationale.strip()
    positive = ("支持", "为真", "正确", "成立", "符合")
    negative = ("不支持", "不正确", "为假", "错误", "否定", "矛盾", "不成立")
    has_positive = any(word in rationale for word in positive)
    has_negative = any(word in rationale for word in negative)
    if verdict == "true" and has_negative:
        return False
    if verdict == "false" and has_positive and not has_negative:
        return False
    return True


def _parse_tf_judgment(content: str) -> tuple[dict[str, Any], str | None]:
    obj = extract_json_from_text(content)
    if obj is None:
        return (
            {"verdict": "error", "fact_checks": [], "rationale": ""},
            f"模型输出不是合法 JSON: {content[:200]!r}",
        )
    verdict = str(obj.get("verdict", "")).strip().lower()
    if verdict not in VALID_TF_VERDICTS:
        return (
            {
                "verdict": "error",
                "fact_checks": obj.get("fact_checks") if isinstance(obj.get("fact_checks"), list) else [],
                "rationale": str(obj.get("rationale", ""))[:200],
            },
            f"verdict 取值非法: {verdict!r}",
        )
    fact_checks = obj.get("fact_checks")
    if not isinstance(fact_checks, list):
        fact_checks = []
    normalized_checks: list[dict[str, Any]] = []
    for item in fact_checks:
        if not isinstance(item, dict):
            continue
        refs = item.get("evidence_refs") or []
        if not isinstance(refs, list):
            refs = []
        normalized_checks.append(
            {
                "claim": str(item.get("claim", ""))[:200],
                "verdict": str(item.get("verdict", "")).strip().lower(),
                "evidence_refs": [
                    int(r) for r in refs if isinstance(r, (int, float, str)) and str(r).isdigit()
                ],
            }
        )
    rationale = str(obj.get("rationale", ""))[:300]
    if not _rationale_consistent_with_tf_verdict(verdict, rationale):
        return (
            {"verdict": "error", "fact_checks": normalized_checks, "rationale": rationale},
            "tf verdict 与 rationale 不自洽",
        )
    return {"verdict": verdict, "fact_checks": normalized_checks, "rationale": rationale}, None


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
    stage_prefix = str(question.get("_trace_stage_prefix", ""))
    try:
        resp = client.chat(
            messages,
            temperature=0.0,
            trace_context={
                "qid": question.get("qid", ""),
                "answer_format": question.get("answer_format", ""),
                "stage": f"{stage_prefix}option_independent_judgment",
                "option_key": option_key,
                "option_text": option_text,
                "evidence": evidence,
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
    parsed, error = _parse_judgment(resp["content"], option_key)
    return {
        **parsed,
        "prompt_tokens": resp["prompt_tokens"],
        "completion_tokens": resp["completion_tokens"],
        "total_tokens": resp["total_tokens"],
        "trace_call_id": resp.get("trace_call_id"),
        "trace_run_id": resp.get("trace_run_id"),
        "local_request_id": resp.get("local_request_id"),
        "provider_request_id": resp.get("provider_request_id"),
        "retry_count": int(resp.get("retry_count") or 0),
        "error": error,
    }


def _flatten_mcq_model_evidence(retrieval: dict[str, Any]) -> list[dict[str, Any]]:
    """为 Trace Gate 扁平化 global 调用实际看到的四组选项证据。"""
    flattened: list[dict[str, Any]] = []
    for option_key in sorted(retrieval.get("options", {})):
        evidence = retrieval["options"][option_key].get("evidence", [])
        for index, item in enumerate(evidence, start=1):
            flattened.append(
                {
                    **item,
                    "option_key": option_key,
                    "evidence_ref": f"{option_key}-{index}",
                }
            )
    return flattened


def judge_mcq_global_comparison_with_qwen(
    client: QwenClient,
    question: dict[str, Any],
    retrieval: dict[str, Any],
) -> dict[str, Any]:
    """第五次调用：只看四个选项与原始检索证据，直接给出 MCQ 答案。"""
    option_keys = sorted(question.get("options", {}))
    messages = build_mcq_global_comparison_messages(question, retrieval)
    stage_prefix = str(question.get("_trace_stage_prefix", ""))
    try:
        resp = client.chat(
            messages,
            temperature=0.0,
            trace_context={
                "qid": question.get("qid", ""),
                "answer_format": question.get("answer_format", ""),
                "stage": f"{stage_prefix}mcq_global_comparison",
                "option_keys": option_keys,
                "evidence": _flatten_mcq_model_evidence(retrieval),
            },
        )
    except Exception as exc:
        return {
            "answer": "",
            "eliminated": {},
            "calculations": [],
            "confidence": "",
            "rationale": "",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "error": f"Qwen MCQ 统一比较调用失败: {exc}",
        }
    parsed, error = parse_mcq_global_comparison_response(
        str(resp.get("content", "")), option_keys
    )
    return {
        **parsed,
        "prompt_tokens": int(resp.get("prompt_tokens") or 0),
        "completion_tokens": int(resp.get("completion_tokens") or 0),
        "total_tokens": int(resp.get("total_tokens") or 0),
        "trace_call_id": resp.get("trace_call_id"),
        "trace_run_id": resp.get("trace_run_id"),
        "local_request_id": resp.get("local_request_id"),
        "provider_request_id": resp.get("provider_request_id"),
        "retry_count": int(resp.get("retry_count") or 0),
        "error": error,
    }


def judge_tf_with_qwen(
    client: QwenClient,
    question: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    extra_instruction: str | None = None,
) -> dict[str, Any]:
    """调用 Qwen 对 tf 题干作一次 true/false/uncertain 判断。"""
    messages = build_tf_judgment_messages(
        question, evidence, extra_instruction=extra_instruction
    )
    stage_prefix = str(question.get("_trace_stage_prefix", ""))
    try:
        resp = client.chat(
            messages,
            temperature=0.0,
            trace_context={
                "qid": question.get("qid", ""),
                "answer_format": question.get("answer_format", ""),
                "stage": f"{stage_prefix}tf_direct_judgment",
                "extra_instruction": extra_instruction or "",
                "evidence": evidence,
            },
        )
    except Exception as exc:
        return {
            "verdict": "error",
            "fact_checks": [],
            "rationale": "",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "error": f"Qwen 调用失败: {exc}",
        }
    parsed, error = _parse_tf_judgment(resp["content"])
    return {
        **parsed,
        "prompt_tokens": resp["prompt_tokens"],
        "completion_tokens": resp["completion_tokens"],
        "total_tokens": resp["total_tokens"],
        "trace_call_id": resp.get("trace_call_id"),
        "trace_run_id": resp.get("trace_run_id"),
        "local_request_id": resp.get("local_request_id"),
        "provider_request_id": resp.get("provider_request_id"),
        "retry_count": int(resp.get("retry_count") or 0),
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
    trace_run_ids = sorted(
        {
            str(judgment.get("trace_run_id"))
            for judgment in option_judgments.values()
            if judgment.get("trace_run_id")
        }
    )
    answer_derivation = {
        "method": "agent.normalize_answer.normalize_answer",
        "answer_format": question.get("answer_format", ""),
        "input_judgments": {
            key: {
                "judgment": judgment.get("judgment"),
                "evidence_refs": judgment.get("evidence_refs", []),
                "error": judgment.get("error"),
            }
            for key, judgment in sorted(option_judgments.items())
        },
        "output_answer": normalized["answer"],
        "warnings": warnings,
        "low_confidence": normalized["low_confidence"],
    }
    return {
        "qid": question["qid"],
        "domain": question.get("domain", ""),
        "answer_format": question.get("answer_format", ""),
        "mode": mode,
        "model": model,
        "pipeline_version": PIPELINE_VERSION,
        "question": question.get("question", ""),
        "options": question.get("options", {}),
        "doc_ids": question.get("doc_ids", []),
        "option_judgments": option_judgments,
        "answer": normalized["answer"],
        "answer_derivation": answer_derivation,
        "trace_run_id": trace_run_ids[0] if len(trace_run_ids) == 1 else None,
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
    """Multi/历史兼容链路：逐选项调用 Qwen，再由旧规则合成答案。"""
    if client is None:
        raise RuntimeError(
            "governed Qwen inference requires an injected traced client from "
            "agent.run_submission or agent.run_gold_oracle"
        )
    option_judgments: dict[str, dict[str, Any]] = {}
    for key in sorted(question.get("options", {})):
        opt = retrieval["options"][key]
        option_judgments[key] = judge_option_with_qwen(
            client, question, key, opt["option_text"], opt["evidence"]
        )
    return _assemble_result(question, retrieval, option_judgments, MODE_QWEN, client.model)


def reason_mcq_question_with_qwen(
    question: dict[str, Any],
    retrieval: dict[str, Any],
    client: QwenClient | None = None,
    *,
    fallback_answer: str | None = None,
) -> dict[str, Any]:
    """v2s2 M1：四次独立参考判断 + 一次不受其锚定的统一比较。"""
    if client is None:
        raise RuntimeError(
            "governed Qwen inference requires an injected traced client from "
            "agent.run_submission or agent.run_gold_oracle"
        )
    if question.get("answer_format") != "mcq":
        raise ValueError("reason_mcq_question_with_qwen only accepts answer_format=mcq")
    option_keys = sorted(question.get("options", {}))
    if option_keys != ["A", "B", "C", "D"]:
        raise ValueError(f"M1 requires exactly A/B/C/D options, got {option_keys}")
    retrieval_options = retrieval.get("options")
    if not isinstance(retrieval_options, dict) or sorted(retrieval_options) != option_keys:
        raise ValueError("M1 retrieval.options must contain exactly A/B/C/D before API calls")
    for key in option_keys:
        option = retrieval_options[key]
        if not isinstance(option, dict):
            raise ValueError(f"M1 retrieval option {key} must be an object")
        if str(option.get("option_text", "")) != str(question["options"][key]):
            raise ValueError(f"M1 retrieval option_text mismatch for {key}")
        if not isinstance(option.get("evidence"), list):
            raise ValueError(f"M1 retrieval evidence for {key} must be a list")

    # 预注册要求保留原有四次判断，作为诊断信号；global prompt 不读取这些结果。
    option_judgments: dict[str, dict[str, Any]] = {}
    for key in option_keys:
        option = retrieval["options"][key]
        option_judgments[key] = judge_option_with_qwen(
            client, question, key, option["option_text"], option["evidence"]
        )
    comparison = judge_mcq_global_comparison_with_qwen(client, question, retrieval)

    fallback = fallback_answer or option_keys[0]
    normalized = normalize_mcq_global_choice(
        str(comparison.get("answer", "")),
        question.get("options", {}),
        fallback_answer=fallback,
    )
    warnings = list(normalized["warnings"])
    for key, judgment in sorted(option_judgments.items()):
        if judgment.get("error"):
            warnings.append(f"参考判断 {key}: {judgment['error']}")
    if comparison.get("error"):
        warnings.append(str(comparison["error"]))
    if comparison.get("confidence") == "low":
        warnings.append("MCQ 统一比较 confidence=low")

    independent_prompt_tokens = sum(
        int(item.get("prompt_tokens") or 0) for item in option_judgments.values()
    )
    independent_completion_tokens = sum(
        int(item.get("completion_tokens") or 0) for item in option_judgments.values()
    )
    independent_total_tokens = sum(
        int(item.get("total_tokens") or 0) for item in option_judgments.values()
    )
    prompt_tokens = independent_prompt_tokens + int(
        comparison.get("prompt_tokens") or 0
    )
    completion_tokens = independent_completion_tokens + int(
        comparison.get("completion_tokens") or 0
    )
    total_tokens = independent_total_tokens + int(comparison.get("total_tokens") or 0)
    trace_run_ids = sorted(
        {
            str(value)
            for value in [
                *(item.get("trace_run_id") for item in option_judgments.values()),
                comparison.get("trace_run_id"),
            ]
            if value
        }
    )
    reference_judgments = {
        key: {
            "judgment": item.get("judgment"),
            "evidence_refs": item.get("evidence_refs", []),
            "error": item.get("error"),
        }
        for key, item in sorted(option_judgments.items())
    }
    answer_derivation = {
        "method": MCQ_GLOBAL_METHOD,
        "answer_format": "mcq",
        "input_choice": str(comparison.get("answer", "")),
        "input_comparison": {
            key: comparison.get(key)
            for key in (
                "answer",
                "eliminated",
                "calculations",
                "confidence",
                "rationale",
            )
        },
        "reference_judgments": reference_judgments,
        "valid_options": option_keys,
        "fallback_answer": fallback,
        "fallback_used": normalized["fallback_used"],
        "parse_error": comparison.get("error"),
        "output_answer": normalized["answer"],
        "warnings": warnings,
        "low_confidence": (
            normalized["low_confidence"]
            or comparison.get("confidence") == "low"
            or bool(comparison.get("error"))
            or any(bool(item.get("error")) for item in option_judgments.values())
        ),
    }
    return {
        "qid": question["qid"],
        "domain": question.get("domain", ""),
        "answer_format": "mcq",
        "mode": MODE_QWEN,
        "model": client.model,
        "pipeline_version": PIPELINE_VERSION,
        "question": question.get("question", ""),
        "options": question.get("options", {}),
        "doc_ids": question.get("doc_ids", []),
        "option_judgments": option_judgments,
        "mcq_comparison": comparison,
        "answer": normalized["answer"],
        "answer_derivation": answer_derivation,
        "trace_run_id": trace_run_ids[0] if len(trace_run_ids) == 1 else None,
        "warnings": warnings,
        "low_confidence": answer_derivation["low_confidence"],
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _tf_option_judgments(tf_judgment: dict[str, Any]) -> dict[str, dict[str, Any]]:
    verdict = str(tf_judgment.get("verdict", "error"))
    if verdict == "true":
        a_judgment, b_judgment = "support", "refute"
    elif verdict == "false":
        a_judgment, b_judgment = "refute", "support"
    else:
        a_judgment = b_judgment = "insufficient"
    base = {
        "rationale": str(tf_judgment.get("rationale", ""))[:200],
        "evidence_refs": sorted(
            {
                ref
                for item in tf_judgment.get("fact_checks", [])
                if isinstance(item, dict)
                for ref in item.get("evidence_refs", [])
                if isinstance(ref, int)
            }
        ),
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "error": tf_judgment.get("error"),
    }
    return {
        "A": {**base, "judgment": a_judgment},
        "B": {**base, "judgment": b_judgment},
    }


def reason_tf_question_with_qwen(
    question: dict[str, Any],
    retrieval: dict[str, Any],
    client: QwenClient | None = None,
    *,
    fallback_answer: str = "A",
) -> dict[str, Any]:
    """v2s2 继承的 TF 链路：题干级单次判断，uncertain 最多重问一次。"""
    if client is None:
        raise RuntimeError(
            "governed Qwen inference requires an injected traced client from "
            "agent.run_submission or agent.run_gold_oracle"
        )
    evidence = retrieval.get("tf", {}).get("evidence", [])
    first = judge_tf_with_qwen(client, question, evidence)
    attempts = [first]
    if first.get("verdict") == "uncertain":
        second = judge_tf_with_qwen(
            client,
            question,
            evidence,
            extra_instruction="上一次判断为 uncertain。请重新拆分事实点，只在证据完整覆盖全部事实点时输出 true 或 false；仍缺证据才输出 uncertain。",
        )
        attempts.append(second)
    final = attempts[-1]
    normalized = normalize_tf_verdict(
        str(final.get("verdict", "error")),
        question.get("options", {}),
        fallback_answer=fallback_answer,
    )
    warnings = list(normalized["warnings"])
    for attempt in attempts:
        if attempt.get("error"):
            warnings.append(str(attempt["error"]))
    prompt_tokens = sum(int(a.get("prompt_tokens") or 0) for a in attempts)
    completion_tokens = sum(int(a.get("completion_tokens") or 0) for a in attempts)
    total_tokens = sum(int(a.get("total_tokens") or 0) for a in attempts)
    tf_judgment = {
        **final,
        "attempt_count": len(attempts),
        "trace_call_ids": [
            str(attempt.get("trace_call_id"))
            for attempt in attempts
            if attempt.get("trace_call_id")
        ],
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
    trace_run_ids = sorted(
        {
            str(attempt.get("trace_run_id"))
            for attempt in attempts
            if attempt.get("trace_run_id")
        }
    )
    answer_derivation = {
        "method": "agent.normalize_answer.normalize_tf_verdict",
        "answer_format": "tf",
        "input_verdict": str(final.get("verdict", "error")),
        "fallback_answer": fallback_answer,
        "attempt_count": len(attempts),
        "output_answer": normalized["answer"],
        "warnings": warnings,
        "low_confidence": normalized["low_confidence"] or bool(final.get("error")),
    }
    return {
        "qid": question["qid"],
        "domain": question.get("domain", ""),
        "answer_format": question.get("answer_format", ""),
        "mode": MODE_QWEN,
        "model": client.model,
        "pipeline_version": PIPELINE_VERSION,
        "question": question.get("question", ""),
        "options": question.get("options", {}),
        "doc_ids": question.get("doc_ids", []),
        "tf_judgment": tf_judgment,
        "option_judgments": _tf_option_judgments(tf_judgment),
        "answer": normalized["answer"],
        "answer_derivation": answer_derivation,
        "trace_run_id": trace_run_ids[0] if len(trace_run_ids) == 1 else None,
        "warnings": warnings,
        "low_confidence": normalized["low_confidence"] or bool(final.get("error")),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


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
        version = str(result.get("pipeline_version") or PIPELINE_VERSION)
        mode = str(result.get("mode") or "unknown")
        if mode == MODE_QWEN:
            path = VERSIONED_REASONING_SAMPLES_DIR / version / f"{result['qid']}.json"
        else:
            # dry-run 的调用方应显式传 outputs/dry_runs 下的路径；此处仅作安全兜底。
            path = REASONING_SAMPLES_ROOT / "dry_run_quarantine" / version / f"{result['qid']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return path
