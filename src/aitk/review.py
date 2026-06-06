"""Claude review step — scores generated code against spec and test results."""
import json
import os

import anthropic

MODEL = "claude-sonnet-4-6"

_SYSTEM = (
    "You are a senior Python engineer reviewing AI-generated code against a spec. "
    "Be specific and actionable. Only flag real issues — do not hallucinate problems. "
    "Respond with a single JSON object and nothing else."
)

_TEMPLATE = """\
## Spec
{spec}

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


def claude_review(spec: str, code: str, test_output: str) -> dict:
    """Call Claude to review generated code against the spec and test results."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set")

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=_SYSTEM,
        messages=[{"role": "user", "content": _TEMPLATE.format(
            spec=spec, code=code, test_output=test_output
        )}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        newline = raw.find("\n")
        raw = raw[newline + 1:] if newline != -1 else raw[3:]
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")].rstrip()

    result = json.loads(raw)
    result["_usage"] = {
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
    }
    return result
