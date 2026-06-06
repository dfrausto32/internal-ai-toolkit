---
language: python
frameworks: []
estimated_lines: 12
test_command: pytest .github/aitk-smoke/tests/ -v
---

# Spec: integer adder (CI smoke test)

This spec exists only to exercise the `aitk-generate` reusable workflow in CI —
it is not a quality benchmark. Keep it tiny and cheap to generate.

One file: `smoke.py`

## Required exports

| Name | Signature | Returns |
|------|-----------|---------|
| `add` | `(a: int, b: int) -> int` | The sum of `a` and `b` |

## Validation rules

- Raise `TypeError` if either argument is not an `int` (booleans count as `int` in Python — that's fine).

## Success criteria

`pytest .github/aitk-smoke/tests/ -v` passes with 0 failures.
