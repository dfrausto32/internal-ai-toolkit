"""Tests for aitk.llm — request shape (thinking, effort, cache placement) and usage extraction."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from aitk import llm


def fake_message(text="hi", stop="end_turn", cache_read=3, cache_write=4):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop,
        usage=SimpleNamespace(
            input_tokens=10, output_tokens=20,
            cache_read_input_tokens=cache_read, cache_creation_input_tokens=cache_write,
        ),
    )


def run(monkeypatch, **kwargs):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    client = MagicMock()
    client.messages.create.return_value = kwargs.pop("message", fake_message())
    with patch.object(llm.anthropic, "Anthropic", return_value=client):
        out = llm.call_claude("claude-sonnet-5-5", "prompt", max_tokens=100, **kwargs)
    return out, client.messages.create.call_args.kwargs


def test_system_prompt_gets_the_cache_breakpoint(monkeypatch):
    _, sent = run(monkeypatch, system="SYS")
    assert sent["system"] == [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]
    assert "cache_control" not in sent


def test_without_system_uses_top_level_cache_control(monkeypatch):
    _, sent = run(monkeypatch)
    assert sent["cache_control"] == {"type": "ephemeral"} and "system" not in sent


def test_cache_off_sends_plain_system_and_no_breakpoint(monkeypatch):
    _, sent = run(monkeypatch, system="SYS", cache=False)
    assert sent["system"] == "SYS" and "cache_control" not in sent


def test_effort_and_thinking_are_forwarded_and_no_sampling_params(monkeypatch):
    _, sent = run(monkeypatch, effort="medium", thinking={"type": "disabled"})
    assert sent["output_config"] == {"effort": "medium"}
    assert sent["thinking"] == {"type": "disabled"}
    assert not {"temperature", "top_p", "top_k"} & sent.keys()


def test_usage_includes_cache_counts_and_stop_reason(monkeypatch):
    (text, usage), _ = run(monkeypatch)
    assert text == "hi"
    assert usage == {"input_tokens": 10, "output_tokens": 20, "cache_read_tokens": 3,
                     "cache_write_tokens": 4, "stop_reason": "end_turn"}


def test_refusal_raises(monkeypatch):
    with pytest.raises(RuntimeError, match="refusal"):
        run(monkeypatch, message=fake_message(stop="refusal"))


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(EnvironmentError):
        llm.call_claude("claude-sonnet-5-5", "p", max_tokens=10)
