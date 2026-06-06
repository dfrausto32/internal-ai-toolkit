# Roadmap

This document tracks what's been done, what's in progress, and what comes next. Updated as each phase completes.

---

## Status Overview

| Phase | Status | Description |
|-------|--------|-------------|
| 0 — Infrastructure | ✅ Complete | Ollama installed, GPU passthrough verified, models pulled |
| 1 — Subagent `.md` files | ✅ Complete | Claude Code agent definitions + Ollama helper script |
| 2 — Benchmarks | ✅ Complete | Three test apps, scoring rubric, Phase 1 and Phase 3 results |
| 3 — Orchestrator | ✅ Complete | Python orchestrator, Claude review loop, routing analysis |
| 4 — Cross-Repo Integration | ✅ Complete | Installable CLI, spec convention, GitHub Actions reusable workflow |

---

## Phase 0 — Infrastructure ✅

**Goal:** Ollama running with GPU acceleration on WSL2, models verified.

- [x] WSL2 confirmed at version 2
- [x] 32 GB RAM allocated to WSL2 via `.wslconfig`
- [x] NVIDIA RTX 4080 GPU passthrough working (CUDA 13.1, driver 591.86)
- [x] Ollama installed via one-line installer
- [x] Models pulled: `qwen2.5-coder:14b`, `llama3.1:8b`, `llama3.2:3b`
- [x] API verified at `http://localhost:11434`
- [x] Setup documentation written → `docs/ollama-setup.md`

---

## Phase 1 — Subagent `.md` Files ✅

**Goal:** Four Claude Code subagent definitions that delegate to Ollama. Claude orchestrates via natural language in the terminal, Ollama does the generation work.

**Why this before the SDK:** Use this phase to tune the system prompts for each agent role and understand what Claude actually needs to see in its review step. That knowledge directly improves Phase 3.

- [x] Write `scripts/ollama_stream.py` — the helper script all agents call
- [x] Write `.claude/agents/ollama-coder.md` — code generation agent
- [x] Write `.claude/agents/ollama-tester.md` — test writing agent
- [x] Write `.claude/agents/ollama-pipeline.md` — CI/CD config agent
- [x] Write `.claude/agents/ollama-notifier.md` — Slack/Discord notification agent
- [x] Document prompt tuning notes in each `.md` file's comments

**What we learned:** The subagent `.md` files live at `~/.claude/agents/` and are already global — any repo opened with Claude Code can invoke them immediately. Prompt tuning has diminishing returns; framework-specific rules (SQLAlchemy, Pydantic) bleed into unrelated generation tasks without a `STDLIB FIRST` guard.

---

## Phase 2 — Benchmarks ✅

**Goal:** Three small, well-defined test applications that let us objectively compare output quality between Phase 1 (subagents) and Phase 3 (orchestrator). Each app has a known spec and a hand-written pass/fail test suite.

- [x] Write specs for all three apps as `benchmarks/app_XX/SPEC.md`
- [x] Write test suites (ground truth — hand-written, never generated)
- [x] Run Phase 1 against each benchmark, record results
- [x] Run Phase 3 against each benchmark, record results
- [x] Write comparison summary in `benchmarks/README.md`

**Results summary (Phase 3 vs Phase 1 best):**

| App | Phase 1 | Phase 3 | Change |
|-----|---------|---------|--------|
| app_01_rest_api | 5/9 | 6/9 | +1 |
| app_02_data_pipeline | 4/9 | 8/9 | +4 |
| app_03_cli_tool | 8/9 | 8/9 | = |
| **Combined** | **17/27** | **22/27** | **+5** |

Full results and notes → `benchmarks/README.md`

---

## Phase 3 — Orchestrator ✅

**Goal:** Python orchestrator that drives the full generate → test → Claude review → retry loop. Cost model established. Routing decision documented.

- [x] `orchestrator/requirements.txt` — `anthropic`, `httpx`
- [x] `orchestrator/agents.py` — async Ollama worker with `STDLIB FIRST` system prompt
- [x] `orchestrator/review.py` — Claude review step, structured JSON output
- [x] `orchestrator/main.py` — full orchestration loop with one auto-retry
- [x] Token cost logging on every Claude call
- [x] All three benchmarks run end-to-end, results recorded

**Key findings:**
- Break-even between Phase 3 (Ollama + Claude review) and raw Claude generation is **~100 lines of generated code (~1,225 output tokens)**. Below that threshold, raw Claude is cheaper per run. Above it, Phase 3 wins because code tokens are 5× cheaper to read as review input ($3/1M) than to write as Claude output ($15/1M).
- Volume alone does not flip the economics for small files — the per-run cost ratio stays fixed regardless of N daily runs. Volume helps Phase 3 when API rate limits or latency matter.
- Framework contamination (unconditional FastAPI/SQLAlchemy rules bleeding into stdlib-only tasks) is the single biggest prompt risk. Fixed by `STDLIB FIRST` + conditional `IF USING X:` rules.

