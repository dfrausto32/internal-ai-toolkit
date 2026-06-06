# Contributing

Guidelines for working in this repo — branching, commit style, how to add agents, and how to run benchmarks.

---

## Branching

```
main          ← stable, working state only
├── phase/1-subagents       ← Phase 1 work
├── phase/2-benchmarks      ← benchmark apps and specs
├── phase/3-sdk             ← SDK migration
└── fix/<short-description> ← bug fixes against any phase
```

Merge to `main` only when the phase's definition of done is met (see `docs/roadmap.md`).

---

## Commit Messages

Keep them short and scoped. Format: `<area>: <what changed>`

```
agents: add ollama-coder.md initial draft
scripts: add ollama_stream.py with token stats
benchmarks: add app_01 spec and hand-written test suite
orchestrator: add parallel worker functions in agents.py
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

### Phase 3 run (SDK)
```bash
cd orchestrator
python main.py --spec ../benchmarks/app_01_rest_api/SPEC.md --output ../benchmarks/app_01_rest_api/generated/
```

Record results in `benchmarks/README.md` under the Phase 3 column.

### What to record

For each run, fill in the benchmark results table:

| Field | Where to find it |
|-------|-----------------|
| Claude tokens (input) | Logged to stdout by orchestrator, or Claude Code session summary |
| Claude tokens (output) | Same |
| Ollama time per agent | Logged by `ollama_stream.py` to `~/.claude/scripts/agent_token_stats.json` |
| Tests passed | `pytest benchmarks/app_XX/tests/ -v` exit output |
| Review iterations | Count how many times Claude flagged issues and re-requested |
| Wall clock time | `time python main.py ...` or note start/end time manually |

---

## Repo Hygiene

- **Never commit generated code** from benchmark runs to `main`. Keep generated output in `benchmarks/app_XX/generated/` which is gitignored.
- **Never commit API keys.** The `ANTHROPIC_API_KEY` comes from the environment, not the code.
- **Keep `docs/roadmap.md` current.** Check off tasks as they complete.
- **Models don't go in the repo.** They live in `~/.ollama/models/` on your machine.
