"""Tests for the generate → check → test → review → retry loop (all model calls stubbed)."""
import asyncio

import pytest

from aitk import generate
from aitk.config import claude_cost

GOOD = "def f():\n    \"\"\"One.\"\"\"\n    return 1\n"
BAD_TESTS = "def f():\n    \"\"\"One.\"\"\"\n    return 0\n"
SYNTAX_ERR = "def f(:\n    pass\n"
USAGE0 = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}


def edit(search, replace):
    return f"<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE"


class Harness:
    """Scripted generator + test runner + reviewer, recording what the loop asked of each."""

    def __init__(self, gen_replies, test_results, reviews=None):
        self.gen_replies = list(gen_replies)
        self.test_results = list(test_results)
        self.reviews = list(reviews or [])
        self.tasks, self.test_runs, self.review_calls = [], 0, 0

    async def generate_fn(self, task):
        self.tasks.append(task)
        stats = {**generate._zero_stats(), "claude_input_tokens": 100, "claude_output_tokens": 50}
        return self.gen_replies.pop(0), stats

    def run_tests(self, test_dir, module_dir=None):
        self.test_runs += 1
        ok = self.test_results.pop(0)
        out = "x PASSED\n1 passed" if ok else "x FAILED\nE assert 0 == 1\n1 failed"
        return ok, out

    def review(self, spec, code, test_out, versions):
        self.review_calls += 1
        r = self.reviews.pop(0) if self.reviews else {"passed": True, "issues": []}
        return {**r, "_usage": {**USAGE0, "input_tokens": 10, "output_tokens": 5}}


def run(h, tmp_path, monkeypatch, max_attempts=2, use_patch=True):
    monkeypatch.setattr(generate, "_run_tests", h.run_tests)
    monkeypatch.setattr(generate, "claude_review", h.review)
    out = tmp_path / "mod.py"
    its = asyncio.run(generate._generate_with_review(
        h.generate_fn, "SPEC", [], str(out), str(tmp_path), False, max_attempts, use_patch,
    ))
    return its, out


def test_clean_first_attempt_runs_one_review_and_stops(tmp_path, monkeypatch):
    h = Harness([GOOD], [True])
    its, _ = run(h, tmp_path, monkeypatch)
    assert len(its) == 1 and h.review_calls == 1 and len(h.tasks) == 1


def test_failing_tests_retry_without_spending_a_review(tmp_path, monkeypatch):
    h = Harness([BAD_TESTS, edit("    return 0", "    return 1")], [False, True])
    its, out = run(h, tmp_path, monkeypatch)
    assert len(its) == 2
    assert h.review_calls == 1                       # attempt 1 skipped review; attempt 2 reviewed
    assert its[0]["review"]["skipped"] is True
    assert "return 1" in out.read_text()             # the patch was applied
    assert "E assert 0 == 1" in h.tasks[1]           # test failure text was fed back
    assert its[1]["how"] == "patch"


def test_unappliable_patch_falls_back_to_rewrite_and_sums_both_calls(tmp_path, monkeypatch):
    h = Harness([BAD_TESTS, "REWRITE", GOOD], [False, True])
    its, out = run(h, tmp_path, monkeypatch)
    assert its[1]["how"] == "rewrite"
    assert out.read_text() == GOOD.strip() + "\n" or out.read_text().strip() == GOOD.strip()
    assert its[1]["gen_stats"]["claude_input_tokens"] == 200   # two calls in one attempt
    assert "Rewrite the implementation" in h.tasks[2]


def test_ollama_style_route_skips_patching(tmp_path, monkeypatch):
    h = Harness([BAD_TESTS, GOOD], [False, True])
    its, _ = run(h, tmp_path, monkeypatch, use_patch=False)
    assert len(h.tasks) == 2 and "Rewrite the implementation" in h.tasks[1]
    assert its[1]["how"] == "rewrite"


