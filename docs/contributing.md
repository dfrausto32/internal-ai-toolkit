# Contributing

Guidelines for working in this repo — branching, commit style, how to add agents, and how to run benchmarks.

---

## Branching

```
master        ← stable, working state only
├── phase/N-<short-name>    ← phase work (see docs/roadmap.md)
└── fix/<short-description> ← bug fixes against any phase
```

Merge to `master` only when the phase's definition of done is met (see `docs/roadmap.md`).

---

## Commit Messages

Keep them short and scoped. Format: `<area>: <what changed>`

```
agents: add ollama-coder.md initial draft
scripts: add ollama_stream.py with token stats
benchmarks: add app_01 spec and hand-written test suite
aitk: add retry-on-blocking-error to generate.py
docs: update roadmap Phase 1 task status
```

---

## Adding or Editing an Agent

Agent definitions live in `.claude/agents/`. Claude Code discovers them automatically when run from the repo root — no copying or installation step needed.

Each agent is a Markdown file with YAML frontmatter:

```markdown
---
name: ollama-coder
description: Delegates code generation tasks to local Ollama model
tools: [Bash, Read]
---

System prompt goes here...
```

Claude Code picks up edits immediately. To promote an agent to global availability (accessible from any directory), copy it to `~/.claude/agents/`:

```bash
cp .claude/agents/ollama-coder.md ~/.claude/agents/ollama-coder.md
```

**When tuning prompts:** add a comment block at the bottom of the `.md` file noting what you changed and why. This becomes the paper trail for Phase 3 prompt design.

```markdown
<!-- Prompt history
2026-06-05: Initial version. Too verbose in output, Claude had to summarize.
2026-06-10: Tightened output format. Claude review iterations dropped from 2 to 1.
-->
```

---

## Working on the `aitk` package

The installable CLI lives in `src/aitk/` (`pyproject.toml` at the repo root, `hatchling` build backend). Install it in editable mode so changes take effect immediately:

```bash
pip install -e .
aitk --help
```

Package layout:

| Module | Responsibility |
|--------|---------------|
| `cli.py` | `argparse` entry point — `generate`, `cost`, `route` subcommands |
| `spec.py` | Parses `SPEC.md` YAML frontmatter |
| `routing.py` | Ollama-vs-Claude break-even decision (`BREAK_EVEN_TOKENS`) |
| `agents.py` | Async Ollama worker, dynamic system-prompt construction |
| `review.py` | Claude review step (structured JSON) |
| `generate.py` | Full generate → test → review → retry orchestration loop |
| `cost.py` | Run cost log (`~/.local/share/aitk/run_log.json`) |

Run its test suite from the repo root:

```bash
pytest src/aitk/tests/ -v
```

When changing routing math or prompt rules, re-run the affected benchmark app (see below) to confirm quality didn't regress — `aitk`'s own tests cover its internals, not generation quality.

---

## Running a Benchmark

Each benchmark app has a spec (`SPEC.md`) and a hand-written test suite (`tests/`). The test suite is ground truth — never generate it with Ollama or Claude.

### Phase 1 run (subagents)
```bash
# Start a Claude Code session in the benchmark directory
cd benchmarks/app_01_rest_api
claude

# In the Claude Code session, give the task:
# "Read SPEC.md and build the application. Use your Ollama agents for all generation."
```

Record results in `benchmarks/README.md` under the Phase 1 column.

### Phase 3 run (aitk)
```bash
aitk generate \
  --spec  benchmarks/app_01_rest_api/SPEC.md \
  --out   benchmarks/app_01_rest_api/generated/api.py \
  --tests benchmarks/app_01_rest_api/tests/
```

Record results in `benchmarks/README.md` under the Phase 3 column.

### What to record

For each run, fill in the benchmark results table:

| Field | Where to find it |
|-------|-----------------|
| Claude tokens (input/output) | `aitk generate --json` result, or `aitk cost --last 1` after the run |
| Ollama time per agent | Logged by `ollama_stream.py` to `~/.claude/scripts/agent_token_stats.json` |
| Tests passed | `pytest benchmarks/app_XX/tests/ -v` exit output, or the `final_pass_count`/`final_fail_count` fields in the `aitk generate --json` result |
| Review iterations | Count how many times Claude flagged issues and re-requested |
| Wall clock time | `time aitk generate ...` or note start/end time manually |

---

## Repo Hygiene

- **Never commit generated code** from benchmark runs to `main`. Keep generated output in `benchmarks/app_XX/generated/` which is gitignored.
- **Never commit API keys.** The `ANTHROPIC_API_KEY` comes from the environment, not the code.
- **Keep `docs/roadmap.md` current.** Check off tasks as they complete.
- **Models don't go in the repo.** They live in `~/.ollama/models/` on your machine.
