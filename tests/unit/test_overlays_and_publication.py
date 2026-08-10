from __future__ import annotations

from pathlib import Path

import pytest

from rebuildwhy.errors import ExecutionError
from rebuildwhy.models import (
    CommandSpec,
    OutputSpec,
    TaskSpec,
)
from rebuildwhy.publication import build_manifest


def task() -> TaskSpec:
    return TaskSpec(
        task_id="example",
        command=CommandSpec(("python3", "task.py"), "."),
        files=(),
        configs=(),
        environment=(),
        artifacts=(),
        output=OutputSpec("outputs/example", ("result.txt",)),
    )


def test_manifest_is_sorted_and_records_executable_bit(tmp_path: Path) -> None:
    (tmp_path / "z.txt").write_text("z", encoding="utf-8")
    executable = tmp_path / "result.txt"
    executable.write_text("result", encoding="utf-8")
    executable.chmod(0o755)

    manifest = build_manifest(task(), tmp_path)

    assert [entry["path"] for entry in manifest["files"]] == ["result.txt", "z.txt"]
    assert manifest["files"][0]["executable"] is True


def test_manifest_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("data", encoding="utf-8")
    (tmp_path / "result.txt").symlink_to(target)

    with pytest.raises(ExecutionError) as caught:
        build_manifest(task(), tmp_path)

    assert caught.value.code == "UNSUPPORTED_OUTPUT_TYPE"


def test_manifest_requires_declared_output(tmp_path: Path) -> None:
    (tmp_path / "other.txt").write_text("data", encoding="utf-8")

    with pytest.raises(ExecutionError) as caught:
        build_manifest(task(), tmp_path)

    assert caught.value.code == "REQUIRED_OUTPUT_MISSING"


def test_output_root_must_be_directory(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ExecutionError):
        build_manifest(task(), output)
