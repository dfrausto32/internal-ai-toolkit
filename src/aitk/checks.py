"""Free, deterministic checks run before any paid model call.

Catching a syntax error or an undefined name here costs nothing and skips a review call that
could only have said the same thing less reliably.
"""
import subprocess
import sys

# Ruff rules that flag code which cannot run: syntax errors (E9), invalid comparisons/raises
# (F63, F7) and undefined names (F82). Style rules are deliberately excluded.
_RUFF_RULES = "E9,F63,F7,F82"


def static_check(code: str, path: str) -> list[str]:
    """Return blocking problems found without running the code (empty list = clean)."""
    try:
        compile(code, path, "exec")
    except SyntaxError as exc:
        return [f"SyntaxError at line {exc.lineno}: {exc.msg}"]

    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", _RUFF_RULES,
         "--output-format", "concise", "--no-cache", path],
        capture_output=True,
        text=True,
    )
    if "No module named ruff" in result.stderr:
        return []  # ruff unavailable: syntax check above is all we can do
    if result.returncode == 0:
        return []
    return [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.startswith(("Found ", "[*]", "All checks"))
    ]
