from __future__ import annotations

import json
import shutil
from pathlib import Path

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


def test_plan_json_is_machine_readable(tmp_path: Path, capsys: object) -> None:
    pipeline = copy_demo(tmp_path)

    exit_code = main(["plan", "-p", str(pipeline), "--json"])
    captured = capsys.readouterr()  # type: ignore[attr-defined]
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


def test_structured_json_error(tmp_path: Path, capsys: object) -> None:
    missing = tmp_path / "missing.yaml"

    exit_code = main(["plan", "-p", str(missing), "--json"])
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    body = json.loads(captured.err)

    assert exit_code == 2
    assert body["error"]["code"] == "PIPELINE_NOT_FOUND"
