"""Tests for aitk.routing — Ollama vs Claude break-even decision."""
import pytest

from aitk.routing import (
    BREAK_EVEN_TOKENS,
    cost_phase3,
    cost_raw_claude,
    decide_route,
    estimate_output_tokens,
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


def test_cost_phase3_charges_input_at_3_and_output_at_15_per_million():
    cost = cost_phase3(review_input=1_000_000, review_output=1_000_000)
    assert cost == pytest.approx(3.00 + 15.00)


def test_cost_raw_claude_charges_spec_as_input_and_code_as_output():
    cost = cost_raw_claude(spec_input=1_000_000, code_output=1_000_000)
    assert cost == pytest.approx(3.00 + 15.00)


def test_cost_raw_claude_is_cheaper_than_phase3_below_break_even():
    # Small file: raw Claude generation should win (per the derivation in routing.py's docstring)
    spec_input, code_output = 500, 600          # ~50-line file
    review_input, review_output = 1_500 + code_output, 800

    assert cost_raw_claude(spec_input, code_output) < cost_phase3(review_input, review_output)


def test_phase3_is_cheaper_than_raw_claude_above_break_even():
    # Large file: Ollama + Claude review should win
    spec_input, code_output = 500, 3_000         # ~250-line file
    review_input, review_output = 1_500 + code_output, 800

    assert cost_phase3(review_input, review_output) < cost_raw_claude(spec_input, code_output)
