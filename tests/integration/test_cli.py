from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from rebuildwhy.cli import main

REPOSITORY_ROOT = Path(__file__).parents[2]


def copy_demo(tmp_path: Path) -> Path:
    destination = tmp_path / "demo"
    shutil.copytree(
        REPOSITORY_ROOT / "examples" / "synthetic_mri",
        destination,
        ignore=shutil.ignore_patterns(".rebuildwhy", "outputs", "__pycache__"),
    )
    return destination / "pipeline.yaml"


def test_plan_json_is_machine_readable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pipeline = copy_demo(tmp_path)

    exit_code = main(["plan", "-p", str(pipeline), "--json"])
    captured = capsys.readouterr()
    body = json.loads(captured.out)

    assert exit_code == 0
    assert body["schema_version"] == 1
    assert body["affected_task_ids"] == [
        "ingest",
        "resample",
        "normalize",
        "features",
        "report",
    ]


def test_structured_json_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.yaml"

    exit_code = main(["plan", "-p", str(missing), "--json"])
    captured = capsys.readouterr()
    body = json.loads(captured.err)

    assert exit_code == 2
    assert body["schema_version"] == 1
    assert body["error"]["code"] == "PIPELINE_NOT_FOUND"


def test_human_plan_and_run_are_readable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pipeline = copy_demo(tmp_path)

    assert main(["plan", "-p", str(pipeline)]) == 0
    plan_output = capsys.readouterr().out

    assert "RebuildWhy plan: synthetic-mri-demo (current)" in plan_output
    assert "ingest RUN" in plan_output
    assert "NEW_TASK: ingest" in plan_output

    assert main(["run", "-p", str(pipeline)]) == 0
    run_output = capsys.readouterr().out

    assert "RebuildWhy run: synthetic-mri-demo" in run_output
    assert "report RUN sha256:" in run_output


def test_human_error_is_readable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.yaml"

    assert main(["plan", "-p", str(missing)]) == 2
    error_output = capsys.readouterr().err

    assert "error [PIPELINE_NOT_FOUND]" in error_output
    assert str(missing) in error_output
