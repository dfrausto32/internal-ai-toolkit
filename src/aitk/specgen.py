"""Draft a SPEC.md from a plain-English description using Claude.

The planning layer in front of `aitk generate`: turn a rough idea into a
complete, routable spec — frontmatter the router can consume plus a body
precise enough for one-pass code generation.
"""
import os

import anthropic

from aitk.agents import _strip_fences
from aitk.config import GENERATION_MODEL, claude_cost
from aitk.spec import parse_spec_text

_SYSTEM = (
    "You are a senior engineer turning a rough feature description into a precise, "
    "buildable specification for an AI code-generation pipeline. The spec must be "
    "complete enough that a code generator can implement it in one pass with no "
    "follow-up questions."
)

_TEMPLATE = """\
Write a complete SPEC.md for the following request.

REQUEST:
{description}

The file must start with exactly this YAML frontmatter shape:

---
language: python
frameworks: [<pip package names of third-party frameworks needed, or [] for stdlib-only>]
estimated_lines: <realistic integer estimate of the generated implementation's size>
test_command: pytest tests/ -v
---

Then a markdown body with these sections:
# <Module name>
## Overview            — 2-3 sentences on purpose and scope
## Public interface    — every function/class to export, with exact signatures and types
## Behavior            — precise rules, including validation and error handling
## Edge cases          — inputs that must be handled defensively
## Out of scope        — what NOT to build

Rules:
- Be concrete: exact names, exact exceptions, exact field validations.
- Only list a framework if the implementation genuinely needs it.
- Return ONLY the file content — no markdown fences around it, no commentary.
"""

_FIX_TEMPLATE = """\
Your previous SPEC.md draft had these problems:
{problems}

Fix them and return the corrected, complete SPEC.md. Same rules as before:
frontmatter first, then the full body, file content only.

PREVIOUS DRAFT:
{draft}
"""


def spec_problems(text: str) -> list[str]:
    """Return validation problems with a spec draft (empty list = usable)."""
    problems = []
    meta, body = parse_spec_text(text)
    if not meta:
        problems.append("missing or unparseable YAML frontmatter block")
        return problems
    if not isinstance(meta.get("estimated_lines"), int):
        problems.append("frontmatter needs an integer estimated_lines (the router depends on it)")
    if not isinstance(meta.get("frameworks"), list):
        problems.append("frontmatter needs a frameworks list (may be [])")
    if not body.strip():
        problems.append("spec body is empty")
    return problems


def draft_spec(description: str, max_attempts: int = 2) -> tuple[str, list[str], dict]:
    """Draft a SPEC.md with Claude, re-prompting once if validation fails.

    Returns (spec_text, remaining_problems, usage_dict).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set")
    client = anthropic.Anthropic(api_key=api_key)

    total_in = total_out = 0
    prompt = _TEMPLATE.format(description=description)
    text, problems = "", ["no draft produced"]

    for _ in range(max_attempts):
        message = client.messages.create(
            model=GENERATION_MODEL,
            max_tokens=4096,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        total_in += message.usage.input_tokens
        total_out += message.usage.output_tokens

        text = _strip_fences(message.content[0].text)
        problems = spec_problems(text)
        if not problems:
            break
        prompt = _FIX_TEMPLATE.format(
            problems="\n".join(f"- {p}" for p in problems), draft=text
        )

    usage = {
        "input_tokens": total_in,
        "output_tokens": total_out,
        "cost_usd": round(claude_cost(GENERATION_MODEL, total_in, total_out), 5),
    }
    return text, problems, usage
