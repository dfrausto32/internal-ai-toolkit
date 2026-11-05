"""Claude review step — scores generated code against spec and test results."""
import json

from aitk.config import REVIEW_MODEL, REVIEW_THINKING
from aitk.llm import call_claude

_SYSTEM = (
    "You are a senior Python engineer reviewing AI-generated code against a spec. "
    "Be specific and actionable. Only flag real issues — do not hallucinate problems. "
    "Respond with a single JSON object and nothing else."
)

_TEMPLATE = """\
## Spec
{spec}

## Environment (ground truth — these are the ACTUAL installed versions; do not assume \
or guess a different version when diagnosing import/API issues)
{installed_versions}

## Generated code
```python
{code}
```

## Test results
```
{test_output}
```

Review the generated code for these defect classes:
1. Tests failing — exact root cause in the code
2. Missing schema-level guards — are all required inputs validated before processing?
3. Falsy numeric checks — `not value` where `value is None` is correct?
4. Deprecated imports — pydantic.v1, sqlalchemy.ext.declarative, etc.
5. Missing docstrings — all public functions and classes documented?
6. Any other blocking correctness issue

Output this exact JSON structure:
{{
  "passed": <true if all tests pass AND no blocking issues>,
  "issues": [
    {{
      "severity": "error or warning",
      "location": "<function name or line description>",
      "description": "<what is wrong>",
      "fix": "<exact code change to make>"
    }}
  ],
  "scores": {{
    "structure": <0-3>,
    "documentation": <0-3>
  }},
  "summary": "<one sentence overall assessment>"
}}
"""


def claude_review(spec: str, code: str, test_output: str, installed_versions: str) -> dict:
    """Call Claude to review generated code against the spec, test results, and real installed versions."""
    raw, usage = call_claude(
        REVIEW_MODEL,
        _TEMPLATE.format(
            spec=spec, code=code, test_output=test_output, installed_versions=installed_versions
        ),
        system=_SYSTEM,
        max_tokens=2048,
        thinking=REVIEW_THINKING,
        cache=False,  # every review prompt is unique (new code each time); caching only adds write cost
    )
    raw = raw.strip()
    if raw.startswith("```"):
        newline = raw.find("\n")
        raw = raw[newline + 1:] if newline != -1 else raw[3:]
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")].rstrip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # A malformed review must not crash a run we've already paid for —
        # degrade to a non-blocking "review unavailable" result instead.
        result = {
            "passed": False,
            "issues": [],
            "scores": {},
            "summary": f"Review skipped: model response was not valid JSON ({raw[:120]!r})",
        }
    result["_usage"] = usage
    return result
