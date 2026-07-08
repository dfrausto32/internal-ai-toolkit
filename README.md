# internal-ai-toolkit

A cost-optimized AI development pipeline. Claude Sonnet generates code from a spec, Claude Haiku reviews it against the spec and test results, and the pipeline retries once on blocking errors. When local-model hardware is available (`AITK_OLLAMA_ENABLED=1`), Ollama takes over generation for large jobs — free, fast, private — with the same Claude review layer on top. The `aitk` CLI wires it all together, including drafting the spec itself.

---

## Using aitk in another repo

### 1. Install

```bash
pip install git+https://github.com/dfrausto32/internal-ai-toolkit.git
# or locally:
pip install -e /path/to/internal-ai-toolkit
```

### 2. Set your API key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Write a spec — or have Claude draft it

Let Claude turn a plain-English description into a complete, routable spec:

```bash
aitk spec init --describe "A rate limiter with sliding-window and token-bucket strategies" --out SPEC.md
# or pipe a longer description:
cat idea.md | aitk spec init --out SPEC.md
```

The draft includes the frontmatter the router needs (`frameworks`, `estimated_lines`, `test_command`) and a body structured for one-pass generation (public interface, behavior, edge cases, out-of-scope). Review and edit it before generating.

Or write `SPEC.md` by hand. Include a frontmatter block so the router knows what it's working with:

```markdown
---
language: python
frameworks: [fastapi, sqlalchemy, pydantic]
estimated_lines: 200
test_command: pytest tests/ -v
---

# What to build
...requirements in plain prose...
```

See [docs/spec-format.md](docs/spec-format.md) for the full format reference.

### 4. Preview the routing decision

```bash
aitk route --spec SPEC.md
```

This tells you whether `aitk generate` will use Ollama or raw Claude — and why — without running anything.

### 5. Generate

```bash
aitk generate --spec SPEC.md --out src/module.py --tests tests/
```

`aitk` will:
1. Route the job (Claude by default; Ollama for large specs when `AITK_OLLAMA_ENABLED=1`)
2. Generate the code (Claude Sonnet, or local Ollama)
3. Run your test suite
4. Send the code + test output to Claude Haiku for review
5. Retry once if the review flags blocking errors
6. Log the run cost

### 6. Check cost history

```bash
aitk cost
```

### GitHub Actions

Use the reusable workflow to run generation in CI:

```yaml
jobs:
  generate:
    uses: dfrausto32/internal-ai-toolkit/.github/workflows/aitk-generate.yml@main
    with:
      spec:   docs/SPEC.md
      output: src/api.py
      tests:  tests/
    secrets:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

See [docs/github-actions.md](docs/github-actions.md) for all inputs, outputs, and routing options in CI.

---

## How routing works

`--route auto` resolves to **claude** unless local models are enabled (`AITK_OLLAMA_ENABLED=1` — off by default, since the current machine can't run them). With local models enabled, auto falls back to the size heuristic:

| Local models | File size | Route | Reason |
|--------------|-----------|-------|--------|
| disabled | any | Claude + Haiku review | No Ollama server to depend on |
| enabled | < ~100 lines | Claude + Haiku review | Small jobs: Claude quality is cheap |
| enabled | > ~100 lines | Ollama + Haiku review | Large jobs: local generation is free |

Override with `--route ollama` or `--route claude` if needed. Both routes get the same Haiku review + retry loop.

---

## How it works

```
aitk spec init ──► Claude drafts SPEC.md (frontmatter + buildable body)
                        │
aitk generate ◄─────────┘ (after human review)
    │
    ├─ route=ollama ─► qwen2.5-coder:14b (local, free; needs AITK_OLLAMA_ENABLED=1)
    │                       │
    └─ route=claude ─► Claude Sonnet 4.6 (direct generation)
                            │
                       pytest tests/
                            │
                       Haiku review ──► blocking errors? ──► retry once
```

The Haiku review catches: wrong imports, schema drift, missing guards, falsy integer checks, missing docstrings.

---

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/install.md](docs/install.md) | Full install options, prerequisites, environment variables |
| [docs/spec-format.md](docs/spec-format.md) | Spec frontmatter schema, framework rules, routing behaviour |
| [docs/github-actions.md](docs/github-actions.md) | Reusable workflow reference, inputs, outputs, CI routing advice |
| [docs/ollama-setup.md](docs/ollama-setup.md) | Ollama install on WSL2 + NVIDIA GPU passthrough |
| [docs/roadmap.md](docs/roadmap.md) | Phase history and what's next |
| [docs/design-parallel-orchestration.md](docs/design-parallel-orchestration.md) | Phase 5 design — parallel orchestration architecture ([visual site](docs/design.html)) |
| [benchmarks/README.md](benchmarks/README.md) | Benchmark methodology, scoring rubric, Phase 1–3 results |

---

## Repository structure

```
internal-ai-toolkit/
├── src/aitk/                    ← installable package (pip install -e .)
│   ├── cli.py                   ← aitk generate / cost / route / spec init
│   ├── config.py                ← models, pricing, local-model availability
│   ├── spec.py                  ← spec frontmatter parser
│   ├── specgen.py               ← Claude-drafted SPEC.md (aitk spec init)
│   ├── routing.py               ← Ollama vs Claude break-even logic
│   ├── agents.py                ← async Ollama worker, dynamic system prompt
│   ├── review.py                ← Claude review step
│   ├── generate.py              ← full generation + retry loop
│   └── cost.py                  ← run cost log and display
├── pyproject.toml               ← package config, aitk entry point
├── .github/workflows/
│   └── aitk-generate.yml        ← reusable workflow for other repos
├── .claude/agents/              ← Claude Code subagents (global, Phase 1)
│   ├── ollama-coder.md
│   ├── ollama-tester.md
│   ├── ollama-pipeline.md
│   └── ollama-notifier.md
├── scripts/
│   └── ollama_stream.py         ← low-level Ollama streaming helper
├── benchmarks/                  ← test apps used to validate aitk quality
│   ├── app_01_rest_api/
│   ├── app_02_data_pipeline/
│   └── app_03_cli_tool/
└── docs/
```

---

## Hardware reference (optional — local models only)

No special hardware is needed for the default Claude-only pipeline. The local Ollama route requires a GPU with enough VRAM for the models below (originally developed against an RTX 4080, 16 GB VRAM); enable it with `AITK_OLLAMA_ENABLED=1`. See [docs/ollama-setup.md](docs/ollama-setup.md).

```bash
ollama pull qwen2.5-coder:14b   # code generation (~9 GB VRAM)
ollama pull llama3.1:8b          # CI/pipeline config (~5 GB VRAM)
ollama pull llama3.2:3b          # notifications (~2 GB VRAM)
```

---

## Benchmark results (Phase 1–3)

| App | Phase 1 | Phase 3 (aitk) |
|-----|---------|----------------|
| app_01_rest_api | 5 / 9 | 6 / 9 |
| app_02_data_pipeline | 4 / 9 | 8 / 9 |
| app_03_cli_tool | 8 / 9 | 8 / 9 |
| **Combined** | **17 / 27** | **22 / 27** |

Full results and methodology → [benchmarks/README.md](benchmarks/README.md)

---

## License

Private repository — not for distribution.
