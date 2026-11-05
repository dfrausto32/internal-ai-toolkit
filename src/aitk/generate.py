"""Core generate loop: tests → (Ollama | Claude) generation → free checks → tests → review → retry.

Both routes run the same pipeline; they differ only in who writes the code. Each attempt:

  1. Free static checks (syntax, undefined names). A failure skips everything below.
  2. The test suite. A failure retries immediately — no review call is spent on code that
     visibly doesn't work. On the final attempt the review still runs, so the user gets a verdict.
  3. Claude (Haiku) review, only once the tests pass. Blocking issues trigger a retry.

Retries on the Claude route ask for a minimal SEARCH/REPLACE patch and fall back to a full
rewrite if the patch doesn't apply cleanly. If the spec has no tests, an independent test-writer
(`aitk.testgen`) derives them from the spec alone before any code is generated.
"""
import importlib.metadata
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from aitk.agents import _strip_fences, ollama_generate
from aitk.checks import static_check
from aitk.config import (
    GENERATION_EFFORT,
    GENERATION_MODEL,
    MAX_GENERATION_TOKENS,
    REVIEW_MODEL,
    TEST_MODEL,
    claude_cost,
    ollama_enabled,
    resolve_max_attempts,
)
from aitk.cost import log_run
from aitk.llm import call_claude
from aitk.patching import apply_edits
from aitk.review import claude_review
from aitk.routing import BREAK_EVEN_TOKENS, estimate_output_tokens, resolve_route
from aitk.spec import parse_spec
from aitk.testgen import generate_tests, has_tests, write_generated_tests

# Cap on test output fed back to the generator, so one noisy failure can't blow up a retry prompt.
_MAX_FEEDBACK_CHARS = 8000

_COUNT_KEYS = (
    "claude_input_tokens",
    "claude_output_tokens",
    "claude_cache_read_tokens",
    "claude_cache_write_tokens",
    "ollama_response_tokens",
)

_CLAUDE_SYSTEM = (
    "You are an expert Python developer implementing a specification. Write production-quality, "
    "well-structured code that satisfies the spec exactly, with a one-line docstring on every "
    "function and class. Follow the output format requested in each task message.\n\n"
    "## SPEC\n{spec}"
)

_INITIAL_TASK = (
    "Implement the spec exactly as described. Produce a single Python file with all required "
    "exports. Return ONLY raw Python code — no markdown fences, no explanation."
)


def _run_tests(test_dir: str, module_dir: str | None = None) -> tuple[bool, str]:
    """Run pytest, return (all_passed, combined_output). `module_dir` is put on PYTHONPATH."""
    env = os.environ.copy()
    if module_dir:
        env["PYTHONPATH"] = os.pathsep.join(p for p in (module_dir, env.get("PYTHONPATH")) if p)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_dir, "-v", "--tb=short"],
        capture_output=True,
        text=True,
        env=env,
    )
    output = result.stdout + result.stderr
    return result.returncode == 0, output


def _installed_versions(frameworks: list[str]) -> str:
    """Look up actually-installed versions of the spec's declared frameworks.

    Claude's review only sees generated code and test output — it has no way to know
    what's actually installed, so it pattern-matches an import statement against its
    training data and can confidently state the wrong version (e.g. claiming SQLAlchemy
    2.0's DeclarativeBase "isn't available in the installed 1.x version" when 2.0.21 is
    what's actually on disk). Grounding the review in real version strings turns a guess
    into a fact it can check the generated code against.
    """
    found = []
    for fw in frameworks:
        try:
            found.append(f"{fw}=={importlib.metadata.version(fw)}")
        except importlib.metadata.PackageNotFoundError:
            continue
    return ", ".join(found) if found else "(no third-party frameworks declared in the spec)"


def _condense_for_review(test_output: str) -> str:
    """Strip per-test PASSED lines before sending pytest output to Claude review.

    These lines carry no diagnostic value (the reviewer needs failure detail,
    not a pass-spam listing) and their count scales with the test suite size —
    on a 13-test spec they made up ~80% of the review's test-output tokens.
    """
    return "\n".join(line for line in test_output.splitlines() if " PASSED" not in line)


def _tail(text: str, limit: int = _MAX_FEEDBACK_CHARS) -> str:
    """Keep the end of long output — pytest puts the failure summary last."""
    return text if len(text) <= limit else "...[truncated]...\n" + text[-limit:]


# --- retry prompts ---

def _format_review_issues(errors: list[dict]) -> str:
    """Render blocking review issues as a bulleted feedback block."""
    return "\n".join(
        f"- [{i.get('severity', 'error').upper()}] {i.get('location', '?')}: "
        f"{i.get('description', '')}  FIX: {i.get('fix', '')}"
        for i in errors
    )


