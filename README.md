# internal-ai-toolkit

A cost-optimized AI development pipeline that uses local Ollama models for code generation, test writing, CI config, and notifications — with Claude as the orchestrator for final review and quality verification.

## The Core Idea

Every token Claude spends generating boilerplate code is a token not spent on reasoning. This repo flips the model: Ollama handles the mechanical work locally (free, fast, private), and Claude only touches the output once — to verify structure, test coverage, and documentation quality before anything ships.

```
Task Input
    │
    ├─► ollama-coder     (qwen2.5-coder:14b)  — writes the code
    ├─► ollama-tester    (qwen2.5-coder:14b)  — writes the tests
    ├─► ollama-pipeline  (llama3.1:8b)        — writes CI/CD config
    └─► ollama-notifier  (llama3.2:3b)        — drafts Slack/Discord messages
            │
            ▼
    Claude Sonnet  — reviews all outputs, flags issues, approves or rejects
```

## Hardware (Reference Config)

This repo was developed and benchmarked on:

- **OS:** Windows 11 + WSL2 (Ubuntu 22.04)
- **GPU:** NVIDIA RTX 4080 (16 GB VRAM) — CUDA via WSL2 passthrough
- **RAM:** 32 GB allocated to WSL2
- **Disk:** ~1 TB available in WSL2 filesystem

Model selection is tuned for 16 GB VRAM. See `docs/ollama-setup.md` for other hardware configs.

## Repository Structure

```
internal-ai-toolkit/
├── README.md                        ← You are here
├── .claude/
│   └── agents/                      ← Phase 1: project-local Claude Code subagents
│       ├── ollama-coder.md
│       ├── ollama-tester.md
│       ├── ollama-pipeline.md
│       └── ollama-notifier.md
├── docs/
│   ├── ollama-setup.md              ← Ollama install + WSL2 setup guide
│   ├── roadmap.md                   ← Development phases and upcoming work
│   └── contributing.md              ← How to work in this repo
├── scripts/
│   └── ollama_stream.py             ← Helper script agents call to invoke Ollama
├── orchestrator/                    ← Phase 3: Claude Agent SDK implementation
│   ├── main.py
│   ├── agents.py
│   └── requirements.txt
└── benchmarks/                      ← Test applications for measuring output quality
    ├── README.md                    ← Benchmark methodology and scoring rubric
    ├── app_01_rest_api/             ← FastAPI CRUD service
    ├── app_02_data_pipeline/        ← CSV ingestion + transformation script
    └── app_03_cli_tool/             ← argparse CLI with subcommands
```

## Development Phases

### Phase 1 — `.md` Subagents (current)
Wire up Claude Code subagent definitions that delegate to Ollama via a Python helper script. Use the benchmark apps to evaluate output quality and tune prompts.

### Phase 2 — Claude Agent SDK
Migrate to a Python orchestrator using `claude_agent_sdk` + `httpx`. Ollama workers run in parallel via `asyncio.gather()`. Claude gets one structured review call per workflow run. Integrate with GitHub Actions.

See `docs/roadmap.md` for detailed task breakdown.

## Quick Start

### Prerequisites
- WSL2 (Ubuntu 22.04) with NVIDIA GPU passthrough working
- Ollama installed and running (`curl http://localhost:11434` returns OK)
- Claude Code installed (`claude --version`)
- Models pulled (see `docs/ollama-setup.md` → Step 3)

### Install models for this hardware config
```bash
ollama pull qwen2.5-coder:14b   # code gen + test writing (~9 GB VRAM)
ollama pull llama3.1:8b          # CI/pipeline config (~5 GB VRAM)
ollama pull llama3.2:3b          # notifications (~2 GB VRAM)
```

### Verify everything is running
```bash
ollama list
curl http://localhost:11434/api/generate \
  -d '{"model": "llama3.2:3b", "prompt": "Say hello", "stream": false}'
```

### Install Phase 2 dependencies (when ready)
```bash
cd orchestrator
pip install -r requirements.txt
```

## Benchmark Results

Results are tracked in `benchmarks/README.md` as each phase completes. Metrics captured per run:

- Claude token cost (input + output)
- Ollama generation time per agent
- Test pass rate on generated code
- Number of Claude review iterations needed
- Overall wall clock time

## License

Private repository — not for distribution.
