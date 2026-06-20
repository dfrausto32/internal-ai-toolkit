# Phase 5 — Parallel Orchestration Design

**Status:** Design (not yet implemented)
**Visual version:** [design.html](design.html) — open in a browser for diagrams.

This document captures the architecture for running multiple planning orchestrators
in parallel, each driving worker→tester→reviewer pipelines, under one shared resource
budget. It is the design artifact that must be agreed before any scheduler code is written.

---

## 1. Goal

Today `aitk generate` is **serial and single-file**: one spec → one worker generation →
tests → one Claude review → at most one retry, all `await`ed in a straight line
(`src/aitk/generate.py`). Phase 5 promotes that single loop into a **hierarchy** where:

- multiple **orchestrators** plan work for different features or projects,
- each orchestrator dispatches **workers** that generate code,
- workers **loop with testers** until tests pass,
- a finished module is handed to an independent **reviewer** as a final gate.

The existing loop is not thrown away — it *becomes* the worker→tester→reviewer leaf of
this hierarchy.

---

## 2. The bottleneck changed — design around the right one

The original cost model (Phase 3) assumed local Ollama generation, where the scarce
resource is the single RTX 4080 GPU. Phase 5's dominant path is **Claude API calls and
agents**, not Ollama. That flips the constraint:

| Path | Bound by | Parallelizes? |
|------|----------|---------------|
| Ollama generation | GPU (one 4080, ~9 GB for `qwen2.5-coder:14b`) | No — serial on one card |
| Claude API (generate / review) | API rate limit + cost budget | Yes — async fan-out |

**Consequence:** the limiter is now the **Claude rate limit (requests/min + tokens/min)
and the cost budget**, both of which are *global*. The GPU constraint is demoted to a
niche concern for the occasional Ollama node. Every design decision below follows from
"the scarce resource is global API budget, not compute."

---

## 3. The core rule: many planners, ONE scheduler

The tempting reading of "multiple orchestrators" is N independent engines, each fanning
out its own workers. **That is the trap.** With a global API/cost budget, N planners ×
M workers all hitting the API with no central throttle produces:

- rate-limit storms (429s, backoff thrash),
- no global cost ceiling (runaway spend),
- file/test-dir collisions between unrelated projects.

So the architecture is **many planners, exactly one scheduler / resource broker**:

```
Orchestrator A (plans feature A) ─┐
Orchestrator B (plans feature B) ─┼─► submit DAG nodes ─► [ ONE Scheduler ]
Orchestrator C (plans project C) ─┘                            │
                                          shared API lease + cost budget
                                                               │
                                        interleaves all nodes from all planners
```

"Multiple orchestrators" is a **planning** concept (each owns a feature/project and
produces a dependency graph of work). Execution is centralized: one scheduler drains all
nodes from all planners under a single shared budget. The scheduler you build for one
project is the same one that serves many — it just accepts work from several planners.

---

## 4. The four roles

| Role | Responsibility | Today's equivalent |
|------|----------------|--------------------|
| **Orchestrator / Planner** | Decompose a feature/project spec into a DAG of module nodes; declare dependencies between them. One per feature/project. | *(new in Phase 5)* |
| **Worker (coder)** | Generate one module from its spec + the real interfaces of its dependencies. | `ollama_generate` / raw-Claude path in `generate.py` |
| **Tester** | Write and run tests for a module; iterate with the worker until they pass. | `_run_tests` + `ollama-tester` |
| **Reviewer** | Independent final gate — reads the *original spec* and the finished module, blocks on spec drift. Non-skippable. | `claude_review` (`review.py`) |

```
Orchestrator (planner)   one per feature/project — emits a DAG
      │ dispatches
   Worker (coder)         generates one module node
      ↕ loops with
   Tester                 writes & runs tests, iterates with worker
      │ hands finished module to
   Reviewer               independent final gate (sees original spec)
```

### 4a. Why the reviewer cannot be dropped

In Phase 3 the tests were **hand-written ground truth**. In Phase 5 the *tester generates*
the tests and the *worker generates* the code, and they loop against each other. Two
self-generated artifacts can converge on **green tests that encode the same misreading of
the spec** (worker and tester wrong in the same direction). The reviewer — which sees the
original spec, not the generated tests — is the independent check that makes self-generated
tests trustworthy. It stays a hard gate.

---

## 5. The scheduler

The scheduler is a **bounded-concurrency DAG executor**.

