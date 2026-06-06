# Installing aitk in another repo

`aitk` is a dev dependency — install it once and use it from any project directory.

---

## Install from source (local)

```bash
pip install -e /path/to/internal-ai-toolkit
```

After this, `aitk` is on your PATH and available in any Python environment.

## Install from GitHub (remote)

```bash
pip install git+https://github.com/dfrausto32/internal-ai-toolkit.git
```

Or pin to a specific commit:

```bash
pip install git+https://github.com/dfrausto32/internal-ai-toolkit.git@<commit-sha>
```

## Add to a project's dev dependencies

In `requirements-dev.txt`:
```
git+https://github.com/dfrausto32/internal-ai-toolkit.git
```

In `pyproject.toml`:
```toml
[project.optional-dependencies]
dev = [
    "aitk @ git+https://github.com/dfrausto32/internal-ai-toolkit.git",
]
```

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Python 3.10+ | Required for `X \| Y` union type syntax |
| `ANTHROPIC_API_KEY` env var | Required for Claude review and `--route claude` |
| Ollama running at `http://localhost:11434` | Required for `--route ollama` only |
| `qwen2.5-coder:14b` pulled | Required for `--route ollama` only — `ollama pull qwen2.5-coder:14b` |

---

## Quick start in a new repo

```bash
# 1. Install
pip install -e /path/to/internal-ai-toolkit

# 2. Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# 3. Write a spec (see docs/spec-format.md)
# 4. Preview the routing decision
aitk route --spec docs/SPEC.md

# 5. Generate
aitk generate --spec docs/SPEC.md --out src/module.py --tests tests/

# 6. Check cost history
aitk cost --last 5
```

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes (for Claude) | Anthropic API key — get one at console.anthropic.com |
| `OLLAMA_URL` | No | Override Ollama base URL (default: `http://localhost:11434`) |
