"""Core generate loop: Ollama or Claude → test → Claude review → optional retry."""
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from aitk.agents import ollama_generate
from aitk.cost import log_run
from aitk.review import claude_review
from aitk.routing import cost_phase3, cost_raw_claude, decide_route
from aitk.spec import parse_spec

import anthropic


def _run_tests(test_dir: str) -> tuple[bool, str]:
    """Run pytest, return (all_passed, combined_output)."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_dir, "-v", "--tb=short"],
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    return result.returncode == 0, output


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
    """Build a retry prompt that feeds Claude's error list back to Ollama."""
    issue_lines = "\n".join(
        f"- [{i['severity'].upper()}] {i['location']}: {i['description']}  FIX: {i['fix']}"
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


def _claude_direct_prompt(spec_body: str) -> str:
    """Build a prompt for raw Claude generation (no Ollama)."""
    return (
        "Implement the following Python spec exactly as described. "
        "Return ONLY raw Python code — no markdown fences, no explanation.\n\n"
        f"{spec_body}"
    )


async def _generate_ollama(
    spec_body: str,
    frameworks: list[str],
    model: str,
    output_path: str,
    test_dir: str,
    verbose: bool,
) -> dict:
    """Full Ollama → test → Claude review → retry loop."""
    iterations = []

    # Iteration 1
    if verbose:
        print(f"[1/3] Generating with Ollama ({model})...", file=sys.stderr)
    code, ollama_stats = await ollama_generate(
        user_prompt=_coder_prompt(spec_body),
        frameworks=frameworks,
        model=model,
    )
    Path(output_path).write_text(code)
    if verbose:
        print(f"      {ollama_stats['response_tokens']} tokens  {ollama_stats['tokens_per_second']} tok/s  {ollama_stats['elapsed_s']}s", file=sys.stderr)

    if verbose:
        print("[2/3] Running tests...", file=sys.stderr)
    passed, test_out = _run_tests(test_dir)
    pass_count = test_out.count(" PASSED")
    fail_count = test_out.count(" FAILED")
    if verbose:
        print(f"      {pass_count} passed  {fail_count} failed", file=sys.stderr)

    if verbose:
        print("[3/3] Claude review...", file=sys.stderr)
    spec_for_review = Path(output_path).parent.parent / "SPEC.md"
    full_spec = spec_for_review.read_text() if spec_for_review.exists() else spec_body
    review = claude_review(full_spec, code, _condense_for_review(test_out))
    usage = review.pop("_usage")
    if verbose:
        print(f"      passed={review['passed']}  issues={len(review['issues'])}  tokens={usage['input_tokens']}in/{usage['output_tokens']}out", file=sys.stderr)

    iterations.append({
        "iteration": 1,
        "ollama_stats": ollama_stats,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "review": review,
        "claude_tokens": usage,
    })

    # Retry if Claude flagged blocking errors
    blocking = [i for i in review.get("issues", []) if i["severity"] == "error"]
    if blocking:
        if verbose:
            print(f"\n[retry] {len(blocking)} blocking issue(s). Regenerating...", file=sys.stderr)
        code2, stats2 = await ollama_generate(
            user_prompt=_retry_prompt(spec_body, code, blocking),
            frameworks=frameworks,
            model=model,
        )
        Path(output_path).write_text(code2)
        if verbose:
            print(f"        {stats2['response_tokens']} tokens  {stats2['elapsed_s']}s", file=sys.stderr)

        passed2, test_out2 = _run_tests(test_dir)
        pass_count2 = test_out2.count(" PASSED")
        fail_count2 = test_out2.count(" FAILED")
        if verbose:
            print(f"        {pass_count2} passed  {fail_count2} failed", file=sys.stderr)

        review2 = claude_review(full_spec, code2, _condense_for_review(test_out2))
        usage2 = review2.pop("_usage")
        if verbose:
            print(f"        passed={review2['passed']}  tokens={usage2['input_tokens']}in/{usage2['output_tokens']}out", file=sys.stderr)

        iterations.append({
            "iteration": 2,
            "ollama_stats": stats2,
            "pass_count": pass_count2,
            "fail_count": fail_count2,
            "review": review2,
            "claude_tokens": usage2,
        })

    final = iterations[-1]
    total_claude_in  = sum(it["claude_tokens"]["input_tokens"]  for it in iterations)
    total_claude_out = sum(it["claude_tokens"]["output_tokens"] for it in iterations)
    total_ollama_out = sum(it["ollama_stats"]["response_tokens"] for it in iterations)

    return {
        "route": "ollama",
        "iterations": len(iterations),
        "final_pass_count": final["pass_count"],
        "final_fail_count": final["fail_count"],
        "final_review": final["review"],
        "claude_input_tokens": total_claude_in,
        "claude_output_tokens": total_claude_out,
        "ollama_response_tokens": total_ollama_out,
        "estimated_cost_usd": round(cost_phase3(total_claude_in, total_claude_out), 5),
        "all_iterations": iterations,
    }


async def _generate_claude(
    spec_body: str,
    output_path: str,
    test_dir: str,
    verbose: bool,
) -> dict:
    """Raw Claude generation — no Ollama, no review loop."""
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set")

    if verbose:
        print("[1/2] Generating with Claude...", file=sys.stderr)
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": _claude_direct_prompt(spec_body)}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        newline = raw.find("\n")
        raw = raw[newline + 1:] if newline != -1 else raw[3:]
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")].rstrip()

    Path(output_path).write_text(raw)
    input_tokens  = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    if verbose:
        print(f"      {output_tokens} tokens out  {input_tokens}in/{output_tokens}out", file=sys.stderr)

    if verbose:
        print("[2/2] Running tests...", file=sys.stderr)
    passed, test_out = _run_tests(test_dir)
    pass_count = test_out.count(" PASSED")
    fail_count = test_out.count(" FAILED")
    if verbose:
        print(f"      {pass_count} passed  {fail_count} failed", file=sys.stderr)

    return {
        "route": "claude",
        "iterations": 1,
        "final_pass_count": pass_count,
        "final_fail_count": fail_count,
        "claude_input_tokens": input_tokens,
        "claude_output_tokens": output_tokens,
        "ollama_response_tokens": 0,
        "estimated_cost_usd": round(cost_raw_claude(input_tokens, output_tokens), 5),
    }


async def run_generate(
    spec_path: str,
    output_path: str,
    test_dir: str,
    route: str = "auto",
    model: str = "qwen2.5-coder:14b",
    verbose: bool = True,
) -> dict:
    """Top-level generate entry point — parses spec, routes, runs, logs."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    meta, spec_body = parse_spec(spec_path)
    frameworks: list[str] = meta.get("frameworks") or []
    estimated_lines: int | None = meta.get("estimated_lines")

    resolved_route = route
    if route == "auto":
        resolved_route = decide_route(spec_body, estimated_lines)
        if verbose:
            tokens = (estimated_lines or 0) * 12 if estimated_lines else len(spec_body.split()) * 2
            print(f"[route] auto → {resolved_route}  (estimated {tokens} output tokens, break-even 1225)", file=sys.stderr)

    t_start = time.monotonic()

    if resolved_route == "ollama":
        result = await _generate_ollama(spec_body, frameworks, model, output_path, test_dir, verbose)
    else:
        result = await _generate_claude(spec_body, output_path, test_dir, verbose)

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