```
build DAG from each planner's nodes → compute in-degrees
ready-set = nodes with in-degree 0
worker pool (size = API concurrency bound):
    acquire API lease → run node → release lease
    on success: store node result (incl. its public interface)
                decrement in-degree of dependents
                newly-zero nodes join ready-set
    on hard failure: apply failure policy (§7)
repeat until DAG drained
```

The **batch case** ("multiple independent specs") is a degenerate DAG with **no edges** —
every node is ready immediately and they all pipeline at once up to the bound. The
**multi-file case** is the same scheduler with dependency edges. One mechanism, both cases.

### 5a. Concurrency control — two leases, not one

| Lease | Bound | Acquired by |
|-------|-------|-------------|
| **API lease** | API rate limit (RPM/TPM), token-aware | every Claude call: generation *and* review |
| **GPU lease** | 1 for the 14b model (only if an Ollama node exists) | Ollama generation only |

The API lease must be **token-aware**, not just request-counting: a burst of large-context
reviews can blow TPM at low request concurrency. **Retry-on-429 with backoff lives inside
the lease** so a rate-limit hit pauses one worker without crashing the DAG.

---

## 6. Execution substrate — recommendation

**Decision needed:** what actually executes a node — a direct async API call, or a spawned
Claude Code agent?

**Recommendation: Python scheduler spine + pluggable executors.** Default every node to a
direct async Anthropic API call; escalate to a spawned Claude Code agent only for
reasoning-heavy nodes (the planner, occasionally a gnarly worker).

**Why not make nested Claude Code agents the backbone:** each spawned agent starts cold,
re-derives context, and — critically — has **no global view of the shared rate-limit / cost
budget**, which is the exact resource Phase 5 is constrained by. The agent layer is
excellent for individual judgment-heavy steps but a poor *scheduler* because it cannot
enforce a global ceiling.

> **Python owns scheduling and the budget. Agents / API calls are the muscle.**

Trade-off accepted: a planner-as-API-call reasons in one shot rather than multi-step with
tools. Mitigation: selectively upgrade *only* planner nodes to spawned agents where the
extra reasoning pays for itself — the choice is per-node, not global.

---

## 7. Open decisions (resolve during implementation)

| Decision | Options | Default leaning |
|----------|---------|-----------------|
| **Failure policy** | (a) skip failed node's subtree, finish independent branches; (b) fail-fast, halt the DAG | Make it a **pluggable hook**; pick default at build time. (Parked per design discussion.) |
| **Planner upgrade** | API-call planner vs spawned-agent planner | Start API-call; upgrade per-node if reasoning is insufficient |
| **GPU concurrency** | serialize all Ollama; or per-model leases (14b + 3b co-resident) | Ignore for now — Ollama is not the dominant path |

---

## 8. Shared-state hazards (the real implementation work)

These are latent in today's serial code and **break the moment execution goes concurrent**:

| Hazard | Location | Fix |
|--------|----------|-----|
| Tests run in a shared cwd / output path — concurrent pytest runs collide | `generate.py:_run_tests` | Per-node sandbox dir + distinct output path |
| Cost log is read-modify-write on one JSON file — concurrent writers clobber records | `cost.py:log_run` | Single writer task draining a queue, or append-only JSONL + lock |
| A dependent worker hallucinates its dependency's interface | (new) cross-node | **Result store**: each finished node publishes its real public interface; dependents' prompts are built from `spec + dependencies' interfaces` |
| No global cost ceiling | (new) scheduler | Budget tracked in the scheduler; refuse/queue new nodes past the ceiling |

The **result store** is the most valuable coordination contract here — it is what prevents
integration drift across modules, and it matters more than raw speed.

---

## 9. Definition of done

- One scheduler drains nodes from ≥2 planners concurrently under a single API lease and a
  single enforced cost budget.
- A multi-file project generates modules in dependency order, with each dependent worker
  receiving its dependencies' real interfaces (not just specs).
- Concurrent runs never collide on test dirs, output paths, or the cost log.
- The reviewer gate runs on every finished module and can block on spec drift.

---

## 10. Relationship to existing phases

Phase 5 builds directly on the Phase 3/4 loop:

- The worker→tester→reviewer leaf **is** the current `generate.py` loop, extracted to run as
  one node.
- Routing (`routing.py`) still decides Ollama vs Claude *per node*.
- Spec frontmatter (`spec.py`, `docs/spec-format.md`) gains a `depends_on` field so planners
  can express the DAG edges.
- Cost logging (`cost.py`) is upgraded from single-writer-implicit to single-writer-enforced.
</content>
</invoke>
