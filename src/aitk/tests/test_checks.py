"""Tests for aitk.checks — free pre-review static checks."""
import importlib.util

import pytest

from aitk.checks import static_check

needs_ruff = pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="ruff not installed")


def test_clean_code_has_no_errors(tmp_path):
    p = tmp_path / "m.py"
    code = "def f(x):\n    return x + 1\n"
    p.write_text(code)
    assert static_check(code, str(p)) == []


def test_syntax_error_is_reported_with_line(tmp_path):
    p = tmp_path / "m.py"
    code = "def f(:\n    pass\n"
    p.write_text(code)
    errors = static_check(code, str(p))
    assert len(errors) == 1 and "SyntaxError" in errors[0] and "line 1" in errors[0]


@needs_ruff
def test_undefined_name_is_reported(tmp_path):
    p = tmp_path / "m.py"
    code = "def f():\n    return missing_name\n"
    p.write_text(code)
    errors = static_check(code, str(p))
    assert errors and "missing_name" in errors[0]


@needs_ruff
def test_style_issues_are_not_blocking(tmp_path):
    p = tmp_path / "m.py"
    code = "import os\nx=1\n"  # unused import + spacing: style only
    p.write_text(code)
    assert static_check(code, str(p)) == []
