"""Task graph validation and deterministic traversal."""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from rebuildwhy.errors import SpecError
from rebuildwhy.models import PipelineSpec


@dataclass(frozen=True, slots=True)
class TaskGraph:
    """A validated artifact dependency graph."""

    dependencies: dict[str, tuple[str, ...]]
    consumers: dict[str, tuple[str, ...]]
    topological_order: tuple[str, ...]

    @classmethod
    def from_pipeline(cls, pipeline: PipelineSpec) -> TaskGraph:
        task_ids = set(pipeline.tasks)
        dependency_sets: dict[str, set[str]] = {task_id: set() for task_id in task_ids}
        consumer_sets: dict[str, set[str]] = {task_id: set() for task_id in task_ids}

        for task in pipeline.tasks.values():
            for artifact in task.artifacts:
                if artifact.task not in task_ids:
                    raise SpecError(
                        "MISSING_TASK_DEPENDENCY",
                        "An artifact dependency references an unknown task.",
                        task_id=task.task_id,
                        dependency=artifact.task,
                    )
                if artifact.task == task.task_id:
                    raise SpecError(
                        "SELF_DEPENDENCY",
                        "A task cannot consume its own output artifact.",
                        task_id=task.task_id,
                    )
                producer = pipeline.tasks[artifact.task]
                if artifact.path not in producer.output.required:
                    raise SpecError(
                        "UNDECLARED_ARTIFACT",
                        "An artifact dependency must reference a required producer output.",
                        task_id=task.task_id,
                        producer=artifact.task,
                        artifact_path=artifact.path,
                    )
                dependency_sets[task.task_id].add(artifact.task)
                consumer_sets[artifact.task].add(task.task_id)

        dependencies = {
            task_id: tuple(sorted(values)) for task_id, values in dependency_sets.items()
        }
        consumers = {task_id: tuple(sorted(values)) for task_id, values in consumer_sets.items()}
        order = _topological_order(dependencies, consumers)
        return cls(dependencies=dependencies, consumers=consumers, topological_order=order)

    def affected_descendants(self, seeds: set[str]) -> tuple[str, ...]:
        """Return seeds and every reachable consumer in topological order."""

        affected = set(seeds)
        queue = list(sorted(seeds))
        while queue:
            producer = queue.pop(0)
            for consumer in self.consumers[producer]:
                if consumer not in affected:
                    affected.add(consumer)
                    queue.append(consumer)
        return tuple(task_id for task_id in self.topological_order if task_id in affected)


def _topological_order(
    dependencies: dict[str, tuple[str, ...]], consumers: dict[str, tuple[str, ...]]
) -> tuple[str, ...]:
    indegree = {task_id: len(values) for task_id, values in dependencies.items()}
    ready = [task_id for task_id, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    order: list[str] = []

    while ready:
        task_id = heapq.heappop(ready)
        order.append(task_id)
        for consumer in consumers[task_id]:
            indegree[consumer] -= 1
            if indegree[consumer] == 0:
                heapq.heappush(ready, consumer)

    if len(order) != len(dependencies):
        cycle_nodes = sorted(task_id for task_id, degree in indegree.items() if degree > 0)
        raise SpecError(
            "PIPELINE_CYCLE",
            "The task graph contains at least one cycle.",
            tasks=cycle_nodes,
        )
    return tuple(order)
