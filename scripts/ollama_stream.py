#!/usr/bin/env python3
"""
Streaming wrapper for the Ollama /api/generate endpoint.
Agents pipe their prompts through stdin or pass --prompt:

    cat <<'EOF' | python ~/.claude/scripts/ollama_stream.py --model qwen2.5-coder:14b --agent ollama-coder
    Write a FastAPI CRUD service...
    EOF

Generated text goes to stdout. Summary stats go to stderr.
Token stats are appended to ~/.claude/scripts/agent_token_stats.json after each run.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

STATS_FILE = Path.home() / ".claude" / "scripts" / "agent_token_stats.json"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Stream a prompt to a local Ollama model and log token stats"
    )
    p.add_argument("--model", required=True, help="Ollama model name (e.g. qwen2.5-coder:14b)")
    p.add_argument("--prompt", default=None, help="Prompt text; reads stdin if omitted")
    p.add_argument("--system", default=None, help="System prompt for the model")
    p.add_argument("--agent", default=None, help="Agent label for stats log (defaults to model name)")
    p.add_argument("--url", default="http://localhost:11434", help="Ollama base URL")
    p.add_argument(
        "--no-stream",
        dest="no_stream",
        action="store_true",
        help="Wait for full response instead of streaming token-by-token",
    )
    return p.parse_args()


def load_stats() -> list:
    try:
        return json.loads(STATS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_stat(entry: dict) -> None:
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    stats = load_stats()
    stats.append(entry)
    STATS_FILE.write_text(json.dumps(stats, indent=2))


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from model output."""
    text = text.strip()
    if text.startswith("```"):
        newline = text.find("\n")
        text = text[newline + 1:] if newline != -1 else text[3:]
    if text.endswith("```"):
        text = text[: text.rfind("```")].rstrip()
    return text


def call_streaming(url: str, payload: dict) -> tuple[str, dict]:
    body = json.dumps(payload).encode()
    req = Request(
        f"{url}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    chunks: list[str] = []
    final_meta: dict = {}
    with urlopen(req) as resp:
        for raw_line in resp:
            line = raw_line.decode().strip()
            if not line:
                continue
            chunk = json.loads(line)
            if chunk.get("done"):
                final_meta = chunk
            else:
                chunks.append(chunk.get("response", ""))
    text = _strip_fences("".join(chunks))
    sys.stdout.write(text)
    sys.stdout.write("\n")
    sys.stdout.flush()
    return text, final_meta


def call_blocking(url: str, payload: dict) -> tuple[str, dict]:
    body = json.dumps({**payload, "stream": False}).encode()
    req = Request(
        f"{url}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req) as resp:
        data = json.loads(resp.read())
    text = _strip_fences(data.get("response", ""))
    sys.stdout.write(text)
    sys.stdout.write("\n")
    sys.stdout.flush()
    return text, data


def main() -> None:
    args = parse_args()

    prompt = args.prompt if args.prompt is not None else sys.stdin.read()
    if not prompt.strip():
        sys.stderr.write("error: empty prompt — pass --prompt or pipe text via stdin\n")
        sys.exit(1)

    payload: dict = {
        "model": args.model,
        "prompt": prompt,
        "stream": not args.no_stream,
    }
    if args.system:
        payload["system"] = args.system

    t_start = time.monotonic()
    try:
        if args.no_stream:
            _, meta = call_blocking(args.url, payload)
        else:
            _, meta = call_streaming(args.url, payload)
    except URLError as exc:
        sys.stderr.write(f"error: could not reach Ollama at {args.url} — {exc.reason}\n")
        sys.stderr.write("Is Ollama running?  sudo systemctl start ollama\n")
        sys.exit(1)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"error: unexpected response from Ollama — {exc}\n")
        sys.exit(1)

    elapsed = time.monotonic() - t_start
    eval_count = meta.get("eval_count", 0)
    eval_duration_s = meta.get("eval_duration", 0) / 1e9
    tokens_per_s = round(eval_count / max(eval_duration_s, 0.001), 1)

    stat = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": args.agent or args.model,
        "model": args.model,
        "prompt_tokens": meta.get("prompt_eval_count", 0),
        "response_tokens": eval_count,
        "tokens_per_second": tokens_per_s,
        "total_duration_s": round(elapsed, 2),
    }
    save_stat(stat)

    sys.stderr.write(
        f"[ollama] agent={stat['agent']} model={args.model} "
        f"tokens={eval_count} speed={tokens_per_s} tok/s elapsed={elapsed:.1f}s\n"
    )


if __name__ == "__main__":
    main()
