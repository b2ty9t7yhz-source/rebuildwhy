"""Trusted sequential task execution and atomic publication."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rebuildwhy.cache import CacheStore
from rebuildwhy.canonical import atomic_write_json, canonical_json_bytes, sha256_bytes
from rebuildwhy.errors import ExecutionError, SpecError
from rebuildwhy.graph import TaskGraph
from rebuildwhy.models import Decision, PipelineSpec, RunEvent, TaskPlan
from rebuildwhy.overlays import WorkspaceView
from rebuildwhy.planner import Planner
from rebuildwhy.publication import build_manifest


@dataclass(frozen=True, slots=True)
class RunReport:
    """Stable summary of an execution request."""

    pipeline: str
    events: tuple[RunEvent, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "pipeline": self.pipeline,
            "events": [event.to_dict() for event in self.events],
        }


class Executor:
    """Refine plans topologically and execute only verified cache misses."""

    def __init__(self, pipeline: PipelineSpec, cache: CacheStore | None = None) -> None:
        self.pipeline = pipeline
        self.cache = cache or CacheStore(pipeline.root)
        self.graph = TaskGraph.from_pipeline(pipeline)
        self.planner = Planner(pipeline, self.cache)

    def run(self, *, check_determinism: bool = False) -> RunReport:
        """Bring every task to a complete published state."""

        events: list[RunEvent] = []
        for task_id in self.graph.topological_order:
            plan = self.planner.plan().by_task[task_id]
            events.append(self._settle(plan, check_determinism=check_determinism))
        return RunReport(self.pipeline.project, tuple(events))

    def verify_determinism(self, task_id: str) -> RunReport:
        """Execute one task twice after materializing all of its ancestors."""

        if task_id not in self.pipeline.tasks:
            raise SpecError(
                "UNKNOWN_TASK",
                "The requested determinism-check task does not exist.",
                task_id=task_id,
            )
        ancestors = self._ancestors(task_id)
        events: list[RunEvent] = []
        for candidate in self.graph.topological_order:
            if candidate in ancestors:
                plan = self.planner.plan().by_task[candidate]
                events.append(self._settle(plan, check_determinism=False))
        plan = self.planner.plan().by_task[task_id]
        if plan.snapshot is None or plan.proposed_action_key is None:
            raise ExecutionError(
                "UNRESOLVED_PLAN",
                "The task could not be resolved after its ancestors completed.",
                task_id=task_id,
            )
        events.append(self._execute(plan, check_determinism=True))
        return RunReport(self.pipeline.project, tuple(events))

    def _settle(self, plan: TaskPlan, *, check_determinism: bool) -> RunEvent:
        task = self.pipeline.tasks[plan.task_id]
        if plan.decision is Decision.HIT:
            assert plan.proposed_action_key is not None
            assert plan.proposed_manifest_digest is not None
            return RunEvent(
                task_id=plan.task_id,
                decision=Decision.HIT,
                action_key=plan.proposed_action_key,
                manifest_digest=plan.proposed_manifest_digest,
            )
        if plan.decision is Decision.RESTORE:
            assert plan.proposed_action_key is not None
            inspection = self.cache.inspect_action(plan.proposed_action_key)
            record = inspection.record
            if record is None:
                raise ExecutionError(
                    "CACHE_CHANGED_DURING_RUN",
                    "A cache entry became invalid after planning.",
                    task_id=plan.task_id,
                    action_key=plan.proposed_action_key,
                )
            self.cache.restore(task, record)
            return RunEvent(
                task_id=plan.task_id,
                decision=Decision.RESTORE,
                action_key=plan.proposed_action_key,
                manifest_digest=record["manifest_digest"],
            )
        if plan.decision is not Decision.RUN:
            raise ExecutionError(
                "UNRESOLVED_PLAN",
                "A task remained conditionally unresolved when execution reached it.",
                task_id=plan.task_id,
                decision=plan.decision.value,
            )
        return self._execute(plan, check_determinism=check_determinism)

    def _execute(self, plan: TaskPlan, *, check_determinism: bool) -> RunEvent:
        if plan.snapshot is None or plan.proposed_action_key is None:
            raise ExecutionError(
                "UNRESOLVED_PLAN",
                "A runnable task has no concrete action snapshot.",
                task_id=plan.task_id,
            )
        task = self.pipeline.tasks[plan.task_id]
        staging_directories: list[Path] = []
        try:
            first_staging, first_output, first_manifest = self._run_once(plan)
            staging_directories.append(first_staging)
            first_digest = sha256_bytes(canonical_json_bytes(first_manifest))
            if check_determinism:
                second_staging, _, second_manifest = self._run_once(plan)
                staging_directories.append(second_staging)
                second_digest = sha256_bytes(canonical_json_bytes(second_manifest))
                if first_digest != second_digest:
                    raise ExecutionError(
                        "NONDETERMINISTIC_OUTPUT",
                        "Two isolated executions produced different artifact manifests.",
                        task_id=task.task_id,
                        first_manifest_digest=first_digest,
                        second_manifest_digest=second_digest,
                    )

            existing = self.cache.inspect_action(plan.proposed_action_key)
            existing_record = existing.record
            if existing_record is not None and existing_record["manifest_digest"] != first_digest:
                raise ExecutionError(
                    "NONDETERMINISTIC_OUTPUT",
                    "This action key previously produced a different artifact manifest.",
                    task_id=task.task_id,
                    previous_manifest_digest=existing_record["manifest_digest"],
                    new_manifest_digest=first_digest,
                )

            record = self.cache.write_bundle(
                task=task,
                action_key=plan.proposed_action_key,
                snapshot=plan.snapshot,
                staging_output=first_output,
                manifest=first_manifest,
            )
            self.cache.publish(task, record)
            return RunEvent(
                task_id=task.task_id,
                decision=Decision.RUN,
                action_key=plan.proposed_action_key,
                manifest_digest=record["manifest_digest"],
            )
        finally:
            for directory in staging_directories:
                shutil.rmtree(directory, ignore_errors=True)

    def _run_once(self, plan: TaskPlan) -> tuple[Path, Path, dict[str, Any]]:
        task = self.pipeline.tasks[plan.task_id]
        staging = self.cache.new_staging_directory(task.task_id)
        try:
            output = staging / "output"
            output.mkdir()
            context_path = staging / "context.json"
            context = self._execution_context(plan, output)
            atomic_write_json(context_path, context)
            environment = os.environ.copy()
            environment["REBUILDWHY_CONTEXT"] = str(context_path)
            working_directory = (self.pipeline.root / task.command.working_directory).resolve()
            try:
                working_directory.relative_to(self.pipeline.root)
            except ValueError as error:
                raise ExecutionError(
                    "WORKING_DIRECTORY_ESCAPE",
                    "The task working directory escapes the project root.",
                    task_id=task.task_id,
                ) from error
            if not working_directory.is_dir():
                raise ExecutionError(
                    "WORKING_DIRECTORY_MISSING",
                    "The task working directory does not exist.",
                    task_id=task.task_id,
                    path=str(working_directory),
                )
            try:
                result = subprocess.run(
                    list(task.command.argv),
                    cwd=working_directory,
                    env=environment,
                    shell=False,
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except OSError as error:
                raise ExecutionError(
                    "COMMAND_START_FAILED",
                    "The trusted task command could not be started.",
                    task_id=task.task_id,
                    command=list(task.command.argv),
                ) from error
            if result.returncode != 0:
                raise ExecutionError(
                    "COMMAND_FAILED",
                    "The trusted task command returned a non-zero status.",
                    task_id=task.task_id,
                    return_code=result.returncode,
                    stdout=result.stdout[-4000:],
                    stderr=result.stderr[-4000:],
                )
            return staging, output, build_manifest(task, output)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _execution_context(self, plan: TaskPlan, output: Path) -> dict[str, Any]:
        task = self.pipeline.tasks[plan.task_id]
        snapshot = plan.snapshot
        if snapshot is None:
            raise ExecutionError(
                "UNRESOLVED_PLAN",
                "A task execution context requires a concrete snapshot.",
                task_id=plan.task_id,
            )
        view = WorkspaceView(self.pipeline)
        files = {logical: str(view.source_path(logical).resolve()) for logical in task.files}
        configs = {
            f"{item['file']}#{item['pointer']}": item["value"] for item in snapshot["configs"]
        }
        artifacts: dict[str, str] = {}
        for dependency in task.artifacts:
            producer = self.cache.load_baseline(dependency.task)
            producer_record = producer.record
            if producer_record is None:
                raise ExecutionError(
                    "UPSTREAM_ARTIFACT_UNAVAILABLE",
                    "A required upstream artifact is not published and verified.",
                    task_id=task.task_id,
                    producer=dependency.task,
                    path=dependency.path,
                )
            producer_record = producer.record
            assert producer_record is not None
            artifacts[f"{dependency.task}:{dependency.path}"] = str(
                self.cache.artifact_path(producer_record["manifest_digest"]) / dependency.path
            )
        return {
            "schema_version": 1,
            "task_id": task.task_id,
            "project_root": str(self.pipeline.root),
            "output_directory": str(output),
            "files": files,
            "configs": configs,
            "artifacts": artifacts,
        }

    def _ancestors(self, task_id: str) -> set[str]:
        result: set[str] = set()
        queue = list(self.graph.dependencies[task_id])
        while queue:
            candidate = queue.pop()
            if candidate not in result:
                result.add(candidate)
                queue.extend(self.graph.dependencies[candidate])
        return result
