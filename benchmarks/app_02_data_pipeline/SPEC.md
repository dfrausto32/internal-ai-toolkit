---
language: python
frameworks: []
estimated_lines: 90
test_command: pytest benchmarks/app_02_data_pipeline/tests/ -v
---

# Spec: app_02_data_pipeline

A CSV ingestion and transformation pipeline that validates rows, applies field transforms, writes clean output, and produces a JSON summary log.

---

## Deliverable

One file: `benchmarks/app_02_data_pipeline/generated/pipeline.py`

Single-file. No sub-packages.

---

## Required export from pipeline.py

The test suite imports this directly — it must exist with this exact signature:

```python
def run_pipeline(input_path: str, output_path: str, log_path: str) -> dict:
    ...
```

**Returns** a summary dict:
```json
{
  "total": 5,
  "passed": 3,
  "failed": 2,
  "errors": [
    {"row": 2, "field": "amount", "reason": "not a non-negative number"},
    {"row": 4, "field": "status", "reason": "invalid status value"}
  ]
}
```

- `row` is the 1-indexed data row number (not counting the header)
- `errors` is a list of dicts, one per failed row, with `row`, `field`, and `reason` keys

**Raises** `ValueError` if the input CSV is missing any required column.

---

## Input CSV schema

Columns (must all be present): `id`, `name`, `amount`, `date`, `status`

| Field | Type | Validation rule |
|-------|------|-----------------|
| `id` | int | Must parse as a positive integer |
| `name` | str | Required, must not be empty |
| `amount` | float | Must parse as a float, must be ≥ 0 |
| `date` | str | Must match `YYYY-MM-DD` format |
| `status` | str | Must be one of: `active`, `inactive`, `pending` |

---

## Transforms (applied to valid rows before writing output)

1. `name` → title case (`"john doe"` → `"John Doe"`)
2. `amount` → rounded to 2 decimal places (`"3.14159"` → `3.14`)
3. `date` → preserved as-is (already validated)

---

## Output CSV

- Same 5 columns: `id`, `name`, `amount`, `date`, `status`
- Contains only rows that passed all validations
- Transforms applied

---

## Summary JSON

Written to `log_path`. Format:

```json
{
  "total": 5,
  "passed": 3,
  "failed": 2,
  "errors": [
    {"row": 2, "field": "amount", "reason": "not a non-negative number"}
  ]
}
```

---

## CLI interface

The script must also be runnable as a CLI tool:

```bash
python pipeline.py --input data.csv --output out.csv --log summary.json
```

Arguments: `--input`, `--output`, `--log` (all required).

---

## Error handling behavior

- **Invalid row:** skip it, append an error entry to the summary, continue processing remaining rows
- **Missing required column:** raise `ValueError` immediately, do not process any rows
- The `reason` string in errors should be human-readable but does not need to match exact wording

---

## Success criteria

```bash
pytest benchmarks/app_02_data_pipeline/tests/ -v
```

All 13 tests pass, 0 failures, 0 errors.
