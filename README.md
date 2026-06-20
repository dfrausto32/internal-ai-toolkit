# internal-ai-toolkit

A cost-optimized AI development pipeline. Local Ollama models handle code generation (free, fast, private). Claude handles review and quality verification. The `aitk` CLI wires them together and routes each job to whichever backend is cheaper.

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

### 3. Write a spec

Add a `SPEC.md` to your project describing what to generate. Include a frontmatter block so the router knows what it's working with:

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
1. Route the job (Ollama or Claude, based on spec size)
2. Generate the code
3. Run your test suite
4. Send the code + test output to Claude for review
5. Retry once if Claude flags blocking errors
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

Every `aitk generate --route auto` call estimates the output size from the spec's `estimated_lines` field and compares it to the break-even threshold:

| File size | Route | Reason |
|-----------|-------|--------|
| < ~100 lines | Raw Claude | Generation output is cheap; review overhead dominates |
| > ~100 lines | Ollama + Claude review | Code tokens are 5× cheaper as review input ($3/1M) than as Claude output ($15/1M) |

Override with `--route ollama` or `--route claude` if needed.

---

## How it works

```
aitk generate
    │
    ├─ route=ollama ─► qwen2.5-coder:14b (local, free)
    │                       │
    │                  pytest tests/
    │                       │
    │                  Claude review ──► blocking errors? ──► retry once
    │
    └─ route=claude ─► Claude Sonnet 4.6 (direct generation)
                            │
                       pytest tests/
```

Claude review catches: wrong imports, schema drift, missing guards, falsy integer checks, missing docstrings.

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
│   ├── cli.py                   ← aitk generate / cost / route
│   ├── spec.py                  ← spec frontmatter parser
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

## Hardware reference

Developed on Windows 11 + WSL2 (Ubuntu 22.04), NVIDIA RTX 4080 (16 GB VRAM), 32 GB RAM.
Model selection is tuned for 16 GB VRAM. See [docs/ollama-setup.md](docs/ollama-setup.md) for other configs.

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