def test_max_attempts_is_honored_and_only_the_last_attempt_reviews(tmp_path, monkeypatch):
    h = Harness([BAD_TESTS] * 3, [False] * 3)
    its, _ = run(h, tmp_path, monkeypatch, max_attempts=3, use_patch=False)
    assert len(its) == 3 and h.review_calls == 1
    assert its[-1]["review"].get("skipped") is None   # final attempt got a real verdict


def test_single_attempt_never_retries(tmp_path, monkeypatch):
    h = Harness([BAD_TESTS], [False])
    its, _ = run(h, tmp_path, monkeypatch, max_attempts=1)
    assert len(its) == 1 and h.review_calls == 1


def test_static_error_skips_tests_and_review(tmp_path, monkeypatch):
    h = Harness([SYNTAX_ERR, GOOD], [True])
    its, _ = run(h, tmp_path, monkeypatch, use_patch=False)
    assert h.test_runs == 1                           # only the second attempt ran tests
    assert its[0]["static_errors"] and its[0]["review"]["skipped"]
    assert "Static analysis" in h.tasks[1]


def test_blocking_review_issue_triggers_retry_even_when_tests_pass(tmp_path, monkeypatch):
    blocking = {"passed": False, "issues": [{"severity": "error", "location": "f", "description": "bad", "fix": "fix"}]}
    h = Harness([GOOD, edit("    return 1", "    return 2")], [True, True], [blocking, {"passed": True, "issues": []}])
    its, _ = run(h, tmp_path, monkeypatch)
    assert len(its) == 2 and h.review_calls == 2
    assert "bad" in h.tasks[1]


def test_warnings_alone_do_not_retry(tmp_path, monkeypatch):
    warn = {"passed": True, "issues": [{"severity": "warning", "location": "f", "description": "meh", "fix": ""}]}
    h = Harness([GOOD], [True], [warn])
    its, _ = run(h, tmp_path, monkeypatch)
    assert len(its) == 1


def test_summarize_prices_generation_review_testgen_and_cache(tmp_path, monkeypatch):
    h = Harness([GOOD], [True])
    its, _ = run(h, tmp_path, monkeypatch)
    its[0]["gen_stats"]["claude_cache_read_tokens"] = 1000
    tg = {"input_tokens": 300, "output_tokens": 200, "cache_read_tokens": 0, "cache_write_tokens": 0}
    result = generate._summarize("claude", its, tg)
    expected = (
        claude_cost("claude-sonnet-5-5", 100, 50, 1000, 0)
        + claude_cost("claude-haiku-5-5", 10, 5)
        + claude_cost("claude-sonnet-5-5", 300, 200)
    )
    assert result["estimated_cost_usd"] == pytest.approx(expected, abs=1e-5)
    assert result["claude_input_tokens"] == 100 + 10 + 300


def test_ensure_tests_modes(tmp_path, monkeypatch):
    out = str(tmp_path / "widget.py")
    tests = tmp_path / "tests"
    good = "import widget\n\n\ndef test_a():\n    assert True\n"
    monkeypatch.setattr(generate, "generate_tests", lambda spec, module: (good, [], dict(USAGE0)))

    assert generate._ensure_tests("spec", out, str(tests), "never", False) == (None, None)

    path, usage = generate._ensure_tests("spec", out, str(tests), "auto", False)
    assert path.endswith("test_widget_generated.py") and usage is not None

    # Tests now exist: auto leaves them alone, always adds another suite.
    assert generate._ensure_tests("spec", out, str(tests), "auto", False) == (None, None)
    assert generate._ensure_tests("spec", out, str(tests), "always", False)[0] is not None


def test_ensure_tests_raises_when_generated_suite_is_invalid(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "generate_tests", lambda spec, module: ("x", ["contains no test_ functions"], dict(USAGE0)))
    with pytest.raises(RuntimeError, match="failed validation"):
        generate._ensure_tests("spec", str(tmp_path / "m.py"), str(tmp_path / "tests"), "auto", False)
