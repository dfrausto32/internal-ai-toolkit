"""
Ground truth test suite for app_03_cli_tool.

Never generate or modify these tests with AI — they define what correct means.
Run from the repo root: pytest benchmarks/app_03_cli_tool/tests/ -v

Expects the implementation at: benchmarks/app_03_cli_tool/generated/cli.py
Exports required: init_config, load_config, cmd_run, cmd_status
"""
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_GENERATED_DIR = Path(__file__).parent.parent / "generated"
_CLI_PATH = _GENERATED_DIR / "cli.py"
sys.path.insert(0, str(_GENERATED_DIR))

from cli import cmd_run, cmd_status, init_config, load_config  # noqa: E402

_VALID_CONFIG = {
    "pipeline": {
        "name": "test-pipeline",
        "input": "data/input.csv",
        "output": "data/output.csv",
        "max_errors": 5,
    }
}


def _write_config(path, data):
    with open(path, "w") as f:
        yaml.dump(data, f)


# ---------------------------------------------------------------------------
# init_config
# ---------------------------------------------------------------------------

def test_init_creates_config_file(tmp_path):
    config_path = str(tmp_path / "config.yaml")
    init_config(config_path)
    assert Path(config_path).exists()


def test_init_config_contains_required_keys(tmp_path):
    config_path = str(tmp_path / "config.yaml")
    init_config(config_path)
    with open(config_path) as f:
        data = yaml.safe_load(f)
    pipeline = data["pipeline"]
    assert "name" in pipeline
    assert "input" in pipeline
    assert "output" in pipeline
    assert "max_errors" in pipeline


def test_init_raises_if_file_exists(tmp_path):
    config_path = str(tmp_path / "config.yaml")
    init_config(config_path)
    with pytest.raises(FileExistsError):
        init_config(config_path)


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------

def test_load_config_returns_valid_dict(tmp_path):
    config_path = str(tmp_path / "config.yaml")
    _write_config(config_path, _VALID_CONFIG)
    config = load_config(config_path)
    assert isinstance(config, dict)
    assert config["pipeline"]["name"] == "test-pipeline"


def test_load_config_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nonexistent.yaml"))


def test_load_config_raises_on_missing_name(tmp_path):
    config_path = str(tmp_path / "config.yaml")
    bad = {"pipeline": {"input": "in.csv", "output": "out.csv", "max_errors": 0}}
    _write_config(config_path, bad)
    with pytest.raises(ValueError):
        load_config(config_path)


def test_load_config_raises_on_negative_max_errors(tmp_path):
    config_path = str(tmp_path / "config.yaml")
    bad = {
        "pipeline": {
            "name": "p",
            "input": "in.csv",
            "output": "out.csv",
            "max_errors": -1,
        }
    }
    _write_config(config_path, bad)
    with pytest.raises(ValueError):
        load_config(config_path)


def test_load_config_raises_on_empty_name(tmp_path):
    config_path = str(tmp_path / "config.yaml")
    bad = {
        "pipeline": {
            "name": "",
            "input": "in.csv",
            "output": "out.csv",
            "max_errors": 0,
        }
    }
    _write_config(config_path, bad)
    with pytest.raises(ValueError):
        load_config(config_path)


# ---------------------------------------------------------------------------
# cmd_run
# ---------------------------------------------------------------------------

def test_cmd_run_returns_ok_status():
    result = cmd_run(_VALID_CONFIG)
    assert result["status"] == "ok"


def test_cmd_run_dry_run_true():
    result = cmd_run(_VALID_CONFIG, dry_run=True)
    assert result["dry_run"] is True


def test_cmd_run_dry_run_false_by_default():
    result = cmd_run(_VALID_CONFIG)
    assert result["dry_run"] is False


# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------

def test_cmd_status_returns_ok_status():
    result = cmd_status(_VALID_CONFIG)
    assert result["status"] == "ok"


def test_cmd_status_includes_config():
    result = cmd_status(_VALID_CONFIG)
    assert "config" in result
    assert result["config"] == _VALID_CONFIG


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

def test_cli_help_exits_zero():
    proc = subprocess.run(
        [sys.executable, str(_CLI_PATH), "--help"],
        capture_output=True,
    )
    assert proc.returncode == 0
