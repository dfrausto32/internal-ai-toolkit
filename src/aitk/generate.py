"""Core generate loop: (Ollama | Claude) generation → test → Claude review → optional retry.

Both routes run the same pipeline — generate, run tests, Haiku review, retry once
on blocking errors. They differ only in who writes the code: the free local
Ollama worker, or a Claude generation call.
"""
import importlib.metadata
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from aitk.agents import _strip_fences, ollama_generate
from aitk.config import (
    GENERATION_MODEL,
    MAX_GENERATION_TOKENS,
    REVIEW_MODEL,
    claude_cost,
    ollama_enabled,
)
from aitk.cost import log_run
from aitk.review import claude_review
from aitk.routing import BREAK_EVEN_TOKENS, estimate_output_tokens, resolve_route
from aitk.spec import parse_spec


def _run_tests(test_dir: str) -> tuple[bool, str]:
    """Run pytest, return (all_passed, combined_output)."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_dir, "-v", "--tb=short"],
        capture_output=True,
        text=True,
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


def _coder_prompt(spec_body: str) -> str:
    """Build the initial generation prompt from spec body text."""
    return (
        "Implement the following spec exactly as described. "
        "Produce a single Python file with all required exports.\n\n"
        f"{spec_body}"
    )


def _retry_prompt(spec_body: str, prior_code: str, errors: list[dict]) -> str:
    """Build a retry prompt that feeds the reviewer's error list back to the generator."""
    issue_lines = "\n".join(
        f"- [{i.get('severity', 'error').upper()}] {i.get('location', '?')}: "
        f"{i.get('description', '')}  FIX: {i.get('fix', '')}"
        for i in errors
    )
    return (
        "The previous implementation had these blocking issues that must be fixed:\n\n"
        f"{issue_lines}\n\n"
        "Rewrite the implementation from scratch fixing all issues above.\n\n"
        f"SPEC:\n{spec_body}\n\n"
        "PREVIOUS CODE (for reference only — do not copy its bugs):\n"
        f"```python\n{prior_code}\n```"
    )


def _claude_generate(prompt: str) -> tuple[str, dict]:
    """One Claude generation call, return (code_text, usage_dict)."""
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set")

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=GENERATION_MODEL,
        max_tokens=MAX_GENERATION_TOKENS,
        messages=[{"role": "user", "content": (
            "Return ONLY raw Python code — no markdown fences, no explanation.\n\n" + prompt
        )}],
    )
    if message.stop_reason == "max_tokens":
        raise RuntimeError(
            f"Claude generation hit the {MAX_GENERATION_TOKENS}-token output cap — "
            "the output would be truncated. Split the spec, or raise "
            "MAX_GENERATION_TOKENS in aitk/config.py."
        )

    code = _strip_fences(message.content[0].text)
    return code, {
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
    }


async def _generate_with_review(
    generate_fn,
    spec_body: str,
    full_spec: str,
    frameworks: list[str],
    output_path: str,
    test_dir: str,
    verbose: bool,
) -> tuple[list[dict], list[dict]]:
    """Shared generate → test → review loop with one retry on blocking errors.

    generate_fn(prompt) -> (code, gen_stats) where gen_stats carries
    claude_input_tokens / claude_output_tokens / ollama_response_tokens
    (zeroes for whichever backend didn't run) plus backend-specific extras.
    """
    versions = _installed_versions(frameworks)
    iterations: list[dict] = []
    prompt = _coder_prompt(spec_body)

    for attempt in (1, 2):
        if verbose:
            print(f"[{attempt}] Generating...", file=sys.stderr)
        code, gen_stats = await generate_fn(prompt)
        Path(output_path).write_text(code)

        if verbose:
            print(f"[{attempt}] Running tests...", file=sys.stderr)
        _, test_out = _run_tests(test_dir)
        pass_count = test_out.count(" PASSED")
        fail_count = test_out.count(" FAILED")
        if verbose:
            print(f"      {pass_count} passed  {fail_count} failed", file=sys.stderr)

        if verbose:
            print(f"[{attempt}] Claude review ({REVIEW_MODEL})...", file=sys.stderr)
        review = claude_review(full_spec, code, _condense_for_review(test_out), versions)
        usage = review.pop("_usage")
        if verbose:
            print(
                f"      passed={review.get('passed')}  issues={len(review.get('issues', []))}  "
                f"tokens={usage['input_tokens']}in/{usage['output_tokens']}out",
                file=sys.stderr,
            )

        iterations.append({
            "iteration": attempt,
            "gen_stats": gen_stats,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "review": review,
            "claude_tokens": usage,
        })

        blocking = [i for i in review.get("issues", []) if i.get("severity") == "error"]
        if not blocking or attempt == 2:
            break
        if verbose:
            print(f"\n[retry] {len(blocking)} blocking issue(s). Regenerating...", file=sys.stderr)
        prompt = _retry_prompt(spec_body, code, blocking)

    return iterations


