"""aitk CLI — entry point for all aitk subcommands."""
import argparse
import asyncio
import json
import sys

from aitk.cost import show_cost
from aitk.generate import run_generate
from aitk.routing import BREAK_EVEN_TOKENS, decide_route, estimate_output_tokens
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
        )
    )
    if not args.quiet:
        print(f"\n--- Result ---", file=sys.stderr)
        print(f"route={result['route']}  iterations={result['iterations']}  "
              f"passed={result['final_pass_count']}  failed={result['final_fail_count']}  "
              f"cost=${result['estimated_cost_usd']:.4f}  elapsed={result['total_elapsed_s']}s",
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
    route = decide_route(spec_body, estimated_lines)

    print(f"spec:            {args.spec}")
    print(f"frameworks:      {meta.get('frameworks') or '[]'}")
    print(f"estimated_lines: {estimated_lines or '(not set, using heuristic)'}")
    print(f"output tokens:   ~{tokens}")
    print(f"break-even:      {BREAK_EVEN_TOKENS}")
    print(f"route:           {route}")


def main() -> None:
    """Parse top-level args and dispatch to subcommands."""
    parser = argparse.ArgumentParser(
        prog="aitk",
        description="AI toolkit: Ollama + Claude orchestration for code generation",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # aitk generate
    gen = sub.add_parser("generate", help="Generate a module from a spec file")
    gen.add_argument("--spec",  required=True, help="Path to SPEC.md")
    gen.add_argument("--out",   required=True, help="Output file path for generated code")
    gen.add_argument("--tests", required=True, help="Path to pytest test directory")
    gen.add_argument(
        "--route",
        default="auto",
        choices=["auto", "ollama", "claude"],
        help="Generation route (default: auto — chosen from spec size)",
    )
    gen.add_argument("--model", default="qwen2.5-coder:14b", help="Ollama model name")
    gen.add_argument("--quiet", action="store_true", help="Suppress progress output")
    gen.add_argument("--json",  action="store_true", help="Print full result as JSON")

    # aitk cost
    cost_cmd = sub.add_parser("cost", help="Show cost summary for recent runs")
    cost_cmd.add_argument("--last", type=int, default=10, help="Number of runs to show")

    # aitk route
    route_cmd = sub.add_parser("route", help="Preview routing decision for a spec")
    route_cmd.add_argument("--spec", required=True, help="Path to SPEC.md")

    args = parser.parse_args()

    if args.command == "generate":
        _cmd_generate(args)
    elif args.command == "cost":
        _cmd_cost(args)
    elif args.command == "route":
        _cmd_route(args)


if __name__ == "__main__":
    main()
