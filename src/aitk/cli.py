"""aitk CLI — entry point for all aitk subcommands."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from aitk.config import OLLAMA_MODEL, ollama_enabled
from aitk.cost import show_cost
from aitk.generate import run_generate
from aitk.routing import BREAK_EVEN_TOKENS, estimate_output_tokens, resolve_route
from aitk.spec import parse_spec


def _cmd_generate(args: argparse.Namespace) -> None:
    """Run the generate command."""
    result = asyncio.run(
        run_generate(
            spec_path=args.spec,
            output_path=args.out,
            test_dir=args.tests,
            route=args.route,
            model=args.model,
            verbose=not args.quiet,
            max_attempts=args.max_attempts,
            gen_tests=args.gen_tests,
        )
    )
    if not args.quiet:
        print(f"\n--- Result ---", file=sys.stderr)
        print(f"route={result['route']}  iterations={result['iterations']}  "
              f"passed={result['final_pass_count']}  failed={result['final_fail_count']}  "
              f"cost=${result['estimated_cost_usd']:.4f}  elapsed={result['total_elapsed_s']}s",
              file=sys.stderr)
        if result.get("tests_generated"):
            print(f"note: tests were generated from the spec ({result['tests_generated']}). "
                  "Review them — a pass is weaker evidence than with hand-written tests.",
                  file=sys.stderr)

    if args.json:
        print(json.dumps(result, indent=2))

    tests_passed = result["final_fail_count"] == 0 and result["final_pass_count"] > 0
    sys.exit(0 if tests_passed else 1)


def _cmd_cost(args: argparse.Namespace) -> None:
    """Run the cost command."""
    show_cost(last_n=args.last)


def _cmd_route(args: argparse.Namespace) -> None:
    """Show which route would be chosen for a given spec without running anything."""
    meta, spec_body = parse_spec(args.spec)
    estimated_lines = meta.get("estimated_lines")
    tokens = estimate_output_tokens(spec_body, estimated_lines)
    route = resolve_route("auto", spec_body, estimated_lines)

    print(f"spec:            {args.spec}")
    print(f"frameworks:      {meta.get('frameworks') or '[]'}")
    print(f"estimated_lines: {estimated_lines or '(not set, using heuristic)'}")
    print(f"output tokens:   ~{tokens}")
    print(f"break-even:      {BREAK_EVEN_TOKENS}")
    print(f"local models:    {'enabled' if ollama_enabled() else 'disabled (set AITK_OLLAMA_ENABLED=1 to enable)'}")
    print(f"route:           {route}")


def _cmd_spec_init(args: argparse.Namespace) -> None:
    """Draft a SPEC.md from a plain-English description using Claude."""
    from aitk.specgen import draft_spec

    if args.describe:
        description = args.describe
    else:
        if sys.stdin.isatty():
            print("Describe what to build (finish with Ctrl-D):", file=sys.stderr)
        description = sys.stdin.read().strip()
    if not description:
        print("error: empty description — pass --describe or pipe text on stdin", file=sys.stderr)
        sys.exit(2)

    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"error: {out} already exists (use --force to overwrite)", file=sys.stderr)
        sys.exit(2)

    print(f"Drafting spec with Claude...", file=sys.stderr)
    text, problems, usage = draft_spec(description)
    out.write_text(text + ("\n" if not text.endswith("\n") else ""))

    print(f"\nWrote {out}  ({usage['input_tokens']}in/{usage['output_tokens']}out, "
          f"${usage['cost_usd']:.4f})", file=sys.stderr)
    if problems:
        print("warning: draft still has problems — review before generating:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)

    meta, body = parse_spec(str(out))
    route = resolve_route("auto", body, meta.get("estimated_lines"))
    print(f"estimated_lines={meta.get('estimated_lines')}  frameworks={meta.get('frameworks')}  "
          f"route(auto)={route}", file=sys.stderr)
    print(f"\nNext: review/edit {out}, then run:", file=sys.stderr)
    print(f"  aitk generate --spec {out} --out <module.py> --tests <tests/>", file=sys.stderr)


def main() -> None:
    """Parse top-level args and dispatch to subcommands."""
    parser = argparse.ArgumentParser(
        prog="aitk",
        description="AI toolkit: Claude (and optionally Ollama) orchestration for code generation",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # aitk generate
    gen = sub.add_parser("generate", help="Generate a module from a spec file")
    gen.add_argument("--spec",  required=True, help="Path to SPEC.md")
    gen.add_argument("--out",   required=True, help="Output file path for generated code")
    gen.add_argument("--tests", default="tests", help="Path to pytest test directory (default: tests)")
    gen.add_argument(
        "--gen-tests",
        default="auto",
        choices=["auto", "always", "never"],
        help="Write tests from the spec with an independent agent: auto = only if the test "
             "directory has none (default), always = add a generated suite alongside existing tests, never",
    )
    gen.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="Total generate attempts including retries (default: 2, or AITK_MAX_ATTEMPTS)",
    )
    gen.add_argument(
        "--route",
        default="auto",
        choices=["auto", "ollama", "claude"],
        help="Generation route (default: auto — claude unless AITK_OLLAMA_ENABLED=1)",
    )
    gen.add_argument("--model", default=OLLAMA_MODEL, help="Ollama model name (route=ollama only)")
    gen.add_argument("--quiet", action="store_true", help="Suppress progress output")
    gen.add_argument("--json",  action="store_true", help="Print full result as JSON")

    # aitk cost
    cost_cmd = sub.add_parser("cost", help="Show cost summary for recent runs")
    cost_cmd.add_argument("--last", type=int, default=10, help="Number of runs to show")

    # aitk route
    route_cmd = sub.add_parser("route", help="Preview routing decision for a spec")
    route_cmd.add_argument("--spec", required=True, help="Path to SPEC.md")

    # aitk spec
    spec_cmd = sub.add_parser("spec", help="Spec utilities")
    spec_sub = spec_cmd.add_subparsers(dest="spec_command", required=True)
    spec_init = spec_sub.add_parser(
        "init", help="Draft a SPEC.md from a plain-English description with Claude"
    )
    spec_init.add_argument("--describe", help="What to build, in plain English (reads stdin if omitted)")
    spec_init.add_argument("--out", default="SPEC.md", help="Where to write the spec (default: SPEC.md)")
    spec_init.add_argument("--force", action="store_true", help="Overwrite an existing spec file")

    args = parser.parse_args()

    if args.command == "generate":
        _cmd_generate(args)
    elif args.command == "cost":
        _cmd_cost(args)
    elif args.command == "route":
        _cmd_route(args)
    elif args.command == "spec":
        _cmd_spec_init(args)


if __name__ == "__main__":
    main()
