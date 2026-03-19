"""TaskGraph: DAG-based workflow engine."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from autodev.core.schemas import (
    FailureClass,
    FailureDetail,
    PhaseName,
    PriorityLevel,
    RetryHistoryEntry,
    TaskRecord,
    TaskStatus,
    utc_now,
)
from autodev.core.state_store import FileStateStore


@dataclass
class TaskNode:
    """A single node in the task execution graph."""

    name: str
    agent_type: str
    dependencies: list[str] = field(default_factory=list)
    input_context: dict[str, Any] = field(default_factory=dict)
    output_context: dict[str, Any] = field(default_factory=dict)


class TaskGraph:
    """Directed acyclic graph of tasks.

    Nodes represent pipeline stages; edges encode execution order.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, TaskNode] = {}
        self._edges: dict[str, list[str]] = {}  # node -> list of successors

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def add_node(self, node: TaskNode) -> None:
        """Register a task node."""
        self._nodes[node.name] = node
        if node.name not in self._edges:
            self._edges[node.name] = []

    def add_edge(self, from_node: str, to_node: str) -> None:
        """Add a directed edge from_node → to_node."""
        if from_node not in self._nodes:
            raise ValueError(f"Unknown node: {from_node!r}")
        if to_node not in self._nodes:
            raise ValueError(f"Unknown node: {to_node!r}")
        if to_node not in self._edges[from_node]:
            self._edges[from_node].append(to_node)

    # ------------------------------------------------------------------
    # Execution ordering (topological sort — Kahn's algorithm)
    # ------------------------------------------------------------------

    def get_execution_order(self) -> list[str]:
        """Return node names in topological order.

        Raises ValueError if a cycle is detected.
        """
        in_degree: dict[str, int] = {n: 0 for n in self._nodes}
        for _src, successors in self._edges.items():
            for dst in successors:
                in_degree[dst] += 1

        queue: deque[str] = deque(n for n, d in in_degree.items() if d == 0)
        order: list[str] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for successor in self._edges.get(node, []):
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    queue.append(successor)

        if len(order) != len(self._nodes):
            raise ValueError("Cycle detected in task graph")

        return order

    # ------------------------------------------------------------------
    # Convenience factory
    # ------------------------------------------------------------------

    @classmethod
    def default_pipeline(cls) -> "TaskGraph":
        """Return the standard plan → implement → validate → review pipeline."""
        graph = cls()
        for name, agent in [
            ("plan", "planner"),
            ("implement", "implementer"),
            ("validate", "validator"),
            ("review", "reviewer"),
        ]:
            graph.add_node(TaskNode(name=name, agent_type=agent))

        graph.add_edge("plan", "implement")
        graph.add_edge("implement", "validate")
        graph.add_edge("validate", "review")
        return graph

    @property
    def nodes(self) -> dict[str, TaskNode]:
        return dict(self._nodes)


