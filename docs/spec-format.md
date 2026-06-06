# Spec Format

Every spec file passed to `aitk generate` should be a Markdown file with an optional YAML frontmatter block at the top. The frontmatter controls routing and prompt construction. The body is free-form prose describing what to build.

---

## Frontmatter

```yaml
---
language: python
frameworks: [fastapi, sqlalchemy, pydantic]
estimated_lines: 200
test_command: pytest tests/ -v
---
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `language` | string | no | Programming language. Currently only `python` is supported. |
| `frameworks` | list | no | Third-party frameworks the generated code must use. Controls which rules are injected into the Ollama system prompt. Supported values: `fastapi`, `sqlalchemy`, `pydantic`. Empty list `[]` means stdlib only. |
| `estimated_lines` | int | no | Expected length of the generated output in lines of code. Used by the auto-router to decide Ollama vs Claude. If omitted, estimated from spec word count (less accurate). |
| `test_command` | string | no | Informational — the command used to run tests. Not executed by `aitk` directly (pass `--tests` on the CLI instead). |

---

## Routing decision

The `estimated_lines` field directly drives the `--route auto` decision:

```
output_tokens = estimated_lines × 12
route = "ollama"  if output_tokens >= 1225  (~100 lines)
route = "claude"  otherwise
```

Run `aitk route --spec SPEC.md` to preview the decision without generating anything.

---

## Framework rules

When a framework is listed in `frameworks`, the corresponding rule is appended to the Ollama system prompt. This prevents contamination — SQLAlchemy rules never appear in a stdlib CSV pipeline.

| Framework | Rule injected |
|-----------|---------------|
| `pydantic` | Use Pydantic v2 imports and `ConfigDict` instead of `orm_mode` |
| `sqlalchemy` | Use SQLAlchemy 2.0 `DeclarativeBase` subclass pattern |
| `fastapi` | No trailing slashes on routes; docstrings on route functions |

Raw Claude generation ignores this field — Claude knows the correct idioms natively.

---

## Body

Everything after the closing `---` is the spec body. It is passed verbatim to the generator as the task description. Write it in plain prose or Markdown — tables, code blocks, and bullet lists all work.

Sections that help the generator most:
- **Required exports** — exact function/class names the test suite imports
- **Data model** — field names, types, constraints
- **Error behaviour** — what to raise, when
- **Success criteria** — the exact `pytest` command and expected result

---

## Minimal example

```markdown
---
language: python
frameworks: []
estimated_lines: 50
test_command: pytest tests/test_parser.py -v
---

# Spec: CSV row parser

One file: `src/parser.py`

## Required exports

| Name | Signature | Returns |
|------|-----------|---------|
| `parse_row` | `(row: dict) -> dict` | Cleaned row dict |

## Validation rules

- `amount`: must be a non-negative float
- `date`: must match YYYY-MM-DD

Raise `ValueError` with the field name if validation fails.
```
