# GitHub Actions Integration

`aitk` ships a reusable workflow at `.github/workflows/aitk-generate.yml`. Other repos reference it directly — no copying required.

---

## Basic usage

```yaml
# .github/workflows/generate.yml  (in your other repo)
name: Generate module
on:
  workflow_dispatch:     # run manually from GitHub UI
  push:
    paths:
      - 'docs/SPEC.md'  # or trigger on spec changes

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

Add `ANTHROPIC_API_KEY` to your repo's **Settings → Secrets and variables → Actions**.

---

## All inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `spec` | yes | — | Path to the spec file |
| `output` | yes | — | Output path for generated code |
| `tests` | yes | — | Path to pytest test directory |
| `route` | no | `auto` | `auto`, `ollama`, or `claude` |
| `model` | no | `qwen2.5-coder:14b` | Ollama model (only used when route=ollama) |
| `python_version` | no | `3.11` | Python version for the runner |
| `open_pr` | no | `true` | Open a PR with generated file if tests pass |

## Outputs

| Output | Description |
|--------|-------------|
| `pass_count` | Number of tests that passed |
| `fail_count` | Number of tests that failed |
| `route_used` | Which route was used (`ollama` or `claude`) |
| `cost_usd` | Estimated Claude API cost |

---

## Routing in CI

The `auto` route works in CI but note:

- **`route: auto` with `estimated_lines` set** — accurate, uses the spec frontmatter
- **`route: auto` without `estimated_lines`** — uses a word-count heuristic (less accurate)
- **`route: ollama`** — the workflow installs Ollama on the runner and pulls the model (~2–3 min cold start)
- **`route: claude`** — no Ollama setup, faster CI, slightly higher cost for large files

For CI pipelines where build time matters more than cost, `route: claude` is often the right default. For nightly generation jobs where cost matters, use `route: auto` or `route: ollama` with `estimated_lines` set in the spec.

---

## Using outputs in downstream steps

```yaml
jobs:
  generate:
    uses: dfrausto32/internal-ai-toolkit/.github/workflows/aitk-generate.yml@main
    with:
      spec: docs/SPEC.md
      output: src/api.py
      tests: tests/
      open_pr: false        # handle PR creation yourself
    secrets:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

  notify:
    needs: generate
    runs-on: ubuntu-latest
    steps:
      - name: Post result to Slack
        run: |
          echo "Tests: ${{ needs.generate.outputs.pass_count }} passed"
          echo "Cost:  \$${{ needs.generate.outputs.cost_usd }}"
```

---

## Verifying the workflow itself

This repo ships a manually-triggered regression check, `aitk-generate smoke test`
(`.github/workflows/aitk-smoke-test.yml`), which runs a tiny 12-line spec
(`.github/aitk-smoke/`) through the real `aitk-generate.yml` pipeline — checkout,
install, generate, test, outputs — with `route: claude` and `open_pr: false` so
it stays fast and cheap. Run it after changing `aitk-generate.yml` or anything
under `src/aitk/` to confirm the reusable workflow still works end to end:

```bash
gh workflow run "aitk-generate smoke test" --ref <your-branch>
gh run watch
```

Requires `ANTHROPIC_API_KEY` to be set as a repo secret (see above).