def _patch_task(prior_code: str, feedback: str) -> str:
    """Ask for the smallest fix, as SEARCH/REPLACE blocks, instead of a rewrite."""
    return (
        "The previous implementation has these problems that must be fixed:\n\n"
        f"{feedback}\n\n"
        "Fix them with the SMALLEST possible change. Respond with ONLY one or more edit blocks "
        "in exactly this format, with no fences or commentary:\n"
        "<<<<<<< SEARCH\n<existing lines copied verbatim; must match the code exactly once>\n"
        "=======\n<replacement lines>\n>>>>>>> REPLACE\n\n"
        "Do not repeat unchanged code. If the fix is too extensive for edit blocks, respond with "
        "the single word REWRITE.\n\n"
        f"CURRENT CODE:\n```python\n{prior_code}\n```"
    )


def _rewrite_task(prior_code: str, feedback: str) -> str:
    """Ask for a full rewrite that fixes the reported problems."""
    return (
        "The previous implementation had these problems that must be fixed:\n\n"
        f"{feedback}\n\n"
        "Rewrite the implementation from scratch fixing all issues above. Return ONLY raw Python "
        "code — no markdown fences, no explanation.\n\n"
        "PREVIOUS CODE (for reference only — do not copy its bugs):\n"
        f"```python\n{prior_code}\n```"
    )


# --- stats helpers ---

def _zero_stats() -> dict:
    """Empty token counters for one generation step."""
    return {k: 0 for k in _COUNT_KEYS}


def _add_stats(a: dict, b: dict) -> dict:
    """Sum the token counters of two generation steps; other keys come from `b`."""
    merged = {**a, **b}
    for key in _COUNT_KEYS:
        merged[key] = a.get(key, 0) + b.get(key, 0)
    return merged


def _review_cost(usage: dict) -> float:
    """USD cost of one review call from its usage dict."""
    return claude_cost(
        REVIEW_MODEL, usage["input_tokens"], usage["output_tokens"],
        usage.get("cache_read_tokens", 0), usage.get("cache_write_tokens", 0),
    )


# --- generation ---

def _make_claude_generate(spec_body: str, verbose: bool):
    """Build a generate_fn(task) -> (text, stats) for the Claude route; the spec rides in `system`."""
    system = _CLAUDE_SYSTEM.format(spec=spec_body)

    async def generate_fn(task: str) -> tuple[str, dict]:
        text, usage = call_claude(
            GENERATION_MODEL, task, system=system,
            max_tokens=MAX_GENERATION_TOKENS, effort=GENERATION_EFFORT,
        )
        if usage["stop_reason"] == "max_tokens":
            raise RuntimeError(
                f"Claude generation hit the {MAX_GENERATION_TOKENS}-token output cap — "
                "the output would be truncated. Split the spec, or raise "
                "MAX_GENERATION_TOKENS in aitk/config.py."
            )
        if verbose:
            print(
                f"      {usage['input_tokens']}in/{usage['output_tokens']}out "
                f"(cache r{usage['cache_read_tokens']}/w{usage['cache_write_tokens']}) "
                f"({GENERATION_MODEL})", file=sys.stderr,
            )
        return text, {
            "claude_input_tokens": usage["input_tokens"],
            "claude_output_tokens": usage["output_tokens"],
            "claude_cache_read_tokens": usage["cache_read_tokens"],
            "claude_cache_write_tokens": usage["cache_write_tokens"],
            "ollama_response_tokens": 0,
        }

    return generate_fn


def _make_ollama_generate(spec_body: str, frameworks: list[str], model: str, verbose: bool):
    """Build a generate_fn(task) -> (text, stats) for the Ollama route; the spec joins the prompt."""

    async def generate_fn(task: str) -> tuple[str, dict]:
        code, stats = await ollama_generate(
            user_prompt=f"{task}\n\nSPEC:\n{spec_body}", frameworks=frameworks, model=model
        )
        if verbose:
            print(f"      {stats['response_tokens']} tokens  {stats['tokens_per_second']} tok/s  {stats['elapsed_s']}s", file=sys.stderr)
        return code, {**_zero_stats(), "ollama_response_tokens": stats["response_tokens"], "ollama_stats": stats}

    return generate_fn


async def _regenerate(generate_fn, prior_code: str, feedback: str, use_patch: bool, verbose: bool):
    """Produce the next attempt's code: a minimal patch if possible, else a full rewrite."""
    stats = _zero_stats()
    if use_patch:
        text, step = await generate_fn(_patch_task(prior_code, feedback))
        stats = _add_stats(stats, step)
        patched = apply_edits(prior_code, text)
        if patched is not None:
            return patched, stats, "patch"
        if verbose:
            print("      patch did not apply cleanly — falling back to a full rewrite", file=sys.stderr)
    text, step = await generate_fn(_rewrite_task(prior_code, feedback))
    return _strip_fences(text), _add_stats(stats, step), "rewrite"


