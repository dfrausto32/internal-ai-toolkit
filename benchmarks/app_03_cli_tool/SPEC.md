---
language: python
frameworks: []
estimated_lines: 90
test_command: pytest benchmarks/app_03_cli_tool/tests/ -v
---

# Spec: app_03_cli_tool

An argparse CLI with three subcommands that manages pipeline job configurations stored in YAML files.

---

## Deliverable

One file: `benchmarks/app_03_cli_tool/generated/cli.py`

Single-file. No sub-packages.

---

## Required exports from cli.py

The test suite imports these directly — they must exist with these exact names and signatures:

| Name | Signature | Purpose |
|------|-----------|---------|
| `init_config` | `(config_path: str) -> None` | Creates a default config YAML |
| `load_config` | `(config_path: str) -> dict` | Loads and validates a config YAML |
| `cmd_run` | `(config: dict, dry_run: bool = False) -> dict` | Executes a pipeline run |
| `cmd_status` | `(config: dict) -> dict` | Returns current pipeline status |

---

## Config YAML format

```yaml
pipeline:
  name: my-pipeline
  input: data/input.csv
  output: data/output.csv
  max_errors: 10
```

### Validation rules (enforced by `load_config`)

| Field | Type | Constraint |
|-------|------|------------|
| `pipeline.name` | str | Required, non-empty |
| `pipeline.input` | str | Required, non-empty |
| `pipeline.output` | str | Required, non-empty |
| `pipeline.max_errors` | int | Required, must be >= 0 |

---

## Function behaviour

### `init_config(config_path: str) -> None`
- Creates a YAML file at `config_path` with default values (see format above)
- Raises `FileExistsError` if a file already exists at that path

### `load_config(config_path: str) -> dict`
- Reads and parses the YAML file at `config_path`
- Raises `FileNotFoundError` if the file does not exist
- Raises `ValueError` if any required field is missing or fails its validation rule
- Returns the parsed config as a dict (same shape as the YAML above)

### `cmd_run(config: dict, dry_run: bool = False) -> dict`
- Simulates running the pipeline described by `config`
- Does not need to actually process any files — just return a status dict
- Returns: `{"status": "ok", "dry_run": <bool>}`

### `cmd_status(config: dict) -> dict`
- Returns a summary of the pipeline configuration
- Returns: `{"status": "ok", "config": <the config dict>}`

---

## CLI interface

Three subcommands via argparse:

```bash
python cli.py init   --config <path>
python cli.py run    --config <path> [--dry-run]
python cli.py status --config <path>
```

- `--config` is required for all three subcommands
- `--dry-run` is a boolean flag (store_true) on the `run` subcommand
- `python cli.py --help` and `python cli.py <subcommand> --help` must exit with code 0

The CLI `__main__` block must:
1. Parse arguments
2. Call the appropriate function (`init_config`, `cmd_run`, `cmd_status`)
3. Print results as JSON (for `run` and `status`)

---

## Documentation requirements

Every function (`init_config`, `load_config`, `cmd_run`, `cmd_status`) must have a docstring describing what it does, its parameters, and what it raises.

---

## Success criteria

```bash
pytest benchmarks/app_03_cli_tool/tests/ -v
```

All 13 tests pass, 0 failures, 0 errors.
