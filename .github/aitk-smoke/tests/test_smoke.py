"""
Ground-truth test suite for the aitk-generate CI smoke test.

This is plumbing, not a quality benchmark — it exists to verify the
aitk-generate.yml reusable workflow runs end to end (checkout, install,
generate, test, outputs). Never generate or modify this file with AI.

Expects the implementation at: .github/aitk-smoke/generated/smoke.py
Exports required from smoke.py: add(a: int, b: int) -> int
"""
import sys
from pathlib import Path

import pytest

_GENERATED_DIR = Path(__file__).parent.parent / "generated"
sys.path.insert(0, str(_GENERATED_DIR))

from smoke import add  # noqa: E402


def test_add_positive_numbers():
    assert add(2, 3) == 5


def test_add_handles_negatives():
    assert add(-1, 1) == 0


def test_add_rejects_non_int():
    with pytest.raises(TypeError):
        add("2", 3)