def _skipped_review(reason: str, issues: list[dict] | None = None) -> dict:
    """Stand-in review for an attempt that never reached the paid review call."""
    return {
        "passed": False,
        "issues": issues or [],
        "scores": {},
        "summary": f"Review skipped: {reason}",
        "skipped": True,
    }


async def _generate_with_review(
    generate_fn,
    full_spec: str,
    frameworks: list[str],
    output_path: str,
    test_dir: str,
    verbose: bool,
    max_attempts: int,
    use_patch: bool,
) -> list[dict]:
    """Shared generate → check → test → review loop, retrying up to `max_attempts` times total."""
    versions = _installed_versions(frameworks)
    module_dir = str(Path(output_path).resolve().parent)
    iterations: list[dict] = []
    code = ""
    feedback = ""

    for attempt in range(1, max_attempts + 1):
        is_last = attempt == max_attempts

        if verbose:
            print(f"[{attempt}/{max_attempts}] Generating...", file=sys.stderr)
        if attempt == 1:
            text, gen_stats = await generate_fn(_INITIAL_TASK)
            code, how = _strip_fences(text), "full"
        else:
            code, gen_stats, how = await _regenerate(generate_fn, code, feedback, use_patch, verbose)
            if verbose:
                print(f"      applied as: {how}", file=sys.stderr)
        Path(output_path).write_text(code)

        pass_count = fail_count = 0
        tests_ok = False
        test_out = ""
        review = None
        usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}

        static_errors = static_check(code, output_path)
        if static_errors:
            if verbose:
                print(f"[{attempt}] Static check failed ({len(static_errors)}) — skipping tests and review", file=sys.stderr)
            feedback = "Static analysis found errors that stop the code from running:\n" + "\n".join(
                f"- {e}" for e in static_errors
            )
            review = _skipped_review(
                "static checks failed",
                [{"severity": "error", "location": "static check", "description": e, "fix": ""} for e in static_errors],
            )
        else:
            if verbose:
                print(f"[{attempt}] Running tests...", file=sys.stderr)
            tests_ok, test_out = _run_tests(test_dir, module_dir)
            pass_count = test_out.count(" PASSED")
            fail_count = test_out.count(" FAILED")
            if verbose:
                print(f"      {pass_count} passed  {fail_count} failed", file=sys.stderr)

            if not tests_ok and not is_last:
                # Visibly broken: retry on the failures themselves, no review call spent.
                feedback = "The test suite fails:\n" + _tail(_condense_for_review(test_out))
                review = _skipped_review("tests failing, retrying on test output")
            else:
                if verbose:
                    print(f"[{attempt}] Claude review ({REVIEW_MODEL})...", file=sys.stderr)
                review = claude_review(full_spec, code, _tail(_condense_for_review(test_out)), versions)
                usage = review.pop("_usage")
                if verbose:
                    print(
                        f"      passed={review.get('passed')}  issues={len(review.get('issues', []))}  "
                        f"tokens={usage['input_tokens']}in/{usage['output_tokens']}out",
                        file=sys.stderr,
                    )
                blocking = [i for i in review.get("issues", []) if i.get("severity") == "error"]
                feedback = _format_review_issues(blocking)
                if not tests_ok:
                    feedback = "The test suite fails:\n" + _tail(_condense_for_review(test_out)) + (
                        "\n\nReviewer findings:\n" + feedback if feedback else ""
                    )

        iterations.append({
            "iteration": attempt,
            "how": how,
            "gen_stats": gen_stats,
            "static_errors": static_errors,
            "tests_ok": tests_ok,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "review": review,
            "claude_tokens": usage,
        })

        blocking_review = any(i.get("severity") == "error" for i in review.get("issues", []))
        done = not static_errors and tests_ok and not blocking_review
        if done or is_last:
            break
        if verbose:
            print(f"\n[retry] attempt {attempt} not clean — retrying...", file=sys.stderr)

    return iterations


