"""Central configuration — models, pricing, and local-model availability.

Every model, pricing, and hardware assumption lives here so a model swap,
price change, or hardware upgrade is a one-file edit.
"""
import os

# --- Claude models ---
GENERATION_MODEL = "claude-sonnet-5-5"   # code generation and spec drafting
TEST_MODEL = "claude-sonnet-5-5"         # spec-derived test writing (separate call, never sees the code)
REVIEW_MODEL = "claude-haiku-5-5"        # code review (cheap, structured checklist work)

# Reasoning effort per role. Sonnet 5.5 thinks adaptively by default; "medium" bounds that
# spend. These are starting points, NOT measured optima — tune them against the benchmarks.
GENERATION_EFFORT = "medium"
TEST_EFFORT = "medium"
# Review is a structured-JSON checklist, so thinking is switched off for it (Haiku 5.5 allows
# this at default effort). Set to None to let the model think.
REVIEW_THINKING = {"type": "disabled"}

# Hard output cap for a single generation call. Adaptive thinking tokens count toward this
# cap, so it is larger than the ~680 lines (at ~12 tokens/line) the code alone would need.
MAX_GENERATION_TOKENS = 16000

# Generate→check→review attempts per run (first try + retries). Override per run with
# `--max-attempts` or the AITK_MAX_ATTEMPTS environment variable.
DEFAULT_MAX_ATTEMPTS = 2

# USD per token, keyed by model ID. Legacy IDs stay so old log entries can be re-priced.
# Haiku 5.5 is priced for prompts up to 100K tokens (more beyond) — aitk prompts are far smaller.
CLAUDE_RATES = {
    "claude-sonnet-5-5": {"input": 2.00 / 1_000_000, "output": 10.00 / 1_000_000},
    "claude-haiku-5-5":  {"input": 0.10 / 1_000_000, "output": 0.50 / 1_000_000},
    "claude-sonnet-4-6": {"input": 3.00 / 1_000_000, "output": 15.00 / 1_000_000},
    "claude-haiku-4-5":  {"input": 1.00 / 1_000_000, "output": 5.00 / 1_000_000},
}

# Prompt-cache pricing as multiples of the base input rate (5-minute cache).
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


def claude_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Estimated USD cost of one Claude call at the given model's rates.

    `input_tokens` is the *uncached* input count (as the API reports it); cache reads and
    writes are separate counts billed at their own multiples of the input rate.
    """
    rates = CLAUDE_RATES[model]
    return (
        input_tokens * rates["input"]
        + output_tokens * rates["output"]
        + cache_read_tokens * rates["input"] * CACHE_READ_MULTIPLIER
        + cache_write_tokens * rates["input"] * CACHE_WRITE_MULTIPLIER
    )


def resolve_max_attempts(requested: int | None = None) -> int:
    """Attempts per run: explicit argument, else AITK_MAX_ATTEMPTS, else the default (min 1)."""
    if requested is None:
        env = os.environ.get("AITK_MAX_ATTEMPTS", "").strip()
        requested = int(env) if env.isdigit() else DEFAULT_MAX_ATTEMPTS
    return max(1, requested)


# --- Ollama (local generation) ---
# Disabled by default: current hardware can't run local models. Set
# AITK_OLLAMA_ENABLED=1 after a hardware upgrade to re-enable local routing;
# `--route ollama` still works explicitly regardless of this flag.
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5-coder:14b"


def ollama_enabled() -> bool:
    """Whether local Ollama generation is available on this machine."""
    return os.environ.get("AITK_OLLAMA_ENABLED", "").lower() in ("1", "true", "yes")
