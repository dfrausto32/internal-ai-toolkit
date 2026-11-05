"""Tests for aitk.patching — SEARCH/REPLACE edit application."""
from aitk.patching import apply_edits

CODE = "def a():\n    return 1\n\n\ndef b():\n    return 2\n"


def block(search: str, replace: str) -> str:
    return f"<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE"


def test_single_block_is_applied():
    out = apply_edits(CODE, block("    return 1", "    return 10"))
    assert out == CODE.replace("return 1", "return 10")


def test_multiple_blocks_apply_in_order():
    resp = block("    return 1", "    return 10") + "\n" + block("    return 2", "    return 20")
    out = apply_edits(CODE, resp)
    assert "return 10" in out and "return 20" in out


def test_block_that_matches_nothing_fails_the_whole_patch():
    assert apply_edits(CODE, block("    return 99", "    return 0")) is None


def test_ambiguous_match_fails():
    code = "x = 1\nx = 1\n"
    assert apply_edits(code, block("x = 1", "x = 2")) is None


def test_one_bad_block_means_no_partial_application():
    resp = block("    return 1", "    return 10") + "\n" + block("nope", "x")
    assert apply_edits(CODE, resp) is None


def test_response_without_blocks_returns_none():
    assert apply_edits(CODE, "REWRITE") is None


def test_empty_replacement_deletes_the_matched_lines():
    resp = "<<<<<<< SEARCH\n\n\ndef b():\n    return 2\n=======\n>>>>>>> REPLACE"
    out = apply_edits(CODE, resp)
    assert out is not None and "def b" not in out


def test_empty_search_is_rejected():
    assert apply_edits(CODE, "<<<<<<< SEARCH\n\n=======\nx\n>>>>>>> REPLACE") is None
