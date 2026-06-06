"""Async Ollama worker — builds a context-aware system prompt and streams generated code."""
import json
import time

import httpx

OLLAMA_URL = "http://localhost:11434"

_BASE_RULES = (
    "You are an expert software developer. Write production-quality, well-structured Python code. "
    "Follow every rule below without exception. "
    "STDLIB FIRST: Use only Python standard library unless the spec explicitly names a third-party "
    "package. Never import FastAPI, SQLAlchemy, Pydantic, or any other framework unless the spec "
    "requires it. "
    "DOCUMENTATION: Add a one-line docstring to every function and class. "
    "DEFENSIVE CHECKS: Before processing any collection of inputs (CSV rows, dict keys, list items), "
    "validate that all required fields/columns exist first — raise ValueError with a clear message "
    "immediately; do not let a missing field surface as KeyError inside the processing loop. "
    "NUMERIC VALIDATION: When checking whether a numeric field is absent, use 'value is None', "
    "never 'not value' — 'not 0' is True and would incorrectly reject a valid zero. "
    "OUTPUT FORMAT: Return ONLY raw Python code. Do not wrap output in markdown fences. "
    "Do not include backticks, ```python, or any markup. "
    "Your response must begin with the first line of Python code."
)

# Injected only when the spec's `frameworks` list includes the matching key
_FRAMEWORK_RULES: dict[str, str] = {
    "pydantic": (
        "IF USING PYDANTIC: Use Pydantic v2 — import BaseModel and Field from pydantic "
        "(not pydantic.v1); use model_config = ConfigDict(from_attributes=True) instead of orm_mode."
    ),
    "sqlalchemy": (
        "IF USING SQLALCHEMY: Use SQLAlchemy 2.0 — import DeclarativeBase from sqlalchemy.orm "
        "(not sqlalchemy.ext.declarative); define Base as 'class Base(DeclarativeBase): pass'; "
        "never call declarative_base()."
    ),
    "fastapi": (
        "IF USING FASTAPI: Register routes without trailing slashes (/tasks not /tasks/). "
        "Add docstrings to all route functions and Pydantic model classes."
    ),
}


def build_system_prompt(frameworks: list[str]) -> str:
    """Compose base rules plus any framework-specific rules declared in the spec."""
    parts = [_BASE_RULES]
    for fw in frameworks:
        rule = _FRAMEWORK_RULES.get(fw.lower().strip())
        if rule:
            parts.append(rule)
    return " ".join(parts)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from model output."""
    text = text.strip()
    if text.startswith("```"):
        newline = text.find("\n")
        text = text[newline + 1:] if newline != -1 else text[3:]
    if text.endswith("```"):
        text = text[: text.rfind("```")].rstrip()
    return text.strip()


async def ollama_generate(
    user_prompt: str,
    frameworks: list[str] | None = None,
    model: str = "qwen2.5-coder:14b",
    url: str = OLLAMA_URL,
) -> tuple[str, dict]:
    """Call Ollama /api/generate (streaming), return (code_text, stats_dict)."""
    system = build_system_prompt(frameworks or [])
    payload = {"model": model, "prompt": user_prompt, "system": system, "stream": True}

    chunks: list[str] = []
    final_meta: dict = {}
    t_start = time.monotonic()

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", f"{url}/api/generate", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("done"):
                    final_meta = chunk
                else:
                    chunks.append(chunk.get("response", ""))

    elapsed = time.monotonic() - t_start
    text = _strip_fences("".join(chunks))

    eval_count = final_meta.get("eval_count", 0)
    eval_duration_s = final_meta.get("eval_duration", 0) / 1e9
    return text, {
        "model": model,
        "prompt_tokens": final_meta.get("prompt_eval_count", 0),
        "response_tokens": eval_count,
        "tokens_per_second": round(eval_count / max(eval_duration_s, 0.001), 1),
        "elapsed_s": round(elapsed, 2),
    }
