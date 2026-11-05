# Phase 5 — Multi-Agent Dashboard & Dynamic Sprint Orchestration

The major milestone: a custom control plane + dashboard that lets you **monitor every
agent live, fire commands at them, create agents with distinct personalities/purposes,
and run a full sprint** as a dynamic workflow — one planner agent decomposes work, hands
off to parallel workers, which hand off to testers, then to a merger that finalizes the
sprint.

This generalizes what already exists: `aitk`'s `generate → test → Claude review → retry`
loop is a single-worker dynamic workflow with a cost router. Phase 5 turns that one loop
into N role-specialized agents with observability on top. **It is orchestration +
observability, not a rewrite** — we build on the Claude Agent SDK, the existing
`.claude/agents/*.md` definitions, and the `aitk` router/loop.

## Decisions locked

- **No Kimi.** The cloud model tier is **Claude only**. (Kimi K2.7-Code is a 1T-param
  model needing 240 GB+ unified memory — it cannot run on a single consumer GPU anyway, and we are
  not using it via cloud either.)
- **Hybrid compute, tunable line.** Local `qwen2.5-coder:14b` (and other local models) by
  default; escalate to Claude when a configurable threshold says so. The threshold and the
  model tiers live in **config, not code**, so upgrading hardware = register a bigger local
  model + move the line, no code change.
- **Custom, but lean on components.** Build the control plane and UI ourselves; reuse
  FastAPI, the Claude Agent SDK, an off-the-shelf frontend kit, SQLite, etc.
- **First major milestone = everything** below, delivered as 6 medium milestones, each
  split into 5 sub-phases.

## Model tiers → sprint roles

| Role | Model | Rationale |
|------|-------|-----------|
| **Planner** | Claude | Strong reasoning + plan mode; one call per sprint |
| **Workers** (parallel) | `qwen2.5-coder:14b` local; escalate to Claude per the tunable router | Most generation stays free + private |
| **Testers** | `qwen2.5-coder:14b` local | Reuses `ollama-tester`; cheap + local |
| **Merger / finalizer** | Claude | Conflict resolution + "is the sprint done" is judgment |

## Dependency order

Foundation first: **1 → 2 → 3** are required by everything else. **4** (sprint) needs 1–3.
**5** (dashboard) and **6** (agent builder) sit on top of 1–3 and can proceed in parallel
once the foundation lands.

---

## Medium Milestone 1 — Model Router & Hardware-Scaling Config

Turn the hardcoded `ollama-vs-claude` break-even (`routing.py`, `BREAK_EVEN_TOKENS`) into a
config-driven, role-aware, hardware-aware router with a tunable line.

- [ ] **1.1 Config schema** — `aitk.toml` defining model tiers (local models + Claude;
      no Kimi), per-model capability + VRAM cost, and a hardware profile (VRAM budget, RAM).
- [ ] **1.2 Tunable threshold** — extract `BREAK_EVEN_TOKENS` and heuristics out of
      `routing.py` into config; add a `--threshold` / config override so the line is a knob.
- [ ] **1.3 Role-aware routing** — router takes a role (planner/worker/tester/merger) and
      picks a model per role from config; worker tier still uses the cost heuristic.
- [ ] **1.4 Hardware-fit guard** — router only selects local models that fit the declared
      VRAM budget; `aitk models` lists registered tiers and what currently fits. Upgrading
      hardware = register a bigger model + bump the budget.
- [ ] **1.5 Tests + migration** — unit tests across roles/thresholds; migrate existing
      `decide_route` callers; `docs/routing.md`.

**DoD:** Changing one config value moves the local/Claude line; adding a model entry makes
a new local model eligible — both with zero code changes.

## Medium Milestone 2 — Agent Runtime / Control Plane

A Python service that spawns, runs, monitors, and stops agents under one interface — Claude
agents via the Agent SDK, local agents via the existing `aitk`/Ollama path.

- [ ] **2.1 Agent abstraction** — `Agent` (id, role, model, system prompt, status,
      transcript) + `AgentRun` lifecycle (queued → running → done/failed/stopped).
- [ ] **2.2 Claude backend** — wrap the Claude Agent SDK to run a Claude agent from a
      system prompt + task, streaming events.
- [ ] **2.3 Local backend** — wrap existing `aitk` generate / `ollama_generate` as the
      worker/tester backend so local agents reuse the proven loop.
- [ ] **2.4 Spawn/stop orchestrator** — launch agents (parallel via asyncio), track them,
      stop one or all; concurrency cap tied to hardware so the local GPU isn't overloaded.
- [ ] **2.5 Tests + headless CLI** — `aitk agent run --role worker --task ...`; integration
      test spawning 2 parallel local workers + 1 Claude agent.

**DoD:** From a CLI call, spawn and stop both a local and a Claude agent and get their
transcripts back.

## Medium Milestone 3 — Event & State Store

Every agent emits structured events; persist them; expose a read + live-subscribe API the
dashboard consumes. Also the unified cost ledger.

- [ ] **3.1 Event schema** — `agent_started`, `tool_call`, `output_chunk`, `test_result`,
      `review`, `cost`, `finished`, with timestamps + agent/run/sprint IDs.
