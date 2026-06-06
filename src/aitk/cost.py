"""Read and display cost logs for aitk runs."""
import json
from pathlib import Path

RUN_LOG = Path.home() / ".local" / "share" / "aitk" / "run_log.json"

_INPUT_RATE  = 3.00  / 1_000_000
_OUTPUT_RATE = 15.00 / 1_000_000


def log_run(entry: dict) -> None:
    """Append a completed run record to the persistent run log."""
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    records = _load()
    records.append(entry)
    RUN_LOG.write_text(json.dumps(records, indent=2))


def _load() -> list:
    """Load existing run log, return empty list if missing or corrupt."""
    try:
        return json.loads(RUN_LOG.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def show_cost(last_n: int = 5) -> None:
    """Print a cost summary for the most recent N runs."""
    records = _load()
    if not records:
        print("No runs logged yet. Run 'aitk generate' first.")
        return

    recent = records[-last_n:]
    total_cost = 0.0

    header = f"{'Date':<22} {'Spec':<30} {'Route':<8} {'OllamaTok':>10} {'ClaudeIn':>10} {'ClaudeOut':>10} {'Cost':>8}"
    print(header)
    print("-" * len(header))

    for r in recent:
        ts   = r.get("timestamp", "")[:19]
        spec = Path(r.get("spec", "")).name[:28]
        route = r.get("route", "?")
        ol_tok = r.get("ollama_response_tokens", 0)
        cl_in  = r.get("claude_input_tokens", 0)
        cl_out = r.get("claude_output_tokens", 0)
        cost   = cl_in * _INPUT_RATE + cl_out * _OUTPUT_RATE
        total_cost += cost
        print(f"{ts:<22} {spec:<30} {route:<8} {ol_tok:>10} {cl_in:>10} {cl_out:>10} ${cost:>7.4f}")

    print("-" * len(header))
    print(f"{'Total (last ' + str(len(recent)) + ' runs)':<72} ${total_cost:>7.4f}")
