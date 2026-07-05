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
    ):
        self._api_key = api_key or resolve_api_key()
        self.model = model or os.environ.get("QWEN_MODEL", DEFAULT_MODEL)
        self.base_url = (base_url or os.environ.get("QWEN_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

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
        **kwargs: Any,
    ) -> dict[str, Any]:
        """调用 chat completions，带重试。失败抛 QwenApiError（不含 key）。"""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            **kwargs,
        }
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                data = self._post(payload)
                return self.parse_response(data, self.model)
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    pass
                last_error = QwenApiError(f"HTTP {exc.code}: {body}")
                if exc.code not in (429, 500, 502, 503, 504):
                    break  # 4xx（非限流）不重试
            except urllib.error.URLError as exc:
                last_error = QwenApiError(f"网络错误: {exc.reason}")
            except QwenApiError as exc:
                last_error = exc
                break
            if attempt < self.max_retries:
                time.sleep(2.0 * (attempt + 1))
        raise last_error if last_error else QwenApiError("未知错误")
