"""Tests for aitk.routing — route resolution and the local break-even heuristic."""
import pytest

from aitk.config import claude_cost
from aitk.routing import (
    BREAK_EVEN_TOKENS,
    decide_route,
    estimate_output_tokens,
    resolve_route,
)


def test_break_even_constant_matches_its_own_derivation():
    # Pins BREAK_EVEN_TOKENS to the formula documented in routing.py's module
    # docstring: code_tokens * $12 == review_overhead_in * $3 + review_out * $15.
    # Caught a real drift once (the docstring's worked example evaluated to
    # 1375, not the 1225 it claimed and the constant actually uses) — this
    # keeps the derivation and the constant from silently diverging again.
    review_overhead_in, review_out = 900, 800
    assert (review_overhead_in * 3 + review_out * 15) / 12 == BREAK_EVEN_TOKENS


def test_estimate_output_tokens_uses_estimated_lines_when_given():
    assert estimate_output_tokens("irrelevant spec text", estimated_lines=100) == 1_200


def test_estimate_output_tokens_falls_back_to_word_count_heuristic():
    spec_text = "one two three four five"  # 5 words
    assert estimate_output_tokens(spec_text, estimated_lines=None) == 10


@pytest.mark.parametrize(
    "estimated_lines, expected_route",
    [
        (50, "claude"),     # 600 tokens  — well under break-even
        (100, "claude"),    # 1200 tokens — just under break-even
        (103, "ollama"),    # 1236 tokens — just over break-even
        (200, "ollama"),    # 2400 tokens — well over break-even
    ],
)
def test_decide_route_respects_break_even_threshold(estimated_lines, expected_route):
    assert decide_route("spec text", estimated_lines=estimated_lines) == expected_route


def test_decide_route_boundary_is_inclusive_of_ollama():
    lines = BREAK_EVEN_TOKENS // 12 + 1  # smallest estimated_lines that crosses the threshold
    tokens = estimate_output_tokens("spec", estimated_lines=lines)
    assert tokens >= BREAK_EVEN_TOKENS
    assert decide_route("spec", estimated_lines=lines) == "ollama"


def test_resolve_route_auto_is_claude_when_local_models_disabled(monkeypatch):
    monkeypatch.delenv("AITK_OLLAMA_ENABLED", raising=False)
    # Even a spec far above the break-even must not route to an Ollama server
    # that isn't there.
    assert resolve_route("auto", "spec", estimated_lines=500) == "claude"


def test_resolve_route_auto_uses_break_even_when_local_models_enabled(monkeypatch):
    monkeypatch.setenv("AITK_OLLAMA_ENABLED", "1")
    assert resolve_route("auto", "spec", estimated_lines=500) == "ollama"
    assert resolve_route("auto", "spec", estimated_lines=50) == "claude"


@pytest.mark.parametrize("explicit", ["ollama", "claude"])
def test_resolve_route_passes_explicit_routes_through(monkeypatch, explicit):
    monkeypatch.delenv("AITK_OLLAMA_ENABLED", raising=False)
    assert resolve_route(explicit, "spec", estimated_lines=500) == explicit


def test_claude_cost_sonnet_charges_3_in_and_15_out_per_million():
    cost = claude_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert cost == pytest.approx(3.00 + 15.00)


def test_claude_cost_haiku_charges_1_in_and_5_out_per_million():
    cost = claude_cost("claude-haiku-4-5", 1_000_000, 1_000_000)
    assert cost == pytest.approx(1.00 + 5.00)
