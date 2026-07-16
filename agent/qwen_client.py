"""Qwen Chat Completions 客户端（OpenAI-compatible HTTP，标准库实现）。

环境变量：
    DASHSCOPE_API_KEY   优先
    QWEN_API_KEY        fallback
    QWEN_MODEL          默认 qwen-plus
    QWEN_BASE_URL       默认 https://dashscope.aliyuncs.com/compatible-mode/v1

安全约定：API key 只存在内存，不打印、不写文件、不出现在异常信息中。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from agent.trace_gate import AgentTraceRecorder, now_iso, sha256_json

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"


class MissingApiKeyError(Exception):
    """未配置 API key。"""


class QwenApiError(Exception):
    """Qwen API 调用失败（不包含 API key 信息）。"""


def resolve_api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY")
    if not key:
        raise MissingApiKeyError(
            "未配置 Qwen API key。请设置环境变量 DASHSCOPE_API_KEY（或 QWEN_API_KEY）。"
        )
    return key


class QwenClient:
    """封装 Qwen chat completions。用法：

        client = QwenClient()
        result = client.chat([{"role": "user", "content": "..."}])
        result["content"], result["total_tokens"]
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 90.0,
        max_retries: int = 2,
        trace_recorder: AgentTraceRecorder | None = None,
    ):
        self._api_key = api_key or resolve_api_key()
        self.model = model or os.environ.get("QWEN_MODEL", DEFAULT_MODEL)
        self.base_url = (base_url or os.environ.get("QWEN_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.trace_recorder = trace_recorder

    def __repr__(self) -> str:  # 不暴露 API key
        return f"QwenClient(model={self.model!r}, base_url={self.base_url!r})"

    # ------------------------------------------------------------ HTTP

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """发送请求，返回解析后的 JSON。可在测试中被替换（monkeypatch）。"""
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def parse_response(data: dict[str, Any], model: str) -> dict[str, Any]:
        """解析 OpenAI-compatible 响应为统一结构。"""
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise QwenApiError(f"响应结构异常，缺少 choices/message/content: {exc!r}") from exc
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens))
        return {
            "content": content,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "model": data.get("model", model),
            "raw": data,
        }

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        trace_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """调用 chat completions，带重试。失败抛 QwenApiError（不含 key）。"""
        if not isinstance(self.trace_recorder, AgentTraceRecorder):
            raise QwenApiError(
                "Agent Trace Gate: QwenClient.chat requires an AgentTraceRecorder; "
                "use agent.run_submission or agent.run_gold_oracle"
            )
        if self.trace_recorder is not None:
            self.trace_recorder.assert_guard_active()
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            **kwargs,
        }
        recorder = self.trace_recorder
        call_id = recorder.new_call_id() if recorder is not None else ""
        local_request_id = f"request-{call_id.removeprefix('call-')}" if call_id else ""
        call_started_at = now_iso()
        attempts: list[dict[str, Any]] = []
        raw_response: dict[str, Any] | None = None
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            attempt_started_at = now_iso()
            try:
                data = self._post(payload)
                raw_response = data
                parsed = self.parse_response(data, self.model)
                attempts.append(
                    {
                        "attempt": attempt + 1,
                        "started_at": attempt_started_at,
                        "finished_at": now_iso(),
                        "status": "success",
                        "error": None,
                        "retry_delay_seconds": 0,
                    }
                )
                if recorder is not None:
                    context = dict(trace_context or {})
                    evidence = context.pop("evidence", [])
                    response_message = {}
                    choices = data.get("choices")
                    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                        candidate = choices[0].get("message")
                        if isinstance(candidate, dict):
                            response_message = candidate
                    tool_calls = response_message.get("tool_calls") or []
                    if not isinstance(tool_calls, list):
                        tool_calls = []
                    recorder.record_call(
                        {
                            "call_id": call_id,
                            "local_request_id": local_request_id,
                            "provider_request_id": str(
                                data.get("id") or data.get("request_id") or ""
                            ),
                            "started_at": call_started_at,
                            "finished_at": now_iso(),
                            "status": "success",
                            "context": context,
                            "messages": messages,
                            "messages_sha256": sha256_json(messages),
                            "model_evidence": evidence,
                            "model_evidence_sha256": sha256_json(evidence),
                            "request_payload": payload,
                            "request_payload_sha256": sha256_json(payload),
                            "raw_response": data,
                            "raw_response_sha256": sha256_json(data),
                            "response_content": parsed["content"],
                            "response_model": parsed["model"],
                            "finish_reason": (
                                choices[0].get("finish_reason", "")
                                if isinstance(choices, list)
                                and choices
                                and isinstance(choices[0], dict)
                                else ""
                            ),
                            "tool_calls": tool_calls,
                            "usage": {
                                "prompt_tokens": parsed["prompt_tokens"],
                                "completion_tokens": parsed["completion_tokens"],
                                "total_tokens": parsed["total_tokens"],
                            },
                            "attempts": attempts,
                            "retry_count": max(0, len(attempts) - 1),
                            "error": None,
                        }
                    )
                parsed.update(
                    {
                        "trace_call_id": call_id or None,
                        "trace_run_id": recorder.run_id if recorder is not None else None,
                        "local_request_id": local_request_id or None,
                        "provider_request_id": str(
                            data.get("id") or data.get("request_id") or ""
                        )
                        or None,
                        "retry_count": max(0, len(attempts) - 1),
                    }
                )
                return parsed
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    pass
                last_error = QwenApiError(f"HTTP {exc.code}: {body}")
                retryable = exc.code in (429, 500, 502, 503, 504)
                attempts.append(
                    {
                        "attempt": attempt + 1,
                        "started_at": attempt_started_at,
                        "finished_at": now_iso(),
                        "status": "error",
                        "error": str(last_error),
                        "retry_delay_seconds": (
                            2.0 * (attempt + 1)
                            if retryable and attempt < self.max_retries
                            else 0
                        ),
                    }
                )
                if exc.code not in (429, 500, 502, 503, 504):
                    break  # 4xx（非限流）不重试
            except urllib.error.URLError as exc:
                last_error = QwenApiError(f"网络错误: {exc.reason}")
                attempts.append(
                    {
                        "attempt": attempt + 1,
                        "started_at": attempt_started_at,
                        "finished_at": now_iso(),
                        "status": "error",
                        "error": str(last_error),
                        "retry_delay_seconds": (
                            2.0 * (attempt + 1) if attempt < self.max_retries else 0
                        ),
                    }
                )
            except QwenApiError as exc:
                last_error = exc
                attempts.append(
                    {
                        "attempt": attempt + 1,
                        "started_at": attempt_started_at,
                        "finished_at": now_iso(),
                        "status": "error",
                        "error": str(last_error),
                        "retry_delay_seconds": 0,
                    }
                )
                break
            if attempt < self.max_retries:
                time.sleep(2.0 * (attempt + 1))
        if recorder is not None:
            context = dict(trace_context or {})
            evidence = context.pop("evidence", [])
            recorder.record_call(
                {
                    "call_id": call_id,
                    "local_request_id": local_request_id,
                    "provider_request_id": "",
                    "started_at": call_started_at,
                    "finished_at": now_iso(),
                    "status": "error",
                    "context": context,
                    "messages": messages,
                    "messages_sha256": sha256_json(messages),
                    "model_evidence": evidence,
                    "model_evidence_sha256": sha256_json(evidence),
                    "request_payload": payload,
                    "request_payload_sha256": sha256_json(payload),
                    "raw_response": raw_response,
                    "raw_response_sha256": (
                        sha256_json(raw_response) if raw_response is not None else None
                    ),
                    "response_content": None,
                    "response_model": None,
                    "finish_reason": None,
                    "tool_calls": [],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                    "attempts": attempts,
                    "retry_count": max(0, len(attempts) - 1),
                    "error": str(last_error or "unknown error"),
                }
            )
        raise last_error if last_error else QwenApiError("未知错误")
