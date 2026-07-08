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

---

## Node specs (Phase 5)

A **node spec** describes one node in a plan's DAG (see
[design-parallel-orchestration.md](design-parallel-orchestration.md)). The planner writes one
per node to `.aitk/plans/<feature>/<node-id>.md`; the body is an expanded slice of the main spec
with everything that node needs before writing. It reuses the frontmatter convention above plus
these fields (parsed by `aitk.plan.parse_node_spec`):

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | **Required.** Unique node id within the plan. |
| `depends_on` | list | Node ids this node depends on. Must resolve; must not form a cycle. |
| `output_scope` | list | Files / directory prefixes this node writes. Used to serialize nodes with overlapping scopes. |
| `acceptance_criteria` | list | Plain strings or `{id, text}` mappings. Strings get positional ids (`AC-1`…). Ids must be unique. |
| `validation_kind` | string | `automated` (tests run) or `gated` (no automated test — reviewer/human gate). |
| `test_command` | string | Executed for `automated` nodes (promoted from informational). |

```markdown
---
id: api-layer
depends_on: [models]
output_scope: [src/api/, src/api.py]
validation_kind: automated
test_command: pytest tests/api -q
acceptance_criteria:
  - id: AC-1
    text: GET /items returns 200 with a list
  - POST /items validates the body and returns 201
---
# Node: API layer
...expanded prose for this node...
```

`validate_plan()` checks the whole set: unique ids, resolvable `depends_on`, no cycles, valid
`validation_kind`, unique criterion ids. `find_scope_conflicts()` reports overlapping
`output_scope`s for the scheduler's write-lease layer.

