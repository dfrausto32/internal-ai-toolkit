"""Central configuration — models, pricing, and local-model availability.

Every model, pricing, and hardware assumption lives here so a model swap,
price change, or hardware upgrade is a one-file edit.
"""
import os

# --- Claude models ---
GENERATION_MODEL = "claude-sonnet-4-6"   # code generation and spec drafting
REVIEW_MODEL = "claude-haiku-4-5"        # code review (cheap, structured checklist work)

# Hard output cap for a single generation call. Non-streaming stays reliable
# up to ~16K; 8192 covers ~680 lines at 12 tokens/line with headroom.
MAX_GENERATION_TOKENS = 8192

# USD per token, keyed by model ID.
CLAUDE_RATES = {
    "claude-sonnet-4-6": {"input": 3.00 / 1_000_000, "output": 15.00 / 1_000_000},
    "claude-haiku-4-5":  {"input": 1.00 / 1_000_000, "output": 5.00 / 1_000_000},
}


def claude_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimated USD cost of one Claude call at the given model's rates."""
    rates = CLAUDE_RATES[model]
    return input_tokens * rates["input"] + output_tokens * rates["output"]


# --- Ollama (local generation) ---
# Disabled by default: current hardware can't run local models. Set
# AITK_OLLAMA_ENABLED=1 after a hardware upgrade to re-enable local routing;
# `--route ollama` still works explicitly regardless of this flag.
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5-coder:14b"


def ollama_enabled() -> bool:
    """Whether local Ollama generation is available on this machine."""
    return os.environ.get("AITK_OLLAMA_ENABLED", "").lower() in ("1", "true", "yes")
