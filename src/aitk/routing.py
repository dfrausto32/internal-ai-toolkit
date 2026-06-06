"""Route generation between Ollama and raw Claude based on expected output size.

Break-even analysis (from Phase 3 benchmarks, 2026-06-05):
  Phase 3 cost = (review_overhead_in + code_tokens) * $3/1M + review_out * $15/1M
  Raw Claude   = spec_in * $3/1M + code_tokens * $15/1M

  Solving for break-even output token count:
    code_tokens * $12 = review_overhead_in * $3 + review_out * $15
    code_tokens >= (900*3 + 800*15) / 12 = 1225 tokens (~100 lines)

  Below 1225 tokens: raw Claude is cheaper.
  Above 1225 tokens: Ollama + Claude review is cheaper (code read as $3 input vs $15 output).
"""

BREAK_EVEN_TOKENS = 1_225  # ~100 lines of Python

_INPUT_RATE  = 3.00  / 1_000_000   # Sonnet 4.6 per input token
_OUTPUT_RATE = 15.00 / 1_000_000   # Sonnet 4.6 per output token
_TOKENS_PER_LINE = 12               # empirical average for Python


def estimate_output_tokens(spec_text: str, estimated_lines: int | None = None) -> int:
    """Estimate generated code size in tokens."""
    if estimated_lines is not None:
        return estimated_lines * _TOKENS_PER_LINE
    # Fallback heuristic: spec word count correlates loosely with output size
    return len(spec_text.split()) * 2


def decide_route(spec_text: str, estimated_lines: int | None = None) -> str:
    """Return 'ollama' or 'claude' based on expected output size."""
    tokens = estimate_output_tokens(spec_text, estimated_lines)
    return "ollama" if tokens >= BREAK_EVEN_TOKENS else "claude"


def cost_phase3(review_input: int, review_output: int) -> float:
    """Estimated USD cost for one Phase 3 Claude review call."""
    return review_input * _INPUT_RATE + review_output * _OUTPUT_RATE


def cost_raw_claude(spec_input: int, code_output: int) -> float:
    """Estimated USD cost for one raw Claude generation call."""
    return spec_input * _INPUT_RATE + code_output * _OUTPUT_RATE
