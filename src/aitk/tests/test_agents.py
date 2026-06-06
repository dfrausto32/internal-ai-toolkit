"""Tests for aitk.agents — system-prompt construction and output cleanup."""
from aitk.agents import _strip_fences, build_system_prompt


def test_build_system_prompt_with_no_frameworks_is_stdlib_only():
    prompt = build_system_prompt([])

    assert "STDLIB FIRST" in prompt
    assert "IF USING PYDANTIC" not in prompt
    assert "IF USING SQLALCHEMY" not in prompt
    assert "IF USING FASTAPI" not in prompt


def test_build_system_prompt_injects_only_requested_framework_rules():
    prompt = build_system_prompt(["fastapi"])

    assert "IF USING FASTAPI" in prompt
    assert "IF USING PYDANTIC" not in prompt
    assert "IF USING SQLALCHEMY" not in prompt


def test_build_system_prompt_injects_multiple_framework_rules():
    prompt = build_system_prompt(["fastapi", "sqlalchemy", "pydantic"])

    assert "IF USING FASTAPI" in prompt
    assert "IF USING SQLALCHEMY" in prompt
    assert "IF USING PYDANTIC" in prompt


def test_build_system_prompt_is_case_and_whitespace_insensitive():
    assert build_system_prompt(["  FastAPI  "]) == build_system_prompt(["fastapi"])


def test_build_system_prompt_ignores_unknown_frameworks():
    prompt = build_system_prompt(["django"])

    assert "STDLIB FIRST" in prompt
    assert "django" not in prompt.lower().replace("stdlib", "")  # no rule text leaked in


def test_strip_fences_removes_python_fence():
    raw = "```python\ndef foo():\n    return 1\n```"
    assert _strip_fences(raw) == "def foo():\n    return 1"


def test_strip_fences_removes_bare_fence():
    raw = "```\nx = 1\n```"
    assert _strip_fences(raw) == "x = 1"


def test_strip_fences_leaves_unfenced_code_untouched():
    raw = "def foo():\n    return 1"
    assert _strip_fences(raw) == raw
