"""Tests for aitk.specgen — spec draft validation (no API calls)."""
from aitk.specgen import _TEMPLATE, spec_problems

GOOD_SPEC = """\
---
language: python
frameworks: [fastapi]
estimated_lines: 120
test_command: pytest tests/ -v
---
# Widget API

## Overview
A small API.
"""


def test_valid_draft_has_no_problems():
    assert spec_problems(GOOD_SPEC) == []


def test_stdlib_only_frameworks_list_is_valid():
    text = GOOD_SPEC.replace("frameworks: [fastapi]", "frameworks: []")
    assert spec_problems(text) == []


def test_missing_frontmatter_is_flagged():
    problems = spec_problems("# Just a body\nNo frontmatter here.\n")
    assert problems == ["missing or unparseable YAML frontmatter block"]


def test_non_integer_estimated_lines_is_flagged():
    text = GOOD_SPEC.replace("estimated_lines: 120", "estimated_lines: about a hundred")
    assert any("estimated_lines" in p for p in spec_problems(text))


def test_missing_frameworks_is_flagged():
    text = GOOD_SPEC.replace("frameworks: [fastapi]\n", "")
    assert any("frameworks" in p for p in spec_problems(text))


def test_empty_body_is_flagged():
    text = GOOD_SPEC.split("# Widget API")[0]
    assert any("body" in p for p in spec_problems(text))


def test_prompt_template_embeds_description_and_frontmatter_contract():
    prompt = _TEMPLATE.format(description="Build a rate limiter")
    assert "Build a rate limiter" in prompt
    assert "estimated_lines" in prompt
    assert "frameworks" in prompt
    assert "test_command" in prompt
