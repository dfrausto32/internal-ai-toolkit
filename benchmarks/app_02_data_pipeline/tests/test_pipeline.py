"""
Ground truth test suite for app_02_data_pipeline.

Never generate or modify these tests with AI — they define what correct means.
Run from the repo root: pytest benchmarks/app_02_data_pipeline/tests/ -v

Expects the implementation at: benchmarks/app_02_data_pipeline/generated/pipeline.py
Exports required from pipeline.py: run_pipeline(input_path, output_path, log_path) -> dict
"""
import csv
import json
import sys
from pathlib import Path

import pytest

_GENERATED_DIR = Path(__file__).parent.parent / "generated"
sys.path.insert(0, str(_GENERATED_DIR))

from pipeline import run_pipeline  # noqa: E402

COLUMNS = ["id", "name", "amount", "date", "status"]

_VALID = {"id": "1", "name": "john doe", "amount": "3.14159", "date": "2026-01-15", "status": "active"}


def _write_csv(path, rows, columns=None):
    cols = columns or COLUMNS
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _read_json(path):
    return json.loads(Path(path).read_text())


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_valid_rows_all_pass(tmp_path):
    inp = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    log = tmp_path / "log.json"
    _write_csv(inp, [_VALID, {**_VALID, "id": "2", "name": "jane smith"}])
    summary = run_pipeline(str(inp), str(out), str(log))
    rows = _read_csv(out)
    assert len(rows) == 2
    assert summary["passed"] == 2
    assert summary["failed"] == 0


def test_name_is_title_cased(tmp_path):
    inp = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    log = tmp_path / "log.json"
    _write_csv(inp, [{**_VALID, "name": "john doe"}])
    run_pipeline(str(inp), str(out), str(log))
    rows = _read_csv(out)
    assert rows[0]["name"] == "John Doe"


def test_amount_is_rounded_to_two_decimals(tmp_path):
    inp = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    log = tmp_path / "log.json"
    _write_csv(inp, [{**_VALID, "amount": "3.14159"}])
    run_pipeline(str(inp), str(out), str(log))
    rows = _read_csv(out)
    assert round(float(rows[0]["amount"]), 2) == 3.14


def test_date_preserved_in_output(tmp_path):
    inp = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    log = tmp_path / "log.json"
    _write_csv(inp, [{**_VALID, "date": "2026-06-05"}])
    run_pipeline(str(inp), str(out), str(log))
    rows = _read_csv(out)
    assert rows[0]["date"] == "2026-06-05"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_input_produces_empty_output(tmp_path):
    inp = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    log = tmp_path / "log.json"
    _write_csv(inp, [])
    summary = run_pipeline(str(inp), str(out), str(log))
    assert _read_csv(out) == []
    assert summary["total"] == 0
    assert summary["passed"] == 0
    assert summary["failed"] == 0


def test_all_invalid_rows_produces_empty_output(tmp_path):
    inp = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    log = tmp_path / "log.json"
    bad1 = {**_VALID, "amount": "not-a-number"}
    bad2 = {**_VALID, "id": "2", "status": "unknown"}
    _write_csv(inp, [bad1, bad2])
    summary = run_pipeline(str(inp), str(out), str(log))
    assert _read_csv(out) == []
    assert summary["passed"] == 0
    assert summary["failed"] == 2


# ---------------------------------------------------------------------------
# Row-level error handling
# ---------------------------------------------------------------------------

def test_invalid_amount_row_is_skipped(tmp_path):
    inp = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    log = tmp_path / "log.json"
    _write_csv(inp, [{**_VALID, "amount": "not-a-number"}])
    summary = run_pipeline(str(inp), str(out), str(log))
    assert _read_csv(out) == []
    assert summary["failed"] == 1
    assert summary["errors"][0]["field"] == "amount"


def test_negative_amount_row_is_skipped(tmp_path):
    inp = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    log = tmp_path / "log.json"
    _write_csv(inp, [{**_VALID, "amount": "-5.0"}])
    summary = run_pipeline(str(inp), str(out), str(log))
    assert _read_csv(out) == []
    assert summary["failed"] == 1
    assert summary["errors"][0]["field"] == "amount"


def test_invalid_date_format_row_is_skipped(tmp_path):
    inp = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    log = tmp_path / "log.json"
    _write_csv(inp, [{**_VALID, "date": "15/01/2026"}])
    summary = run_pipeline(str(inp), str(out), str(log))
    assert _read_csv(out) == []
    assert summary["failed"] == 1
    assert summary["errors"][0]["field"] == "date"


def test_invalid_status_row_is_skipped(tmp_path):
    inp = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    log = tmp_path / "log.json"
    _write_csv(inp, [{**_VALID, "status": "unknown"}])
    summary = run_pipeline(str(inp), str(out), str(log))
    assert _read_csv(out) == []
    assert summary["failed"] == 1
    assert summary["errors"][0]["field"] == "status"


def test_empty_name_row_is_skipped(tmp_path):
    inp = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    log = tmp_path / "log.json"
    _write_csv(inp, [{**_VALID, "name": ""}])
    summary = run_pipeline(str(inp), str(out), str(log))
    assert _read_csv(out) == []
    assert summary["failed"] == 1
    assert summary["errors"][0]["field"] == "name"


# ---------------------------------------------------------------------------
# Summary correctness
# ---------------------------------------------------------------------------

def test_summary_counts_are_correct(tmp_path):
    inp = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    log = tmp_path / "log.json"
    good = _VALID
    bad1 = {**_VALID, "id": "2", "amount": "not-a-number"}
    bad2 = {**_VALID, "id": "3", "status": "unknown"}
    _write_csv(inp, [good, bad1, bad2])
    summary = run_pipeline(str(inp), str(out), str(log))
    assert summary["total"] == 3
    assert summary["passed"] == 1
    assert summary["failed"] == 2
    assert len(summary["errors"]) == 2


# ---------------------------------------------------------------------------
# Schema-level error handling
# ---------------------------------------------------------------------------

def test_missing_required_column_raises(tmp_path):
    inp = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    log = tmp_path / "log.json"
    _write_csv(inp, [{"id": "1", "name": "test", "date": "2026-01-01", "status": "active"}],
               columns=["id", "name", "date", "status"])
    with pytest.raises(ValueError):
        run_pipeline(str(inp), str(out), str(log))
