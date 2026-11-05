"""Tests for aitk.config — current models, cache-aware pricing, attempt resolution."""
import pytest

from aitk.config import (
    CLAUDE_RATES, GENERATION_MODEL, REVIEW_MODEL, TEST_MODEL, claude_cost, resolve_max_attempts,
)


def test_configured_models_all_have_rates():
    for model in (GENERATION_MODEL, REVIEW_MODEL, TEST_MODEL):
        assert model in CLAUDE_RATES


def test_sonnet_5_5_rates():
    assert claude_cost("claude-sonnet-5-5", 1_000_000, 1_000_000) == pytest.approx(12.00)


def test_haiku_5_5_rates():
    assert claude_cost("claude-haiku-5-5", 1_000_000, 1_000_000) == pytest.approx(0.60)


def test_cache_reads_cost_a_tenth_and_writes_a_quarter_more_than_input():
    base = claude_cost("claude-sonnet-5-5", 1_000_000, 0)
    assert claude_cost("claude-sonnet-5-5", 0, 0, cache_read_tokens=1_000_000) == pytest.approx(base * 0.10)
    assert claude_cost("claude-sonnet-5-5", 0, 0, cache_write_tokens=1_000_000) == pytest.approx(base * 1.25)


def test_max_attempts_precedence(monkeypatch):
    monkeypatch.delenv("AITK_MAX_ATTEMPTS", raising=False)
    assert resolve_max_attempts() == 2
    monkeypatch.setenv("AITK_MAX_ATTEMPTS", "4")
    assert resolve_max_attempts() == 4
    assert resolve_max_attempts(3) == 3          # explicit beats env
    assert resolve_max_attempts(0) == 1          # floor of one attempt
    monkeypatch.setenv("AITK_MAX_ATTEMPTS", "junk")
    assert resolve_max_attempts() == 2
