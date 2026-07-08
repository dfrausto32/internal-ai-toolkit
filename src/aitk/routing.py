"""Route generation between local Ollama and Claude.

Routing rules:
  - An explicit --route ollama/claude always wins.
  - --route auto resolves to "claude" unless local models are enabled
    (AITK_OLLAMA_ENABLED=1 — see aitk.config). With local models enabled,
    auto falls back to the Phase 3 size heuristic below.

Break-even analysis (from Phase 3 benchmarks, 2026-06-05, Sonnet reviewer at $3/$15):
  Phase 3 cost = (review_overhead_in + code_tokens) * $3/1M + review_out * $15/1M
  Raw Claude   = spec_in * $3/1M + code_tokens * $15/1M

  Solving for break-even output token count:
    code_tokens * $12 = review_overhead_in * $3 + review_out * $15
    code_tokens >= (900*3 + 800*15) / 12 = 1225 tokens (~100 lines)

  Below 1225 tokens: raw Claude is cheaper.
  Above 1225 tokens: Ollama + Claude review is cheaper (code read as $3 input vs $15 output).

  Note: this derivation predates the Haiku reviewer and the review step on the
  claude route. With free local generation and both routes reviewed, Ollama is
  strictly cheaper whenever it's available — the threshold is kept as a *quality*
  heuristic (small specs go to Claude, where quality-per-dollar is cheap; large
  specs go to free local generation).
"""

from aitk.config import ollama_enabled

BREAK_EVEN_TOKENS = 1_225  # ~100 lines of Python

_TOKENS_PER_LINE = 12               # empirical average for Python


def estimate_output_tokens(spec_text: str, estimated_lines: int | None = None) -> int:
    """Estimate generated code size in tokens."""
    if estimated_lines is not None:
        return estimated_lines * _TOKENS_PER_LINE
    # Fallback heuristic: spec word count correlates loosely with output size
    return len(spec_text.split()) * 2


def decide_route(spec_text: str, estimated_lines: int | None = None) -> str:
    """Return 'ollama' or 'claude' based on expected output size (assumes Ollama is available)."""
    tokens = estimate_output_tokens(spec_text, estimated_lines)
    return "ollama" if tokens >= BREAK_EVEN_TOKENS else "claude"


def resolve_route(route: str, spec_text: str, estimated_lines: int | None = None) -> str:
    """Resolve a requested route ('auto'/'ollama'/'claude') to a concrete one.

    'auto' resolves to 'claude' when local models are unavailable, so the
    pipeline never depends on an Ollama server that isn't there.
    """
    if route != "auto":
        return route
    if not ollama_enabled():
        return "claude"
    return decide_route(spec_text, estimated_lines)