class TaskScheduler:
    """Validate and schedule durable task records deterministically."""

    _PHASE_ORDER = {
        PhaseName.PLAN.value: 0,
        PhaseName.IMPLEMENT.value: 1,
        PhaseName.VALIDATE.value: 2,
        PhaseName.REVIEW.value: 3,
        PhaseName.PROMOTE.value: 4,
    }
    _PRIORITY_ORDER = {
        PriorityLevel.CRITICAL.value: 0,
        PriorityLevel.HIGH.value: 1,
        PriorityLevel.MEDIUM.value: 2,
        PriorityLevel.LOW.value: 3,
    }

    def __init__(
        self, tasks: list[TaskRecord], state_store: Optional[FileStateStore] = None
    ) -> None:
        self._tasks = list(tasks)
        self._state_store = state_store

    @property
    def tasks(self) -> list[TaskRecord]:
        return list(self._tasks)

    def validate(self) -> None:
        task_ids = [task.task_id for task in self._tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Duplicate task IDs are not allowed")

        task_map = {task.task_id: task for task in self._tasks}
        for task in self._tasks:
            for dependency_id in task.dependencies:
                if dependency_id not in task_map:
                    raise ValueError(
                        f"Task {task.task_id!r} has missing dependency {dependency_id!r}"
                    )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ValueError(f"Cycle detected in task graph at {task_id!r}")
            if task_id in visited:
                return

            visiting.add(task_id)
            for dependency_id in task_map[task_id].dependencies:
                visit(dependency_id)
            visiting.remove(task_id)
            visited.add(task_id)

        for task in self._tasks:
            visit(task.task_id)

    def get_runnable_tasks(self, now: Optional[datetime] = None) -> list[TaskRecord]:
        self.validate()
        current_time = now or utc_now()

        task_map = {task.task_id: task for task in self._tasks}
        runnable: list[TaskRecord] = []
        for task in self._tasks:
            if task.status != TaskStatus.PENDING:
                continue
            if task.next_eligible_at is not None and task.next_eligible_at > current_time:
                continue
            if all(
                task_map[dependency_id].status == TaskStatus.COMPLETED
                for dependency_id in task.dependencies
            ):
                runnable.append(task)

        return sorted(runnable, key=self._sort_key)

    def choose_next_task(self, now: Optional[datetime] = None) -> Optional[TaskRecord]:
        runnable = self.get_runnable_tasks(now=now)
        if not runnable:
            return None
        return runnable[0]

    def record_failure(
        self,
        task_id: str,
        failure: FailureDetail,
        *,
        now: Optional[datetime] = None,
        backoff_base_seconds: int = 60,
    ) -> TaskRecord:
        current_time = now or utc_now()
        task = self._get_task(task_id)
        attempt_number = len(task.retry_history) + 1

        should_retry = (
            failure.failure_class == FailureClass.RETRYABLE and task.retry_count < task.max_retries
        )

        if should_retry:
            next_retry_count = task.retry_count + 1
            delay_seconds = backoff_base_seconds * (2 ** (next_retry_count - 1))
            next_eligible_at = current_time + timedelta(seconds=delay_seconds)
            status = TaskStatus.PENDING
        else:
            next_retry_count = task.retry_count
            delay_seconds = None
            next_eligible_at = None
            status = TaskStatus.BLOCKED

        history_entry = RetryHistoryEntry(
            attempt_number=attempt_number,
            attempted_at=current_time,
            failure_class=failure.failure_class,
            message=failure.message,
            retry_scheduled=should_retry,
            scheduled_for=next_eligible_at,
            delay_seconds=delay_seconds,
        )

        updated = task.model_copy(
            update={
                "status": status,
                "retry_count": next_retry_count,
                "next_eligible_at": next_eligible_at,
                "retry_history": [*task.retry_history, history_entry],
                "last_failure": failure,
                "updated_at": current_time,
            }
        )
        self._replace_task(updated)
        self._persist_scheduler_state(
            current_time,
            {
                "event": "task_failure_recorded",
                "task_id": task_id,
                "failure_class": failure.failure_class.value,
                "retry_scheduled": should_retry,
                "retry_count": updated.retry_count,
                "scheduled_for": next_eligible_at.isoformat() if next_eligible_at else None,
            },
        )
        return updated

    def reset_task_for_new_attempt(
        self,
        task_id: str,
        *,
        now: Optional[datetime] = None,
    ) -> TaskRecord:
        current_time = now or utc_now()
        task = self._get_task(task_id)
        updated = task.model_copy(
            update={
                "status": TaskStatus.PENDING,
                "next_eligible_at": None,
                "last_failure": None,
                "updated_at": current_time,
            }
        )
        self._replace_task(updated)
        self._persist_scheduler_state(
            current_time,
            {"event": "task_reset_for_new_attempt", "task_id": task_id},
        )
        return updated

    def _sort_key(self, task: TaskRecord) -> tuple[int, int, Any, str]:
        priority_value = str(task.metadata.get("backlog_priority", PriorityLevel.MEDIUM.value))
        phase_value = task.phase.value if isinstance(task.phase, PhaseName) else str(task.phase)
        return (
            self._PRIORITY_ORDER.get(
                priority_value, self._PRIORITY_ORDER[PriorityLevel.MEDIUM.value]
            ),
            self._PHASE_ORDER.get(phase_value, 99),
            task.created_at,
            task.task_id,
        )

    def _get_task(self, task_id: str) -> TaskRecord:
        for task in self._tasks:
            if task.task_id == task_id:
                return task
        raise ValueError(f"Unknown task ID: {task_id!r}")

    def _replace_task(self, updated: TaskRecord) -> None:
        for index, task in enumerate(self._tasks):
            if task.task_id == updated.task_id:
                self._tasks[index] = updated
                if self._state_store is not None:
                    self._state_store.save_task(updated)
                return
        raise ValueError(f"Unknown task ID: {updated.task_id!r}")

    def _persist_scheduler_state(self, current_time: datetime, event: dict[str, Any]) -> None:
        if self._state_store is None:
            return

        scheduler_state = {
            "generated_at": current_time.isoformat(),
            "tasks": [
                {
                    "task_id": task.task_id,
                    "status": task.status.value,
                    "retry_count": task.retry_count,
                    "max_retries": task.max_retries,
                    "next_eligible_at": (
                        task.next_eligible_at.isoformat() if task.next_eligible_at else None
                    ),
                    "last_failure_class": (
                        task.last_failure.failure_class.value if task.last_failure else None
                    ),
                    "retry_history": [
                        entry.model_dump(mode="json") for entry in task.retry_history
                    ],
                }
                for task in self._tasks
            ],
        }
        self._state_store.save_scheduler_state(scheduler_state)
        history_event = dict(event)
        history_event["recorded_at"] = current_time.isoformat()
        self._state_store.append_scheduler_history(history_event)
