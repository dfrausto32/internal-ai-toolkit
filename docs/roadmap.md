# Roadmap

This document tracks what's been done, what's in progress, and what comes next. Updated as each phase completes.

---

## Status Overview

| Phase | Status | Description |
|-------|--------|-------------|
| 0 — Infrastructure | ✅ Complete | Ollama installed, GPU passthrough verified, models pulled |
| 1 — Subagent `.md` files | 🔄 In Progress | Claude Code agent definitions + Ollama helper script |
| 2 — Benchmarks | ⏳ Pending | Three test apps, scoring rubric, baseline results |
| 3 — SDK Migration | ⏳ Pending | Python orchestrator, parallel workers, CI integration |

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

## Phase 1 — Subagent `.md` Files 🔄

**Goal:** Four Claude Code subagent definitions that delegate to Ollama. Claude orchestrates via natural language in the terminal, Ollama does the generation work.

**Why this before the SDK:** Use this phase to tune the system prompts for each agent role and understand what Claude actually needs to see in its review step. That knowledge directly improves Phase 3.

### Tasks

- [ ] Write `scripts/ollama_stream.py` — the helper script all agents call
- [ ] Write `agents/ollama-coder.md` — code generation agent
- [ ] Write `agents/ollama-tester.md` — test writing agent
- [ ] Write `agents/ollama-pipeline.md` — CI/CD config agent
- [ ] Write `agents/ollama-notifier.md` — Slack/Discord notification agent
- [ ] Install agents to `~/.claude/agents/` and verify Claude can invoke them
- [ ] Test end-to-end: ask Claude to build something, confirm it delegates to Ollama
- [ ] Document prompt tuning notes in each `.md` file's comments

### Definition of Done
Claude can be given a task in plain language, delegates all generation to Ollama agents, and returns a structured review without writing code itself.

---

## Phase 2 — Benchmarks ⏳

**Goal:** Three small, well-defined test applications that let us objectively compare output quality between Phase 1 (subagents) and Phase 3 (SDK). Each app has a known spec and a pass/fail test suite.

### Benchmark Apps

**`app_01_rest_api`** — FastAPI CRUD service
- Spec: 4 endpoints (list, get, create, delete) for a `Task` resource, SQLite backend
- Success criteria: all endpoints return correct HTTP status codes, pytest suite passes
- Measures: code correctness, test coverage, docs quality

**`app_02_data_pipeline`** — CSV ingestion + transformation
- Spec: reads a CSV, validates schema, transforms 3 columns, writes output CSV + summary log
- Success criteria: handles malformed rows gracefully, output matches expected schema
- Measures: error handling quality, edge case coverage in tests

**`app_03_cli_tool`** — argparse CLI with subcommands
- Spec: 3 subcommands (`init`, `run`, `status`), reads config from a YAML file
- Success criteria: `--help` output is correct, all subcommands functional, tests cover each command
- Measures: documentation quality, argument validation

### Metrics Captured Per Run

| Metric | How Measured |
|--------|-------------|
| Claude token cost | Input + output tokens logged per run |
| Ollama generation time | Wall clock per agent call |
| Test pass rate | `pytest` exit code + pass/fail count |
| Claude review iterations | How many times Claude had to flag and re-request |
| Total wall clock time | Start to green tests |

### Tasks

- [ ] Write specs for all three apps as `benchmarks/app_XX/SPEC.md`
- [ ] Write test suites for all three apps (these are the ground truth — written by hand, not generated)
- [ ] Run Phase 1 against each benchmark, record results
- [ ] Run Phase 3 against each benchmark, record results
- [ ] Write comparison summary in `benchmarks/README.md`

---

## Phase 3 — Claude Agent SDK Migration ⏳

**Goal:** Rewrite the orchestration layer as a Python script using `claude_agent_sdk`. Ollama workers run in parallel via `asyncio.gather()`. Claude gets one structured review call per run. Integrate with GitHub Actions for automated runs.

**Why migrate from Phase 1:** The SDK gives explicit parallelism (all Ollama workers run simultaneously), full control over what Claude sees in its context window, and a clean CI integration path.

### Architecture

```python
# Rough shape of orchestrator/main.py
async def run(spec: str):
    # All three Ollama workers run in parallel — zero Claude tokens
    code, tests, pipeline = await asyncio.gather(
        ollama_call("qwen2.5-coder:14b", CODER_PROMPT, spec),
        ollama_call("qwen2.5-coder:14b", TESTER_PROMPT, spec),
        ollama_call("llama3.1:8b",       PIPELINE_PROMPT, spec),
    )

    # Claude gets one call with a structured review prompt
    review = await claude_review(code, tests, pipeline)

    # If review flags issues, loop once with targeted fixes
    # If review passes, generate notification and return
```

### Tasks

- [ ] Set up `orchestrator/requirements.txt` (`claude-agent-sdk`, `httpx`, `anthropic`)
- [ ] Write `orchestrator/agents.py` — Ollama worker functions
- [ ] Write `orchestrator/main.py` — orchestration loop
- [ ] Add token cost logging to every Claude call
- [ ] Write GitHub Actions workflow in `.github/workflows/benchmark.yml`
- [ ] Run all three benchmarks via SDK, record results
- [ ] Compare Phase 1 vs Phase 3 results in `benchmarks/README.md`

### Definition of Done
`python orchestrator/main.py --spec benchmarks/app_01_rest_api/SPEC.md` runs end to end, tests pass, Claude token cost is logged, and the result matches or beats Phase 1 quality.

---

## Future Considerations

These aren't planned yet but worth tracking:

- **Model upgrades:** As better models land on Ollama (e.g. future Qwen releases), re-run benchmarks to see if quality improves without touching the orchestration layer.
- **Notification delivery:** Actually POST to a Slack/Discord webhook instead of just generating the message text.
- **Multi-file projects:** Current benchmarks are single-file or small. A larger benchmark (e.g. a full microservice with multiple modules) would stress-test context management.
- **Cost dashboard:** A simple script that aggregates Claude token logs across all runs and shows cost over time.