---

## Phase 4 — Cross-Repo Integration ✅

**Goal:** Turn the orchestrator into a tool other repos can actually use. Right now it's a benchmark runner tied to this repo's directory structure. Phase 4 makes it a general-purpose CLI that any repo can call against its own specs, with a reusable GitHub Actions workflow and a minimal spec convention.

**Why this matters:** The subagent `.md` files are already global. The missing piece is the orchestrator — other repos need to be able to drive generation without copying this repo's structure or knowing its internals.

### Piece 1 — Installable CLI (`aitk`)

Extract the orchestrator into a proper CLI tool installed from this repo:

```bash
# In any other repo
pip install -e /path/to/internal-ai-toolkit   # or via pip + git URL
aitk generate --spec docs/SPEC.md --out src/api.py --tests tests/
aitk generate --spec docs/SPEC.md --out src/api.py --tests tests/ --route auto
```

The `--route auto` flag applies the routing decision automatically:
- Estimates output token count from the spec
- Routes to Ollama + Claude review if estimated output > 1,225 tokens (~100 lines)
- Routes to raw Claude generation if below threshold
- Can be overridden with `--route ollama` or `--route claude`

**Tasks:**
- [x] Add `pyproject.toml` with `[project.scripts]` entry point for `aitk`
- [x] Move `orchestrator/` logic into `src/aitk/` package structure
- [x] Implement `aitk generate` CLI command with `--spec`, `--out`, `--tests`, `--route` flags
- [x] Implement routing estimator: count spec tokens, estimate output size, decide route
- [x] Add `aitk cost` subcommand: show token cost breakdown for the last run
- [x] Write `docs/install.md` — how to add this as a dev dependency in another repo

### Piece 2 — Spec Convention

Right now each benchmark `SPEC.md` is free-form prose. For the orchestrator to drive generation reliably across repos, specs need a minimal structure the router can parse:

```markdown
## Meta
language: python
framework: fastapi        # or: stdlib, sqlalchemy, etc. — drives system prompt selection
estimated_lines: 200      # optional hint for routing; orchestrator estimates if omitted
test_command: pytest tests/

## Requirements
...free-form prose from here...
```

The `framework:` field replaces the current static system prompt with a dynamic one — only inject FastAPI/SQLAlchemy/Pydantic rules when the spec declares those frameworks.

**Tasks:**
- [x] Define the spec frontmatter schema (language, framework, estimated_lines, test_command)
- [x] Update `src/aitk/agents.py` to build system prompt dynamically from spec metadata
- [x] Update all three benchmark `SPEC.md` files to use the new frontmatter
- [x] Write `docs/spec-format.md` — how to write a spec for use with `aitk`

### Piece 3 — GitHub Actions Reusable Workflow

Publish a reusable workflow that other repos reference directly — no copying, no forking:

```yaml
# .github/workflows/generate.yml in another repo
name: Generate module
on: [workflow_dispatch]
jobs:
  generate:
    uses: dfrausto32/internal-ai-toolkit/.github/workflows/aitk-generate.yml@main
    with:
      spec: docs/SPEC.md
      output: src/api.py
      tests: tests/
    secrets:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

The workflow handles: install `aitk`, run generation, upload the generated file as an artifact, post a PR with the result if tests pass.

**Tasks:**
- [x] Write `.github/workflows/aitk-generate.yml` as a reusable `workflow_call` workflow
- [x] Workflow inputs: `spec`, `output`, `tests`, `route` (default: `auto`)
- [x] Workflow outputs: test pass/fail count, Claude cost, generated file artifact
- [x] Add PR creation step: if tests pass, open a PR in the calling repo with the generated file
- [x] Write `docs/github-actions.md` — how to reference the workflow from another repo

### Definition of Done

A second repo (not this one) can run `aitk generate --spec SPEC.md --out module.py --tests tests/` and get a generated, tested, Claude-reviewed file — without touching anything in `internal-ai-toolkit` directly. The GitHub Actions workflow does the same thing on push/dispatch.

---

## Future Considerations

- **Multi-file projects:** Current benchmarks are single-file. A larger benchmark (e.g. a full microservice with multiple modules) would stress-test context management and the spec convention.
- **Model upgrades:** As better models land on Ollama, re-run benchmarks to see if quality improves without touching the orchestration layer.
- **Cost dashboard:** Aggregate Claude token logs across all runs and repos into a single view. The `~/.claude/scripts/agent_token_stats.json` file is already tracking Ollama stats — add a Claude cost log in the same format.
- **Notification delivery:** Actually POST to a Slack/Discord webhook when a generation run completes, instead of just generating the message text.
- **Dynamic model routing:** Beyond Ollama vs Claude, route between Ollama models based on task type — `qwen2.5-coder:14b` for code, `llama3.2:3b` for notifications, `llama3.1:8b` for CI config.
