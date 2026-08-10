"""Immutable domain models for specifications, plans, and explanations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from rebuildwhy.canonical import canonical_json_bytes, sha256_bytes

ENGINE_SEMANTICS_VERSION = 1
PLAN_SCHEMA_VERSION = 1
PIPELINE_SCHEMA_VERSION = 1


class Decision(StrEnum):
    """A task's current or counterfactual execution decision."""

    HIT = "HIT"
    RESTORE = "RESTORE"
    RUN = "RUN"
    MAY_RUN = "MAY_RUN"
    BLOCKED = "BLOCKED"


class ReasonCode(StrEnum):
    """Stable reason codes emitted by planning and integrity checks."""

    NEW_TASK = "NEW_TASK"
    FILE_CONTENT_CHANGED = "FILE_CONTENT_CHANGED"
    CONFIG_FIELD_CHANGED = "CONFIG_FIELD_CHANGED"
    COMMAND_CHANGED = "COMMAND_CHANGED"
    ENVIRONMENT_CHANGED = "ENVIRONMENT_CHANGED"
    OUTPUT_CONTRACT_CHANGED = "OUTPUT_CONTRACT_CHANGED"
    UPSTREAM_ARTIFACT_CHANGED = "UPSTREAM_ARTIFACT_CHANGED"
    UPSTREAM_ARTIFACT_MAY_CHANGE = "UPSTREAM_ARTIFACT_MAY_CHANGE"
    ACTION_RECORD_MISSING = "ACTION_RECORD_MISSING"
    ACTION_RECORD_CORRUPT = "ACTION_RECORD_CORRUPT"
    OUTPUT_VIEW_MISSING = "OUTPUT_VIEW_MISSING"
    CACHE_MANIFEST_MISSING = "CACHE_MANIFEST_MISSING"
    CACHE_MANIFEST_CORRUPT = "CACHE_MANIFEST_CORRUPT"
    CACHE_OBJECT_MISSING = "CACHE_OBJECT_MISSING"
    CACHE_OBJECT_CORRUPT = "CACHE_OBJECT_CORRUPT"
    REQUIRED_OUTPUT_MISSING = "REQUIRED_OUTPUT_MISSING"
    NONDETERMINISTIC_OUTPUT = "NONDETERMINISTIC_OUTPUT"
    INVALID_SPEC = "INVALID_SPEC"
    MISSING_SOURCE_INPUT = "MISSING_SOURCE_INPUT"
    OUTPUT_PATH_CONFLICT = "OUTPUT_PATH_CONFLICT"


@dataclass(frozen=True, slots=True)
class CommandSpec:
    argv: tuple[str, ...]
    working_directory: str


@dataclass(frozen=True, slots=True)
class ConfigDependency:
    file: str
    pointers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArtifactDependency:
    task: str
    path: str


@dataclass(frozen=True, slots=True)
class OutputSpec:
    publish: str
    required: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaskSpec:
    task_id: str
    command: CommandSpec
    files: tuple[str, ...]
    configs: tuple[ConfigDependency, ...]
    environment: tuple[str, ...]
    artifacts: tuple[ArtifactDependency, ...]
    output: OutputSpec


@dataclass(frozen=True, slots=True)
class PipelineSpec:
    version: int
    project: str
    root: Path
    pipeline_path: Path
    tasks: dict[str, TaskSpec]


@dataclass(frozen=True, slots=True)
class ConfigOverlay:
    file: str
    pointer: str
    value: Any


@dataclass(frozen=True, slots=True)
class FileOverlay:
    file: str
    replacement: Path


@dataclass(frozen=True, slots=True)
class OverlaySet:
    configs: tuple[ConfigOverlay, ...] = ()
    files: tuple[FileOverlay, ...] = ()

    @property
    def active(self) -> bool:
        return bool(self.configs or self.files)


@dataclass(frozen=True, slots=True)
class ReasonDraft:
    task_id: str
    code: ReasonCode
    subject: str
    old_digest: str | None = None
    new_digest: str | None = None
    old_value: Any = None
    new_value: Any = None
    include_values: bool = False
    cause_keys: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        body = self._body(include_causes=True)
        return sha256_bytes(canonical_json_bytes(body))

    def _body(self, *, include_causes: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "task_id": self.task_id,
            "code": self.code.value,
            "subject": self.subject,
        }
        if self.old_digest is not None:
            body["old_digest"] = self.old_digest
        if self.new_digest is not None:
            body["new_digest"] = self.new_digest
        if self.include_values:
            body["old_value"] = self.old_value
            body["new_value"] = self.new_value
        if include_causes:
            body["cause_keys"] = sorted(self.cause_keys)
        return body

    def to_dict(self, reason_id: str, id_by_key: dict[str, str]) -> dict[str, Any]:
        body = self._body(include_causes=False)
        body["reason_id"] = reason_id
        body["caused_by"] = [id_by_key[key] for key in sorted(self.cause_keys)]
        return body


@dataclass(frozen=True, slots=True)
class TaskPlan:
    task_id: str
    decision: Decision
    baseline_action_key: str | None
    proposed_action_key: str | None
    proposed_manifest_digest: str | None
    snapshot: dict[str, Any] | None
    reason_keys: tuple[str, ...] = ()

    def to_dict(self, id_by_key: dict[str, str]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "task_id": self.task_id,
            "decision": self.decision.value,
            "reason_ids": [id_by_key[key] for key in sorted(self.reason_keys)],
        }
        if self.baseline_action_key is not None:
            result["baseline_action_key"] = self.baseline_action_key
        if self.proposed_action_key is not None:
            result["proposed_action_key"] = self.proposed_action_key
        if self.proposed_manifest_digest is not None:
            result["proposed_manifest_digest"] = self.proposed_manifest_digest
        return result


@dataclass(frozen=True, slots=True)
class PlanReport:
    pipeline: str
    mode: str
    tasks: tuple[TaskPlan, ...]
    reasons: tuple[ReasonDraft, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        unique_reasons = {reason.key: reason for reason in self.reasons}
        ordered_keys = sorted(unique_reasons)
        id_by_key = {key: f"reason-{index:04d}" for index, key in enumerate(ordered_keys, 1)}
        task_dicts = [task.to_dict(id_by_key) for task in self.tasks]
        body: dict[str, Any] = {
            "schema_version": PLAN_SCHEMA_VERSION,
            "pipeline": self.pipeline,
            "mode": self.mode,
            "affected_task_ids": [
                task.task_id for task in self.tasks if task.decision is not Decision.HIT
            ],
            "tasks": task_dicts,
            "reasons": [
                unique_reasons[key].to_dict(id_by_key[key], id_by_key) for key in ordered_keys
            ],
        }
        body["plan_id"] = sha256_bytes(canonical_json_bytes(body))
        return body


@dataclass(frozen=True, slots=True)
class RunEvent:
    task_id: str
    decision: Decision
    action_key: str
    manifest_digest: str

    def to_dict(self) -> dict[str, str]:
        return {
            "task_id": self.task_id,
            "decision": self.decision.value,
            "action_key": self.action_key,
            "manifest_digest": self.manifest_digest,
        }
