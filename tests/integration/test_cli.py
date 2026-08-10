from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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


def test_counterfactual_plan_renders_causal_chain(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pipeline = copy_demo(tmp_path)
    assert main(["run", "-p", str(pipeline)]) == 0
    capsys.readouterr()

    exit_code = main(
        [
            "plan",
            "-p",
            str(pipeline),
            "--set",
            "config/pipeline.yaml#/image/spacing=[1.0,1.0,2.0]",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "RebuildWhy plan: synthetic-mri-demo (counterfactual)" in captured.out
    assert "ingest HIT" in captured.out
    assert "resample RUN" in captured.out
    assert "normalize MAY_RUN" in captured.out
    assert "CONFIG_FIELD_CHANGED: config/pipeline.yaml#/image/spacing" in captured.out
    assert "UPSTREAM_ARTIFACT_MAY_CHANGE: resample:image.json" in captured.out


def test_irrelevant_counterfactual_field_preserves_hits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pipeline = copy_demo(tmp_path)
    assert main(["run", "-p", str(pipeline), "--json"]) == 0
    capsys.readouterr()

    exit_code = main(
        [
            "plan",
            "-p",
            str(pipeline),
            "--set",
            'config/pipeline.yaml#/notes/owner="hypothetical"',
            "--json",
        ]
    )
    captured = capsys.readouterr()
    body = json.loads(captured.out)

    assert exit_code == 0
    assert body["mode"] == "counterfactual"
    assert body["affected_task_ids"] == []
    assert [task["decision"] for task in body["tasks"]] == ["HIT"] * 5


def test_structured_json_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.yaml"

    exit_code = main(["plan", "-p", str(missing), "--json"])
    captured = capsys.readouterr()
    body = json.loads(captured.err)

    assert exit_code == 2
    assert body["error"]["code"] == "PIPELINE_NOT_FOUND"


def test_human_error_is_concise(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.yaml"

    exit_code = main(["plan", "-p", str(missing)])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert captured.err.startswith("error [PIPELINE_NOT_FOUND]:")
    assert f"path: {missing.resolve()}" in captured.err


def test_module_entrypoint_reports_version() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-m", "rebuildwhy", "--version"],
        check=False,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == "rebuildwhy 0.1.0\n"
    assert result.stderr == ""
