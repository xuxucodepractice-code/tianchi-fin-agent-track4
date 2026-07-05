"""Qwen 客户端测试（Task 5）。不调用真实 API。

运行：python -m pytest tests/test_qwen_client.py -q
"""

from __future__ import annotations

import pytest

from agent.qwen_client import (
    DEFAULT_MODEL,
    MissingApiKeyError,
    QwenClient,
    resolve_api_key,
)

FAKE_KEY = "sk-test-fake-key-do-not-use"


def _clear_keys(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)


# ------------------------------------------------- 1. 缺 key 报错


def test_missing_api_key_raises_clear_error(monkeypatch):
    _clear_keys(monkeypatch)
    with pytest.raises(MissingApiKeyError) as exc_info:
        resolve_api_key()
    msg = str(exc_info.value)
    assert "DASHSCOPE_API_KEY" in msg
    with pytest.raises(MissingApiKeyError):
        QwenClient()


def test_qwen_api_key_fallback(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("QWEN_API_KEY", FAKE_KEY)
    assert resolve_api_key() == FAKE_KEY


# ------------------------------------------------- 2. key 不泄漏


def test_api_key_not_in_repr_or_error_strings(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_API_KEY", FAKE_KEY)
    client = QwenClient()
    assert FAKE_KEY not in repr(client)
    assert FAKE_KEY not in str(client.__dict__.get("model", ""))
    # 模拟网络错误路径：错误信息不应包含 key
    import urllib.error

    def _fail(payload):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(client, "_post", _fail)
    client.max_retries = 0
    with pytest.raises(Exception) as exc_info:
        client.chat([{"role": "user", "content": "hi"}])
    assert FAKE_KEY not in str(exc_info.value)


# ------------------------------------------------- 3. usage 解析


def test_parse_response_usage():
    data = {
        "choices": [{"message": {"role": "assistant", "content": "hello"}}],
        "usage": {"prompt_tokens": 321, "completion_tokens": 45, "total_tokens": 366},
        "model": "qwen-plus",
    }
    result = QwenClient.parse_response(data, DEFAULT_MODEL)
    assert result["content"] == "hello"
    assert result["prompt_tokens"] == 321
    assert result["completion_tokens"] == 45
    assert result["total_tokens"] == 366


def test_parse_response_missing_usage_defaults_zero():
    data = {"choices": [{"message": {"content": "x"}}]}
    result = QwenClient.parse_response(data, DEFAULT_MODEL)
    assert result["prompt_tokens"] == 0
    assert result["total_tokens"] == 0


def test_chat_end_to_end_with_fake_post(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", FAKE_KEY)
    client = QwenClient()

    def _fake_post(payload):
        assert payload["model"] == client.model
        assert payload["temperature"] == 0.0
        return {
            "choices": [{"message": {"content": '{"judgment": "support"}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    monkeypatch.setattr(client, "_post", _fake_post)
    result = client.chat([{"role": "user", "content": "test"}])
    assert result["total_tokens"] == 15
    assert "support" in result["content"]