def _summarize(route: str, iterations: list[dict], testgen_usage: dict | None = None) -> dict:
    """Fold per-iteration stats into the flat result dict callers and CI expect."""
    final = iterations[-1]
    tg = testgen_usage or {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}

    def total(key: str) -> int:
        return sum(it["gen_stats"].get(key, 0) for it in iterations)

    gen_in, gen_out = total("claude_input_tokens"), total("claude_output_tokens")
    gen_cr, gen_cw = total("claude_cache_read_tokens"), total("claude_cache_write_tokens")
    review_cost = sum(_review_cost(it["claude_tokens"]) for it in iterations)
    review_in = sum(it["claude_tokens"]["input_tokens"] for it in iterations)
    review_out = sum(it["claude_tokens"]["output_tokens"] for it in iterations)

    cost = (
        claude_cost(GENERATION_MODEL, gen_in, gen_out, gen_cr, gen_cw)
        + review_cost
        + claude_cost(TEST_MODEL, tg["input_tokens"], tg["output_tokens"], tg["cache_read_tokens"], tg["cache_write_tokens"])
    )
    return {
        "route": route,
        "iterations": len(iterations),
        "final_pass_count": final["pass_count"],
        "final_fail_count": final["fail_count"],
        "final_review": final["review"],
        "claude_input_tokens": gen_in + review_in + tg["input_tokens"],
        "claude_output_tokens": gen_out + review_out + tg["output_tokens"],
        "claude_cache_read_tokens": gen_cr + tg["cache_read_tokens"],
        "claude_cache_write_tokens": gen_cw + tg["cache_write_tokens"],
        "ollama_response_tokens": total("ollama_response_tokens"),
        "estimated_cost_usd": round(cost, 5),
        "all_iterations": iterations,
    }


def _ensure_tests(spec_text: str, output_path: str, test_dir: str, mode: str, verbose: bool):
    """Write spec-derived tests when asked for (or when none exist). Returns (path|None, usage|None)."""
    if mode == "never" or (mode == "auto" and has_tests(test_dir)):
        return None, None
    module = Path(output_path).stem
    if verbose:
        print(f"[tests] Writing tests from the spec only ({TEST_MODEL}, independent of the coder)...", file=sys.stderr)
    code, problems, usage = generate_tests(spec_text, module)
    if problems:
        raise RuntimeError("generated tests failed validation: " + "; ".join(problems))
    path = write_generated_tests(test_dir, module, code)
    if verbose:
        print(f"      wrote {path} — generated tests are weaker evidence than hand-written ones; review them", file=sys.stderr)
    return str(path), usage


async def run_generate(
    spec_path: str,
    output_path: str,
    test_dir: str = "tests",
    route: str = "auto",
    model: str | None = None,
    verbose: bool = True,
    max_attempts: int | None = None,
    gen_tests: str = "auto",
) -> dict:
    """Top-level generate entry point — parses spec, writes tests if needed, routes, runs, logs."""
    from aitk.config import OLLAMA_MODEL
    model = model or OLLAMA_MODEL
    attempts = resolve_max_attempts(max_attempts)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    meta, spec_body = parse_spec(spec_path)
    frameworks: list[str] = meta.get("frameworks") or []
    estimated_lines: int | None = meta.get("estimated_lines")
    full_spec = Path(spec_path).read_text()

    resolved_route = resolve_route(route, spec_body, estimated_lines)
    if route == "auto" and verbose:
        if not ollama_enabled():
            print("[route] auto → claude  (local models disabled — set AITK_OLLAMA_ENABLED=1 to route locally)", file=sys.stderr)
        else:
            tokens = estimate_output_tokens(spec_body, estimated_lines)
            print(f"[route] auto → {resolved_route}  (estimated {tokens} output tokens, break-even {BREAK_EVEN_TOKENS})", file=sys.stderr)

    t_start = time.monotonic()

    tests_path, testgen_usage = _ensure_tests(full_spec, output_path, test_dir, gen_tests, verbose)

    if resolved_route == "ollama":
        generate_fn = _make_ollama_generate(spec_body, frameworks, model, verbose)
    else:
        generate_fn = _make_claude_generate(spec_body, verbose)

    iterations = await _generate_with_review(
        generate_fn, full_spec, frameworks, output_path, test_dir, verbose,
        max_attempts=attempts, use_patch=(resolved_route == "claude"),
    )
    result = _summarize(resolved_route, iterations, testgen_usage)
    result["max_attempts"] = attempts
    result["tests_generated"] = tests_path
    result["total_elapsed_s"] = round(time.monotonic() - t_start, 2)
    result["spec"] = spec_path

    log_run({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "spec": spec_path,
        "output": output_path,
        "route": resolved_route,
        "iterations": result["iterations"],
        "tests_generated": tests_path,
        "ollama_response_tokens": result.get("ollama_response_tokens", 0),
        "claude_input_tokens": result.get("claude_input_tokens", 0),
        "claude_output_tokens": result.get("claude_output_tokens", 0),
        "claude_cache_read_tokens": result.get("claude_cache_read_tokens", 0),
        "claude_cache_write_tokens": result.get("claude_cache_write_tokens", 0),
        "estimated_cost_usd": result.get("estimated_cost_usd", 0),
        "pass_count": result.get("final_pass_count", 0),
        "fail_count": result.get("final_fail_count", 0),
        "elapsed_s": result["total_elapsed_s"],
    })

    return result
