"""Deterministic current and counterfactual causal planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rebuildwhy.cache import CacheInspection, CacheStore
from rebuildwhy.canonical import sha256_value
from rebuildwhy.graph import TaskGraph
from rebuildwhy.hashing import SnapshotResult, build_snapshot, snapshot_artifact_map
from rebuildwhy.models import (
    Decision,
    OverlaySet,
    PipelineSpec,
    PlanReport,
    ReasonCode,
    ReasonDraft,
    TaskPlan,
)
from rebuildwhy.overlays import WorkspaceView


@dataclass(frozen=True, slots=True)
class PlanningResult:
    """A public report plus internal task plans used by the executor."""

    report: PlanReport
    by_task: dict[str, TaskPlan]


class Planner:
    """Compute action decisions without running commands or mutating sources."""

    def __init__(self, pipeline: PipelineSpec, cache: CacheStore | None = None) -> None:
        self.pipeline = pipeline
        self.cache = cache or CacheStore(pipeline.root)
        self.graph = TaskGraph.from_pipeline(pipeline)

    def plan(self, overlays: OverlaySet | None = None) -> PlanningResult:
        """Plan the entire DAG in stable topological order."""

        overlay_set = overlays or OverlaySet()
        view = WorkspaceView(self.pipeline, overlay_set)
        plans: dict[str, TaskPlan] = {}
        reasons: list[ReasonDraft] = []

        for task_id in self.graph.topological_order:
            task = self.pipeline.tasks[task_id]
            baseline_inspection = self.cache.load_baseline(task_id)
            baseline = baseline_inspection.record
            old_snapshot = baseline.get("snapshot") if baseline else None
            upstream, uncertain = self._resolve_upstream(task_id, plans, old_snapshot)

            snapshot_result: SnapshotResult | None = None
            if not uncertain or old_snapshot is not None:
                snapshot_result = build_snapshot(task, view, upstream)

            task_reasons: list[ReasonDraft] = []
            direct_changes = (
                _snapshot_reasons(task_id, old_snapshot, snapshot_result.snapshot)
                if snapshot_result is not None and old_snapshot is not None
                else []
            )

            if uncertain:
                if old_snapshot is None:
                    task_reasons.append(
                        self._baseline_reason(task_id, baseline_inspection, subject=task_id)
                    )
                    decision = Decision.RUN
                else:
                    direct_only = [
                        reason
                        for reason in direct_changes
                        if reason.code is not ReasonCode.UPSTREAM_ARTIFACT_CHANGED
                    ]
                    task_reasons.extend(direct_only)
                    for producer, path in uncertain:
                        producer_plan = plans[producer]
                        task_reasons.append(
                            ReasonDraft(
                                task_id=task_id,
                                code=ReasonCode.UPSTREAM_ARTIFACT_MAY_CHANGE,
                                subject=f"{producer}:{path}",
                                cause_keys=producer_plan.reason_keys,
                            )
                        )
                    decision = Decision.RUN if direct_only else Decision.MAY_RUN
                plan = TaskPlan(
                    task_id=task_id,
                    decision=decision,
                    baseline_action_key=baseline.get("action_key") if baseline else None,
                    proposed_action_key=None,
                    proposed_manifest_digest=None,
                    snapshot=None,
                    reason_keys=tuple(reason.key for reason in task_reasons),
                )
            else:
                assert snapshot_result is not None
                candidate = self.cache.inspect_action(snapshot_result.action_key)
                candidate_record = candidate.record
                if candidate_record is not None:
                    manifest_digest = candidate_record["manifest_digest"]
                    if self.cache.output_view_valid(task, manifest_digest):
                        decision = Decision.HIT
                    else:
                        decision = Decision.RESTORE
                        task_reasons.extend(direct_changes)
                        task_reasons.append(
                            ReasonDraft(
                                task_id=task_id,
                                code=ReasonCode.OUTPUT_VIEW_MISSING,
                                subject=task.output.publish,
                            )
                        )
                    plan = TaskPlan(
                        task_id=task_id,
                        decision=decision,
                        baseline_action_key=baseline.get("action_key") if baseline else None,
                        proposed_action_key=snapshot_result.action_key,
                        proposed_manifest_digest=manifest_digest,
                        snapshot=snapshot_result.snapshot,
                        reason_keys=tuple(reason.key for reason in task_reasons),
                    )
                else:
                    task_reasons.extend(direct_changes)
                    if not task_reasons:
                        task_reasons.append(
                            self._baseline_reason(
                                task_id,
                                baseline_inspection,
                                subject=task_id,
                                candidate=candidate,
                            )
                        )
                    plan = TaskPlan(
                        task_id=task_id,
                        decision=Decision.RUN,
                        baseline_action_key=baseline.get("action_key") if baseline else None,
                        proposed_action_key=snapshot_result.action_key,
                        proposed_manifest_digest=None,
                        snapshot=snapshot_result.snapshot,
                        reason_keys=tuple(reason.key for reason in task_reasons),
                    )

            plans[task_id] = plan
            reasons.extend(task_reasons)

        report = PlanReport(
            pipeline=self.pipeline.project,
            mode="counterfactual" if overlay_set.active else "current",
            tasks=tuple(plans[task_id] for task_id in self.graph.topological_order),
            reasons=tuple(reasons),
        )
        return PlanningResult(report=report, by_task=plans)

    def _resolve_upstream(
        self,
        task_id: str,
        plans: dict[str, TaskPlan],
        old_snapshot: dict[str, Any] | None,
    ) -> tuple[dict[tuple[str, str], dict[str, Any]], list[tuple[str, str]]]:
        task = self.pipeline.tasks[task_id]
        old_artifacts = snapshot_artifact_map(old_snapshot or {})
        resolved: dict[tuple[str, str], dict[str, Any]] = {}
        uncertain: list[tuple[str, str]] = []
        for dependency in task.artifacts:
            producer_plan = plans[dependency.task]
            key = (dependency.task, dependency.path)
            if producer_plan.proposed_manifest_digest is not None:
                resolved[key] = self.cache.artifact_entry(
                    producer_plan.proposed_manifest_digest, dependency.path
                )
            else:
                uncertain.append(key)
                if key in old_artifacts:
                    resolved[key] = old_artifacts[key]
        return resolved, uncertain

    def _baseline_reason(
        self,
        task_id: str,
        baseline: CacheInspection,
        *,
        subject: str,
        candidate: CacheInspection | None = None,
    ) -> ReasonDraft:
        code: ReasonCode
        if candidate is not None and candidate.reason not in {
            None,
            ReasonCode.ACTION_RECORD_MISSING,
        }:
            code = candidate.reason
        elif (self.cache.state / f"{task_id}.json").exists() and baseline.reason is not None:
            code = baseline.reason
        else:
            code = ReasonCode.NEW_TASK
        return ReasonDraft(task_id=task_id, code=code, subject=subject)


def _snapshot_reasons(
    task_id: str,
    old: dict[str, Any],
    new: dict[str, Any],
) -> list[ReasonDraft]:
    reasons: list[ReasonDraft] = []
    if old.get("command") != new.get("command"):
        reasons.append(
            _value_reason(
                task_id,
                ReasonCode.COMMAND_CHANGED,
                "command",
                old.get("command"),
                new.get("command"),
            )
        )
    if old.get("output_contract") != new.get("output_contract"):
        reasons.append(
            _value_reason(
                task_id,
                ReasonCode.OUTPUT_CONTRACT_CHANGED,
                "output_contract",
                old.get("output_contract"),
                new.get("output_contract"),
            )
        )

    reasons.extend(
        _component_reasons(
            task_id,
            ReasonCode.FILE_CONTENT_CHANGED,
            old.get("files", []),
            new.get("files", []),
            lambda item: item["path"],
        )
    )
    reasons.extend(_config_reasons(task_id, old.get("configs", []), new.get("configs", [])))
    reasons.extend(
        _component_reasons(
            task_id,
            ReasonCode.ENVIRONMENT_CHANGED,
            old.get("environment", []),
            new.get("environment", []),
            lambda item: item["name"],
        )
    )
    reasons.extend(
        _component_reasons(
            task_id,
            ReasonCode.UPSTREAM_ARTIFACT_CHANGED,
            old.get("upstream_artifacts", []),
            new.get("upstream_artifacts", []),
            lambda item: f"{item['task']}:{item['path']}",
        )
    )
    return sorted(reasons, key=lambda reason: (reason.code.value, reason.subject))


def _component_reasons(
    task_id: str,
    code: ReasonCode,
    old_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
    locator: Any,
) -> list[ReasonDraft]:
    old_index = {locator(item): item for item in old_items}
    new_index = {locator(item): item for item in new_items}
    reasons: list[ReasonDraft] = []
    for subject in sorted(set(old_index) | set(new_index)):
        old_item = old_index.get(subject)
        new_item = new_index.get(subject)
        old_digest = old_item.get("digest") if old_item else None
        new_digest = new_item.get("digest") if new_item else None
        if old_digest != new_digest:
            reasons.append(
                ReasonDraft(
                    task_id=task_id,
                    code=code,
                    subject=subject,
                    old_digest=old_digest,
                    new_digest=new_digest,
                )
            )
    return reasons


def _config_reasons(
    task_id: str,
    old_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
) -> list[ReasonDraft]:
    def locator(item: dict[str, Any]) -> str:
        return f"{item['file']}#{item['pointer']}"

    old_index = {locator(item): item for item in old_items}
    new_index = {locator(item): item for item in new_items}
    reasons: list[ReasonDraft] = []
    for subject in sorted(set(old_index) | set(new_index)):
        old_item = old_index.get(subject)
        new_item = new_index.get(subject)
        old_digest = old_item.get("digest") if old_item else None
        new_digest = new_item.get("digest") if new_item else None
        if old_digest != new_digest:
            reasons.append(
                ReasonDraft(
                    task_id=task_id,
                    code=ReasonCode.CONFIG_FIELD_CHANGED,
                    subject=subject,
                    old_digest=old_digest,
                    new_digest=new_digest,
                    old_value=old_item.get("value") if old_item else None,
                    new_value=new_item.get("value") if new_item else None,
                    include_values=True,
                )
            )
    return reasons


def _value_reason(
    task_id: str,
    code: ReasonCode,
    subject: str,
    old_value: Any,
    new_value: Any,
) -> ReasonDraft:
    return ReasonDraft(
        task_id=task_id,
        code=code,
        subject=subject,
        old_digest=sha256_value(old_value),
        new_digest=sha256_value(new_value),
    )
