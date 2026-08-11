"""Declared-input snapshots and action-key hashing."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from rebuildwhy.canonical import sha256_bytes, sha256_file, sha256_value
from rebuildwhy.errors import SpecError
from rebuildwhy.models import ENGINE_SEMANTICS_VERSION, TaskSpec
from rebuildwhy.overlays import WorkspaceView
from rebuildwhy.spec import resolve_json_pointer


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    """One canonical declared-input snapshot and its action key."""

    snapshot: dict[str, Any]
    action_key: str


def build_snapshot(
    task: TaskSpec,
    view: WorkspaceView,
    upstream: dict[tuple[str, str], dict[str, Any]],
    *,
    environment: dict[str, str] | None = None,
) -> SnapshotResult:
    """Hash every declared dependency for one task."""

    file_inputs: list[dict[str, Any]] = []
    for logical_path in task.files:
        digest, size = sha256_file(view.source_path(logical_path))
        file_inputs.append({"path": logical_path, "digest": digest, "size": size})

    config_inputs: list[dict[str, Any]] = []
    for config_dependency in task.configs:
        document = view.config_document(config_dependency.file)
        for pointer in config_dependency.pointers:
            value = resolve_json_pointer(document, pointer)
            config_inputs.append(
                {
                    "file": config_dependency.file,
                    "pointer": pointer,
                    "digest": sha256_value(value),
                    "value": value,
                }
            )

    environ = os.environ if environment is None else environment
    environment_inputs: list[dict[str, Any]] = []
    for name in task.environment:
        value = environ.get(name)
        marker = {"state": "unset"} if value is None else {"state": "set", "value": value}
        environment_inputs.append({"name": name, "digest": sha256_value(marker)})

    artifact_inputs: list[dict[str, Any]] = []
    for artifact_dependency in task.artifacts:
        key = (artifact_dependency.task, artifact_dependency.path)
        if key not in upstream:
            raise SpecError(
                "UPSTREAM_ARTIFACT_UNAVAILABLE",
                "An upstream artifact digest is not available for a concrete snapshot.",
                task_id=task.task_id,
                producer=artifact_dependency.task,
                path=artifact_dependency.path,
            )
        record = upstream[key]
        artifact_inputs.append(
            {
                "task": artifact_dependency.task,
                "path": artifact_dependency.path,
                "digest": record["digest"],
                "size": record["size"],
            }
        )

    snapshot: dict[str, Any] = {
        "engine_semantics_version": ENGINE_SEMANTICS_VERSION,
        "task_spec_version": 1,
        "task_id": task.task_id,
        "command": {
            "argv": list(task.command.argv),
            "working_directory": task.command.working_directory,
            "protocol_version": 1,
        },
        "files": file_inputs,
        "configs": config_inputs,
        "environment": environment_inputs,
        "upstream_artifacts": artifact_inputs,
        "output_contract": {
            "publish": task.output.publish,
            "required": list(task.output.required),
        },
    }
    return SnapshotResult(snapshot=snapshot, action_key=sha256_value(snapshot))


def snapshot_artifact_map(snapshot: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Index upstream artifact components from a stored snapshot."""

    return {
        (item["task"], item["path"]): {"digest": item["digest"], "size": item["size"]}
        for item in snapshot.get("upstream_artifacts", [])
    }


def absent_digest() -> str:
    """Return the stable digest used for an explicitly absent value."""

    return sha256_bytes(b"REBUILDWHY_ABSENT\0")