def _summarize(route: str, iterations: list[dict]) -> dict:
    """Fold per-iteration stats into the flat result dict callers and CI expect."""
    final = iterations[-1]
    gen_in = sum(it["gen_stats"]["claude_input_tokens"] for it in iterations)
    gen_out = sum(it["gen_stats"]["claude_output_tokens"] for it in iterations)
    review_in = sum(it["claude_tokens"]["input_tokens"] for it in iterations)
    review_out = sum(it["claude_tokens"]["output_tokens"] for it in iterations)
    ollama_out = sum(it["gen_stats"]["ollama_response_tokens"] for it in iterations)

    cost = claude_cost(GENERATION_MODEL, gen_in, gen_out) + claude_cost(
        REVIEW_MODEL, review_in, review_out
    )
    return {
        "route": route,
        "iterations": len(iterations),
        "final_pass_count": final["pass_count"],
        "final_fail_count": final["fail_count"],
        "final_review": final["review"],
        "claude_input_tokens": gen_in + review_in,
        "claude_output_tokens": gen_out + review_out,
        "ollama_response_tokens": ollama_out,
        "estimated_cost_usd": round(cost, 5),
        "all_iterations": iterations,
    }


async def run_generate(
    spec_path: str,
    output_path: str,
    test_dir: str,
    route: str = "auto",
    model: str | None = None,
    verbose: bool = True,
) -> dict:
    """Top-level generate entry point — parses spec, routes, runs, logs."""
    from aitk.config import OLLAMA_MODEL
    model = model or OLLAMA_MODEL

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

    if resolved_route == "ollama":
        async def generate_fn(prompt: str) -> tuple[str, dict]:
            code, stats = await ollama_generate(user_prompt=prompt, frameworks=frameworks, model=model)
            if verbose:
                print(f"      {stats['response_tokens']} tokens  {stats['tokens_per_second']} tok/s  {stats['elapsed_s']}s", file=sys.stderr)
            return code, {
                "claude_input_tokens": 0,
                "claude_output_tokens": 0,
                "ollama_response_tokens": stats["response_tokens"],
                "ollama_stats": stats,
            }
    else:
        async def generate_fn(prompt: str) -> tuple[str, dict]:
            code, usage = _claude_generate(prompt)
            if verbose:
                print(f"      {usage['input_tokens']}in/{usage['output_tokens']}out ({GENERATION_MODEL})", file=sys.stderr)
            return code, {
                "claude_input_tokens": usage["input_tokens"],
                "claude_output_tokens": usage["output_tokens"],
                "ollama_response_tokens": 0,
            }

    iterations = await _generate_with_review(
        generate_fn, spec_body, full_spec, frameworks, output_path, test_dir, verbose
    )
    result = _summarize(resolved_route, iterations)
    result["total_elapsed_s"] = round(time.monotonic() - t_start, 2)
    result["spec"] = spec_path

    log_run({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "spec": spec_path,
        "output": output_path,
        "route": resolved_route,
        "ollama_response_tokens": result.get("ollama_response_tokens", 0),
        "claude_input_tokens": result.get("claude_input_tokens", 0),
        "claude_output_tokens": result.get("claude_output_tokens", 0),
        "estimated_cost_usd": result.get("estimated_cost_usd", 0),
        "pass_count": result.get("final_pass_count", 0),
        "fail_count": result.get("final_fail_count", 0),
        "elapsed_s": result["total_elapsed_s"],
    })

    return result
