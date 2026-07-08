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
extra reasoning pays for itself — the choice is per-node, not global. The planner is the one
node where this choice is non-obvious; §6a specifies how it resolves.

### 6a. The planner — a tiered component

The planner is the only node where "API call vs agent" is a real contest (worker, tester,
and reviewer are structured enough that a direct API call is always right). It resolves by
splitting the planner into two separable halves and making only the first half pluggable:

- **Understand** — what already exists, the conventions, where new code plugs in.
- **Decide** — emit the module list, the dependency edges, the per-node specs.

The **decide** half is *always* a structured API call — you want a machine-checkable DAG.
The substrate debate is only about **understand**, and it splits by target:

- *Greenfield, spec-is-the-world* (today's benchmarks): nothing to explore; an agent's
  repo-reading buys nothing.
- *Brownfield, "add feature X to this repo"* (the stated vision): plan quality depends on
  reading real code — exactly what an agent does and a blind API call can't.

**The clean seam: both paths emit the identical validated DAG, so the scheduler never knows
which produced it.**

**1 — Context-gatherer (deterministic, always runs first).** No LLM, trivially in-budget.
Collects the mechanically-discoverable facts: repo file tree, existing public interfaces
(signatures via AST / grep — the same interface data the result store uses in §8), the
dependency manifest, any existing `SPEC.md`s. For greenfield this blob is near-empty, which
is correct.

**2 — Planner API call = the "decide" (default path).** Input: feature spec + repo context.
Output forced to a structured DAG via tool-use JSON —
`nodes: [{ id, spec, framework, depends_on: [...], estimated_lines, route_hint }]` — then
validated in Python (acyclic, every `depends_on` resolves, no orphans). Invalid → cheap
reject + retry. Stays inside the API lease.

**3 — Escalation as a fallback, NOT an upfront gate.** Do not try to *predict* whether a
repo is messy enough to need an agent — that prediction itself needs judgment. Instead, give
the API planner an explicit `needs_exploration` escape hatch in its output schema ("I can't
resolve where this feature integrates from the context given"). Only when it raises that flag
do you spawn the agent. You pay for the agent exactly when the cheap path *admits defeat* —
never speculatively. Greenfield never triggers it; clean brownfield rarely does.

**4 — Budget-capped agent wrapper (the escalation target).** Spawned with a hard token/cost
cap; on exceed it returns its best partial DAG. Its output runs through the *same* DAG
validation as path 2. That bounds the budget hole an agent otherwise opens — it can't run
away, and if it tries it degrades to a validated-partial plan rather than blowing the ceiling.

**Trade-off accepted:** the `needs_exploration` self-report isn't perfect — a
confidently-wrong planner can skip the hatch and emit a plausible-but-misgrounded DAG. The
reviewer gate catches *code* drift downstream, but a bad *decomposition* slips through
earlier. Mitigation if it bites (not worth building until it does): a cheap validation pass
checking the proposed DAG's nodes against the real interfaces the context-gatherer already
collected.

---

## 6b. Decision log — vision round 1 (locked)

These six are settled. Items still open (test-trust model, human-in-the-loop, where
per-node specs live, single-repo vs multi-repo) are tracked in §7 and being resolved over
follow-up discussion.

| # | Decision | Resolution | Implication |
|---|----------|------------|-------------|
| 1 | **Scheduler process model** | **Lightweight shared broker** — a persistent token-bucket + cost ledger that independent `aitk` processes coordinate through (not one monolithic process, not per-invocation budgets). | Preserves the global ceiling across separately-launched orchestrators. The broker is the one piece that must be a durable shared service (socket/file-backed). |
| 2 | **Worker⇅tester loop** | Tests authored **up front** per spec iteration. **But** the test-execution step is **pluggable per node**, not hardcoded pytest — it must support non-Python frameworks (gtest, language-specific runners) via the spec's `test_command`, and provide an explicit **escape path for validation that can't be fully automated** (hardware-in-the-loop, simulation, real-instance dependencies). Those nodes fall back to a non-test gate (reviewer / human) rather than blocking the loop forever. | Promotes `test_command` from informational (today) to executed. Adds a "validation kind" per node: `automated` vs `gated`. The loop's green-signal is "test command passed" *or* "gate satisfied". |
| 3 | **Per-role model** | **Per-role config** — planner / worker / tester / reviewer each get their own configurable model (cost-vs-capability per role). | Replaces today's hardcoded model choices. Config surface, not code change, to retune. |
| 4 | **Budget unit** | **Dollars** is the real ceiling. Broker throttles/limits on cumulative spend, converting tokens→dollars via the per-model rate table (rates already in `cost.py`). | Token-aware lease becomes dollar-aware: every call estimates cost, broker refuses/queues past the $ cap. Needs a per-model pricing table keyed by the role models from #3. |
| 5 | **Result-store interface** | **Signatures + docstrings** (AST-extracted), not full source. | Cheap dependent-input cost; the result store extracts public signatures + one-line docstrings from a finished node's files. |
| 6 | **Node granularity** | **Multi-file nodes** allowed — a node maps to a set of output files + its tests, not a single file. | `generate.py`'s single-file assumption must be generalized. Sandboxing is per-node *directory*; interface extraction (#5) spans all of a node's files. |

---

## 6c. Decision log — vision round 2 (locked)

| Item | Decision | Resolution | Implication |
|------|----------|------------|-------------|
| A | **Test-trust model** | The **planner emits explicit acceptance criteria per node**. Generated tests must cover them; the reviewer receives the acceptance criteria as ground truth. | `acceptance_criteria` becomes a first-class field on every node spec. This is the anti-collusion anchor — tests and code are no longer the only sources of truth. |
| B | **Human-in-the-loop** | **Review after the plan is emitted**, before any worker spends tokens. Approval gate sits between planner and scheduler dispatch. | Splits the flow into **plan → review → build**. Because node specs are on disk (item C), the human can *edit* them during review, not just approve/reject. |
| C | **Per-node specs** | **Written to disk.** Main spec is human-co-authored; each node spec is an **expanded slice of the main spec** containing everything that node needs before writing — its portion of the main spec plus extra detail, its `acceptance_criteria`, `depends_on`, and (at build time) its dependencies' extracted interfaces. | Planner does decomposition **and** expansion. Proposed layout: `\.aitk/plans/<feature>/<node-id>.md`, one spec file per node, reusing the existing spec frontmatter convention. Reviewable + editable artifact. |
| D | **Single vs multi repo** | **Both.** Guiding constraint: concurrent planners/nodes should work on **unrelated things** to avoid interfering. | Adds a coordination requirement beyond DAG edges (see below). |

### Derived points these answers create

- **Acceptance-criteria coverage** (from A): something must check that the generated tests actually exercise the criteria — assigned to the **reviewer**, which already sees the original spec; it now also sees the per-node acceptance criteria and flags uncovered ones. *(Open: whether to add a cheaper pre-reviewer coverage check — deferred.)*
- **Plan approval mechanics** (from B): approval is **per-feature-plan (whole DAG)**, with on-disk node specs editable before build. The CLI surface therefore needs a distinct `plan` step that halts for review and a `build` step that consumes the approved plan.
- **Write-scope conflict avoidance** (from D): two nodes with *no dependency edge* can still collide if they write overlapping files. Since nodes are multi-file (round-1 #6), **each node declares its output file set, and the scheduler/broker serializes any two nodes whose output scopes overlap** — a path-keyed write lock layered on top of the DAG. "Unrelated work" is enforced, not just hoped for. Mechanism detail TBD.

---

## 6d. Mechanism decisions (resolves the §6c TBDs)

**Node-spec location — confirmed:** `.aitk/plans/<feature>/<node-id>.md`, one spec file per
node, reusing the existing spec frontmatter convention. Reviewable and editable during the
plan-approval gate (round-2 B).

### Write-scope lock — broker-held, atomic, path-keyed

The write-scope lock lives in the **broker**, not the in-process scheduler. The broker is
already the cross-process authority for the dollar budget (round-1 #1); write-scope
collisions are the *same* cross-process problem (two separately-launched orchestrators
touching the same files), so one authority owns both.

- **Declared scope:** each node declares `output_scope` (concrete file paths and/or directory
  prefixes) in its node spec. The planner aims to make scopes **disjoint by construction**
  ("unrelated work", round-2 D); the lock is the **safety net** for collisions it can't see
  across features/repos.
- **Atomic whole-scope acquisition:** before running, a node requests a write-lease over its
  *entire* scope in one broker call. Granted only if no overlapping path/prefix is currently
  leased; otherwise the node waits. Acquiring the whole scope atomically eliminates
  hold-and-wait → **deadlock-free**.
- **Overlap rule:** two scopes conflict if any concrete path in one is equal-to or
  prefix-of a path in the other. File-level locks where paths are enumerable; prefix locks
  for directory scopes. Fine-grained to preserve concurrency.
- **Composes with the DAG:** dependency edges already serialize A→B, so by the time B runs,
  A's lease is released — a shared file between a node and its declared dependency is fine.
  The lock only adds serialization between nodes with *no* edge.
- **Robustness:** leases are tied to a run id with a **TTL / heartbeat** so a crashed
  orchestrator cannot hold a lock (or budget) forever.

### Acceptance-criteria coverage — layered, cheap-then-smart

Mirrors the design's standing philosophy (deterministic check first, LLM only for judgment —
same shape as the planner's context-gatherer→API-call, §6a):

1. **Planner emits criteria with stable ids** (`AC-1`, `AC-2`, …) per node.
2. **Tester tags each generated test** with the criterion id(s) it targets — pytest marker
   or naming convention; a parallel convention for non-Python runners (gtest etc.).
3. **Deterministic coverage check (no LLM):** parse the tests, compare referenced ids vs the
   full criteria set. Any criterion with zero tests **fails fast and loops back to the
   tester** to regenerate — no Claude call spent. Bounded by the loop cap (round-1 #2).
4. **Reviewer judges adequacy:** tagging proves a test *claims* `AC-1`, not that it is a
   *good* test. The reviewer receives the criteria + the coverage map and flags weak coverage.

**Division of labour:** step 3 catches **missing** coverage for free; step 4 catches **weak**
coverage. For `gated` / non-automatable nodes (round-1 #2) there are no tests, so step 3 is
skipped and coverage falls entirely to the reviewer / human gate against the criteria.

### Accumulating node-spec schema

These decisions add fields to the per-node spec (to be formalized in `docs/spec-format.md`
as a Plan task): `output_scope`, `acceptance_criteria` (with ids), `validation_kind`
(`automated` | `gated`), `depends_on`, plus the existing `framework` / `test_command`.

---

## 7. Open decisions (resolve during implementation)

| Decision | Options | Default leaning |
|----------|---------|-----------------|
| **Failure policy** | (a) skip failed node's subtree, finish independent branches; (b) fail-fast, halt the DAG | Make it a **pluggable hook**; pick default at build time. (Parked per design discussion.) |
| **Planner substrate** | API-call vs spawned-agent | **Resolved (§6a):** tiered — deterministic context-gatherer + API-call decide by default; escalate to a budget-capped agent only on a `needs_exploration` self-report |
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
