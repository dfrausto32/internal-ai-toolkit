"""Async Ollama worker — builds a context-aware system prompt and streams generated code."""
import json
import time

import httpx

OLLAMA_URL = "http://localhost:11434"

_BASE_RULES = (
    "You are an expert software developer. Write production-quality, well-structured Python code. "
    "Follow every rule below exactly — they are requirements, not suggestions.\n"
    "\n"
    "1. STDLIB FIRST: use only the Python standard library unless the spec explicitly names a "
    "third-party package. Never import FastAPI, SQLAlchemy, Pydantic, or any other framework "
    "unless the spec requires it.\n"
    "2. DOCUMENTATION: every function and class gets a one-line docstring — including small "
    "helpers, route handlers, and model classes. No exceptions.\n"
    "3. DEFENSIVE CHECKS: before processing any collection of inputs (CSV rows, dict keys, "
    "list items, request bodies), validate that all required fields/columns exist first — raise "
    "ValueError with a clear message immediately; never let a missing field surface as KeyError "
    "mid-loop.\n"
    "4. NULL-SAFETY: for any value that might legitimately be None, zero, an empty string, or an "
    "empty collection, check `value is None` — never `not value`. `not 0`, `not \"\"`, and "
    "`not []` are all True and would wrongly reject valid data.\n"
    "5. OUTPUT FORMAT: return ONLY raw Python code. No markdown fences, no backticks, no "
    "```python, no explanation. Your response begins with the first line of Python code."
)

# Injected only when the spec's `frameworks` list includes the matching key.
# Each rule below leads with a concrete code pattern rather than prose: qwen2.5-coder's
# training-data priors for these libraries skew toward older APIs (SQLAlchemy 1.x style,
# Pydantic v1, undocumented FastAPI routes), and a worked example competes with those
# priors far more reliably than a one-line instruction telling it not to use them.
_FRAMEWORK_RULES: dict[str, str] = {
    "pydantic": (
        "IF USING PYDANTIC: match this exact pattern (Pydantic v2) — substitute your own "
        "field names —\n"
        "    from pydantic import BaseModel, ConfigDict, Field\n"
        "\n"
        "    class ItemCreate(BaseModel):\n"
        "        \"\"\"Request schema for creating an item.\"\"\"\n"
        "        model_config = ConfigDict(from_attributes=True)\n"
        "        name: str = Field(..., description=\"Item name\")\n"
        "\n"
        "Never import from pydantic.v1, never write `class Config` or `orm_mode = True` — "
        "model_config = ConfigDict(...) replaces both."
    ),
    "sqlalchemy": (
        "IF USING SQLALCHEMY: match this exact pattern for the declarative base (SQLAlchemy "
        "2.0) — keep using Column for fields, only the base changes —\n"
        "    from sqlalchemy import Column, Integer\n"
        "    from sqlalchemy.orm import DeclarativeBase\n"
        "\n"
        "    class Base(DeclarativeBase):\n"
        "        \"\"\"Declarative base shared by all ORM models.\"\"\"\n"
        "\n"
        "    class Item(Base):\n"
        "        \"\"\"ORM model for an item row.\"\"\"\n"
        "        __tablename__ = \"items\"\n"
        "        id = Column(Integer, primary_key=True)\n"
        "\n"
        "Never import from sqlalchemy.ext.declarative and never call declarative_base() — "
        "class Base(DeclarativeBase) replaces it entirely."
    ),
    "fastapi": (
        "IF USING FASTAPI: register routes without trailing slashes (/tasks not /tasks/). "
        "Every route function gets a one-line docstring directly under its decorator and "
        "signature — and so does every Pydantic request/response model class. Match this "
        "shape exactly —\n"
        "    @app.get(\"/items/{item_id}\")\n"
        "    def read_item(item_id: int, db: Session = Depends(get_db)) -> ItemOut:\n"
        "        \"\"\"Fetch a single item by its ID.\"\"\"\n"
        "        ...\n"
    ),
}


def build_system_prompt(frameworks: list[str]) -> str:
    """Compose base rules plus any framework-specific rules declared in the spec."""
    parts = [_BASE_RULES]
    for fw in frameworks:
        rule = _FRAMEWORK_RULES.get(fw.lower().strip())
        if rule:
            parts.append(rule)
    return "\n\n".join(parts)


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
