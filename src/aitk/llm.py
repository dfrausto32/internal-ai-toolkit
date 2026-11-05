"""Single entry point for Claude calls — client setup, caching, usage, and stop-reason handling."""
import os

import anthropic


def call_claude(
    model: str,
    prompt: str,
    *,
    max_tokens: int,
    system: str | None = None,
    effort: str | None = None,
    thinking: dict | None = None,
    cache: bool = True,
) -> tuple[str, dict]:
    """One Claude call. Returns (text, usage).

    Caching: when `system` is given, the cache breakpoint goes on the system block so a
    stable system prompt (e.g. role + spec) is reused across calls that share it; with no
    system prompt, top-level automatic caching is used. Caches are per-model, and a prefix
    below the model's minimum cacheable size silently doesn't cache — check
    usage["cache_read_tokens"] to see whether it is paying off.

    usage keys: input_tokens (uncached), output_tokens, cache_read_tokens,
    cache_write_tokens, stop_reason.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set")

    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system and cache:
        kwargs["system"] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
    elif system:
        kwargs["system"] = system
    elif cache:
        kwargs["cache_control"] = {"type": "ephemeral"}
    if effort:
        kwargs["output_config"] = {"effort": effort}
    if thinking:
        kwargs["thinking"] = thinking

    message = anthropic.Anthropic(api_key=api_key).messages.create(**kwargs)

    if message.stop_reason == "refusal":
        raise RuntimeError(f"{model} declined the request (stop_reason=refusal)")

    text = "".join(b.text for b in message.content if b.type == "text")
    usage = {
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
        "cache_read_tokens": getattr(message.usage, "cache_read_input_tokens", 0) or 0,
        "cache_write_tokens": getattr(message.usage, "cache_creation_input_tokens", 0) or 0,
        "stop_reason": message.stop_reason,
    }
    return text, usage
