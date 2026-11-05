"""Tests for aitk.testgen — independent spec-derived test writer (no API calls)."""
from unittest.mock import patch

from aitk import testgen
from aitk.testgen import generate_tests, has_tests, validate_tests, write_generated_tests

GOOD = "import widget\n\n\ndef test_it():\n    \"\"\"Rule 1.\"\"\"\n    assert widget.f() == 1\n"
USAGE = {"input_tokens": 10, "output_tokens": 20, "cache_read_tokens": 0, "cache_write_tokens": 0, "stop_reason": "end_turn"}


def test_has_tests_detects_test_files(tmp_path):
    assert not has_tests(str(tmp_path / "missing"))
    assert not has_tests(str(tmp_path))
    (tmp_path / "helpers.py").write_text("")
    assert not has_tests(str(tmp_path))
    (tmp_path / "test_x.py").write_text("")
    assert has_tests(str(tmp_path))


def test_validate_accepts_good_file():
    assert validate_tests(GOOD, "widget") == []


def test_validate_flags_syntax_error_no_tests_and_missing_import():
    assert "not valid Python" in validate_tests("def (:", "widget")[0]
    assert any("no test_ functions" in p for p in validate_tests("import widget\n", "widget"))
    assert any("never imports" in p for p in validate_tests("def test_a():\n    pass\n", "widget"))


def test_prompt_contains_only_the_spec_and_module_not_code():
    with patch.object(testgen, "call_claude", return_value=(GOOD, USAGE)) as call:
        generate_tests("SPEC TEXT", "widget")
    prompt = call.call_args.args[1]
    assert "SPEC TEXT" in prompt and "`widget`" in prompt
    assert "have NOT seen the implementation" in call.call_args.kwargs["system"]


def test_generate_retries_once_on_invalid_output_and_sums_usage():
    replies = [("not python at all (", USAGE), (GOOD, USAGE)]
    with patch.object(testgen, "call_claude", side_effect=replies) as call:
        code, problems, usage = generate_tests("spec", "widget")
    assert problems == [] and code == GOOD.strip()
    assert call.call_count == 2
    assert usage["input_tokens"] == 20 and usage["output_tokens"] == 40


def test_generate_reports_problems_after_retries_exhausted():
    with patch.object(testgen, "call_claude", return_value=("x = 1", USAGE)):
        _, problems, _ = generate_tests("spec", "widget")
    assert problems


def test_write_generated_tests_names_file_after_module(tmp_path):
    path = write_generated_tests(str(tmp_path / "tests"), "widget", GOOD)
    assert path.name == "test_widget_generated.py" and path.read_text() == GOOD
