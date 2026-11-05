# Architecture

A one-page tour of how `aitk` works, why it is shaped this way, and what is not built yet.
For install and usage see the [README](../README.md).

---

## What it does

`aitk` turns a Markdown **spec** into a single, tested, reviewed Python file:

1. **Draft** (optional) — `aitk spec init` has Claude write the spec from a plain-English description.
2. **Tests** — if the test directory is empty, a *separate* agent writes tests from the spec alone.
3. **Route** — pick who writes the code: Claude (default) or a local Ollama model.
4. **Generate** — produce the code.
5. **Free checks** — syntax and undefined-name checks; a failure retries with no model review.
6. **Test** — run the pytest suite; a failure retries on the failure output with no model review.
7. **Review** — only once tests pass, a cheaper model (Haiku) checks the code against the spec.
8. **Retry** — on a failed check, failing tests, or blocking review errors; up to `--max-attempts` total (default 2). Retries ask for a minimal patch and fall back to a full rewrite.
9. **Log** — record tokens (including cache reads/writes) and estimated cost.

```
 SPEC.md ─► [no tests? spec-only test agent] ─► route ──┬─► Claude Sonnet ──┐
                                                         └─► Ollama (opt-in) ┘
                                                                  │
                          write file ─► static checks ─► pytest ──┤ any fail & attempts left:
                                                                  │   retry on that output (no review)
                                                                  ▼ all pass
                                                            Haiku review
                                                                  │ blocking errors & attempts left:
                                                                  │   retry (patch, else rewrite)
                                                                  ▼
                                                         result + cost log
```

---

## Components

| Module | Responsibility |
|--------|----------------|
| [`cli.py`](../src/aitk/cli.py) | Entry point: `generate`, `route`, `cost`, `spec init` |
| [`spec.py`](../src/aitk/spec.py) | Parses spec frontmatter (language, frameworks, estimated_lines, test_command) |
| [`specgen.py`](../src/aitk/specgen.py) | Claude-drafted specs for `aitk spec init` |
| [`routing.py`](../src/aitk/routing.py) | Chooses Claude vs Ollama; holds the break-even constant |
| [`generate.py`](../src/aitk/generate.py) | The check → test → review → retry loop; cost summary |
| [`testgen.py`](../src/aitk/testgen.py) | Independent test writer: sees only the spec, never the implementation |
| [`checks.py`](../src/aitk/checks.py) | Free static checks that run before any paid review |
| [`patching.py`](../src/aitk/patching.py) | Applies SEARCH/REPLACE edit blocks for minimal-patch retries |
| [`llm.py`](../src/aitk/llm.py) | One Claude client: cache placement, effort/thinking, usage, refusals |
| [`agents.py`](../src/aitk/agents.py) | Async Ollama worker; builds the system prompt from declared frameworks |
| [`review.py`](../src/aitk/review.py) | Haiku review step, structured JSON verdict |
| [`cost.py`](../src/aitk/cost.py) | Persistent run log and `aitk cost` display |
| [`config.py`](../src/aitk/config.py) | Single home for model IDs, prices, and the Ollama on/off switch |
| [`plan.py`](../src/aitk/plan.py) | Phase 5 node-spec schema and plan validation (not yet used by the CLI) |

---

## Key design decisions

**Both routes share one pipeline.** The route only decides who writes the code; test, review, and
retry are identical. That keeps results comparable and means a local-model failure is caught by the
same gate as a Claude one.

**Claude-only by default.** Local generation is free but needs a GPU. `auto` routing resolves to
Claude unless `AITK_OLLAMA_ENABLED=1`, so the tool never depends on an Ollama server that may not
exist. With local models on, a size heuristic applies: roughly 100 lines is the point above which
local generation plus Claude review beat raw Claude on cost (code is read at input prices instead of
written at output prices). The constant predates the Haiku reviewer and is due to be re-derived —
see the roadmap.

**A cheap reviewer, grounded in facts.** Review uses Haiku. Because a reviewer only sees code and
test output, it can confidently state wrong things about the environment, so the review prompt
includes the *actually installed* framework versions. Passing-test noise is stripped from the output
sent to the reviewer, since its token count scales with suite size and carries no signal.

**Hand-written tests are the ground truth.** Generated code is never graded by generated tests.
The benchmarks follow the same rule; see [`benchmarks/README.md`](../benchmarks/README.md).

**Cheapest signal first.** Static checks, then tests, then the paid review. Code that visibly
fails never reaches the reviewer; the failure output goes straight back to the generator.

**The test author is not the code author.** Generated tests come from a separate call that sees only
the spec, and the file is frozen for the run, so the coder can neither see nor edit it. They are still
weaker evidence than hand-written tests (both can misread the spec), so they are labelled and meant to
be reviewed.

**Bounded, configurable retry.** Two attempts by default (`--max-attempts` / `AITK_MAX_ATTEMPTS`). A
loop that cannot converge in two attempts usually has a spec problem; the benchmarks should show
whether a third is worth its cost. Retries ask for a minimal patch rather than a rewrite.

**One file of configuration.** Models, prices, and the hardware switch live in `config.py`, so a
model swap or price change is a one-file edit. Cost is recorded at run time rather than recomputed,
so history is not silently repriced when rates change.

---

## Cost model

Cost per run = test-writing + generation + review tokens, priced per model in `config.py` (cache reads and
writes at their own multiples), summed across every attempt. `aitk cost` shows recent runs from
`~/.local/share/aitk/run_log.json`.

---

## Status and what is not built

| Area | State |
|------|-------|
| Spec → code pipeline, routing, free checks, spec-derived tests, patch retries, review, cost log | Built and unit-tested with stubbed model calls (CI on every PR); **not yet exercised against the live API** |
| Reusable GitHub Actions workflow | Built |
| Benchmarks | Recorded for the original Ollama pipeline; **the Claude-only default is not yet benchmarked** |
| Phase 5 node-spec schema (`plan.py`) | Built, not yet wired into the CLI |
| Phase 5 `plan`/`build`, executor | Planned |
| Phase 5 broker and scheduler | Designed, **deliberately deferred** until benchmark data shows they are needed |

The full Phase 5 design is in [design-parallel-orchestration.md](design-parallel-orchestration.md)
([visual version](design.html)); sequencing and the scope gate are in [build-plan.md](build-plan.md);
overall status is in [roadmap.md](roadmap.md).

---

## Known limitations

- Single-file output; multi-file generation arrives with Phase 5.
- Generated tests can share the spec's ambiguities with the code; they catch implementation drift, not a wrong spec.
- Prompt caching helps only when a prefix repeats and is long enough to cache; for short specs expect little. The run log records cache tokens so the benchmarks can show the real effect.
- Effort levels and the review's thinking-off setting are starting points, not measured optima.
- Python only for generation and test execution.
- Quality claims about the current default pipeline are unmeasured until the benchmark refresh lands.
- Cost figures are estimates from token counts and the prices in `config.py`.
