"""Tests for aitk.generate — pure helpers (no Ollama/Claude calls)."""
from aitk.generate import _condense_for_review


def test_condense_drops_passed_lines_but_keeps_summary():
    text = (
        "collecting ... collected 2 items\n"
        "tests/test_x.py::test_a PASSED [ 50%]\n"
        "tests/test_x.py::test_b PASSED [100%]\n"
        "\n"
        "============================== 2 passed in 0.02s ==============================\n"
    )

    condensed = _condense_for_review(text)

    assert "PASSED" not in condensed
    assert "collected 2 items" in condensed
    assert "2 passed in 0.02s" in condensed


def test_condense_keeps_failure_detail_and_failed_lines():
    text = (
        "tests/test_x.py::test_a PASSED [ 33%]\n"
        "tests/test_x.py::test_b FAILED [ 66%]\n"
        "tests/test_x.py::test_c PASSED [100%]\n"
        "\n"
        "=================================== FAILURES ===================================\n"
        "_________________________________ test_b _______________________________________\n"
        "tests/test_x.py:12: in test_b\n"
        "    assert result == expected\n"
        "E   AssertionError: assert {'field': 'amount'} == {'field': 'id'}\n"
        "=========================== short test summary info ============================\n"
        "FAILED tests/test_x.py::test_b - AssertionError: assert ...\n"
        "========================= 2 passed, 1 failed in 0.05s ==========================\n"
    )

    condensed = _condense_for_review(text)

    # The two PASSED lines are gone...
    assert condensed.count("PASSED") == 0
    # ...but every failure-relevant line survives, including the FAILED markers
    # in the verbose listing, the FAILURES traceback, and the summary.
    assert "test_b FAILED" in condensed
    assert "AssertionError: assert {'field': 'amount'} == {'field': 'id'}" in condensed
    assert "FAILED tests/test_x.py::test_b - AssertionError" in condensed
    assert "2 passed, 1 failed in 0.05s" in condensed


def test_condense_is_significantly_smaller_for_large_passing_suites():
    # On a 13-test all-passing run this measured ~79% smaller — pin a generous
    # lower bound so a future regression (e.g. an over-broad filter that stops
    # matching) gets caught without being brittle to exact byte counts.
    lines = [f"tests/test_x.py::test_{i:02d} PASSED [{i * 10:3d}%]" for i in range(10)]
    text = "collected 10 items\n\n" + "\n".join(lines) + "\n\n10 passed in 0.10s\n"

    condensed = _condense_for_review(text)

    assert len(condensed) < len(text) * 0.5
    assert "10 passed in 0.10s" in condensed
    assert "collected 10 items" in condensed