- [ ] **3.2 Emit via hooks** — instrument the control plane and `aitk` loop to emit events;
      use SDK hooks for Claude agents.
- [ ] **3.3 Persistence** — SQLite store (runs, events, cost ledger); fold the existing
      `cost.py` `log_run` + `agent_token_stats.json` into one ledger.
- [ ] **3.4 Read/subscribe API** — query past runs; live async pub/sub feeding a WebSocket.
- [ ] **3.5 Tests + cost CLI upgrade** — extend `aitk cost` / add `aitk runs` to read the
      unified ledger; event round-trip tests.

**DoD:** A running agent's events land in SQLite and stream to a subscriber in real time;
`aitk cost` reads the same ledger.

## Medium Milestone 4 — Sprint Orchestration / Dynamic Workflow

The planner → workers → testers → merger pipeline as a loop-driven, dynamic workflow
(plan mode + loops + handoff).

- [ ] **4.1 Sprint model** — a Sprint (set of features) + Task DAG; handoff artifacts
      (plan → feature tasks → code → test results → merged branch).
- [ ] **4.2 Planner stage (plan mode)** — a Claude planner ingests a sprint goal and emits
      a plan + decomposed feature tasks; **N workers decided at runtime** (the dynamic part).
- [ ] **4.3 Worker fan-out + loop** — spawn parallel workers (one per feature task), each
      running the existing generate → test → review → retry loop; bounded concurrency;
      per-worker git worktree/branch to avoid collisions.
- [ ] **4.4 Tester + merger stages** — testers validate worker output; a Claude merger
      resolves conflicts, integrates branches, decides "sprint done." Loop until green or
      max iterations.
- [ ] **4.5 Handoff + e2e** — shared-state/mailbox handoff between stages; end-to-end test
      on one small real feature; `docs/sprint-workflow.md`.

**DoD:** One command takes a multi-feature sprint goal and produces an integrated, tested,
Claude-reviewed branch with no manual hand-holding between stages.

**Worker task-sizing rule (the planner's core job).** `qwen2.5-coder:14b` on a 16 GB GPU is
reliable only when a task is: (1) a **single file**, **~100–200 lines** target; (2) a
**frozen interface** — signatures + input/output schema fixed by the planner, no design left
to the worker; (3) **stdlib or one declared framework**; (4) shipped with an **acceptance
test** to loop against; (5) **independent** — no dependency on another in-flight worker's
choices. Two lines bound the worker tier: below ~100 lines, route to Claude directly (cheaper
*and* better); above ~200 lines or any multi-file coupling, the planner must split further.
The planner owns every cross-file seam (module boundaries, shared data model, the contracts
between files) so each 14B worker fills one box against a fixed contract.

**Local parallelism caveat.** A 14B model is 9 GB; a 16 GB card has ~14 GB free — so only **one
14B worker runs at a time**. Local "parallel" workers are a queue through one GPU (the 3B/8B
models can run alongside). Claude workers parallelize freely. Milestone 2's concurrency cap
and Milestone 1's hardware profile encode this; both lift automatically on a hardware upgrade.

## Medium Milestone 5 — Web Dashboard UI

The GUI to watch everything live and fire commands.

- [ ] **5.1 Backend API** — FastAPI exposing the state store (runs/agents/sprints) +
      WebSocket live feed; serves the frontend.
- [ ] **5.2 Live monitor view** — agent cards (role, model, status, current tool, tokens,
      cost) updating over WebSocket; sprint/DAG view.
- [ ] **5.3 Log/transcript drill-down** — click an agent → live streaming transcript +
      test/review output.
- [ ] **5.4 Command box** — fire a task at a specific agent or start a sprint from the UI;
      stop buttons.
- [ ] **5.5 Cost dashboard + polish** — aggregate cost view (per run/sprint/role, local vs
      Claude); responsive layout; API + smoke e2e tests.

**Stack:** FastAPI + WebSocket backend; **React** SPA frontend (locked 2026-06-19).

**DoD:** Open the dashboard, watch a live sprint run, drill into any agent's transcript, and
start/stop work from the browser.

## Medium Milestone 6 — Agent Builder GUI

Interactive creation of agents with distinct personalities/purposes → `.claude/agents/*.md`.

- [ ] **6.1 Definition schema** — formalize the `.claude/agents/*.md` frontmatter (name,
      role, model tier, tools, system prompt = personality) + loader/validator.
- [ ] **6.2 Builder form** — GUI form (name, purpose, personality, model tier from the
      router config, tool allowlist) with live preview of the generated `.md`.
- [ ] **6.3 Save/edit/version** — write/update `.claude/agents/*.md`; list/edit existing
      agents; keep the prompt-tuning-history comment convention.
- [ ] **6.4 Personality templates** — starter archetypes (planner, worker, tester, merger)
      prefilled so building a sprint team is a few clicks.
- [ ] **6.5 Wire into runtime + tests** — created agents are immediately spawnable by the
      control plane and assignable to sprint roles; generate/load round-trip tests.

**DoD:** Create a new agent in the browser, see its `.md` written, and assign it to a sprint
role without leaving the dashboard.

---

## Resolved decisions

- **Frontend stack** — React SPA (decided 2026-06-19).
</content>
</invoke>
