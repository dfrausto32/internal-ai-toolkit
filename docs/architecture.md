# Architecture

A one-page tour of how `aitk` works, why it is shaped this way, and what is not built yet.
For install and usage see the [README](../README.md).

---

## What it does

`aitk` turns a Markdown **spec** into a single, tested, reviewed Python file:

1. **Draft** (optional) — `aitk spec init` has Claude write the spec from a plain-English description.
2. **Route** — pick who writes the code: Claude (default) or a local Ollama model.
3. **Generate** — produce the code.
4. **Test** — run the caller's own pytest suite against it.
5. **Review** — a cheaper model (Haiku) checks the code against the spec and the test output.
6. **Retry once** — if the review reports blocking errors, regenerate with the errors fed back.
7. **Log** — record tokens and estimated cost for the run.

```
 SPEC.md ──► route ──┬─► Claude Sonnet ──┐
                     │                   ├─► write file ─► pytest ─► Haiku review
                     └─► Ollama (opt-in) ┘                               │
                              ▲                                          │ blocking errors?
                              └──────── retry once with error list ◄─────┘
                                                                          │ no / 2nd attempt
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
| [`generate.py`](../src/aitk/generate.py) | The generate → test → review → retry loop; cost summary |
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

**Bounded retry.** One retry only. A loop that cannot converge in two attempts usually has a spec
problem, and the cost of a third attempt is rarely justified.

**One file of configuration.** Models, prices, and the hardware switch live in `config.py`, so a
model swap or price change is a one-file edit. Cost is recorded at run time rather than recomputed,
so history is not silently repriced when rates change.

---

## Cost model

Cost per run = generation tokens + review tokens, priced per model in `config.py`, summed across
both attempts when a retry happens. `aitk cost` shows recent runs from
`~/.local/share/aitk/run_log.json`.

---

## Status and what is not built

| Area | State |
|------|-------|
| Spec → code pipeline, routing, review, retry, cost log | Built and unit-tested (CI on every PR) |
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
- Python only for generation and test execution.
- Quality claims about the current default pipeline are unmeasured until the benchmark refresh lands.
- Cost figures are estimates from token counts and the prices in `config.py`.
