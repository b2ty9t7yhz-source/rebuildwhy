"""Output validation and canonical artifact manifests."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

from rebuildwhy.canonical import sha256_file
from rebuildwhy.errors import ExecutionError
from rebuildwhy.models import TaskSpec


def build_manifest(task: TaskSpec, output_directory: Path) -> dict[str, Any]:
    """Validate a staging output tree and describe all regular files."""

    if not output_directory.is_dir() or output_directory.is_symlink():
        raise ExecutionError(
            "REQUIRED_OUTPUT_MISSING",
            "The task did not create its staging output directory.",
            task_id=task.task_id,
        )

    entries: list[dict[str, Any]] = []
    discovered: set[str] = set()
    for path in sorted(output_directory.rglob("*")):
        metadata = path.lstat()
        relative = path.relative_to(output_directory).as_posix()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ExecutionError(
                "UNSUPPORTED_OUTPUT_TYPE",
                "Task outputs may contain only regular files and directories.",
                task_id=task.task_id,
                path=relative,
            )
        digest, size = sha256_file(path)
        entries.append(
            {
                "path": relative,
                "digest": digest,
                "size": size,
                "executable": bool(metadata.st_mode & 0o111),
            }
        )
        discovered.add(relative)

    missing = sorted(set(task.output.required) - discovered)
    if missing:
        raise ExecutionError(
            "REQUIRED_OUTPUT_MISSING",
            "The task did not produce every required output file.",
            task_id=task.task_id,
            missing=missing,
        )
    return {"schema_version": 1, "files": entries}
