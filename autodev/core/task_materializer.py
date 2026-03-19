"""Task materialization for eligible backlog items."""

from __future__ import annotations

from typing import Iterable, Optional

from autodev.core.backlog_service import BacklogService
from autodev.core.schemas import BacklogItem, BacklogStatus, PhaseName, PriorityLevel, TaskRecord
from autodev.core.state_store import FileStateStore


class TaskMaterializer:
    """Expand eligible backlog items into durable phase tasks."""

    DEFAULT_PHASE_SEQUENCE = [
        PhaseName.PLAN,
        PhaseName.IMPLEMENT,
        PhaseName.VALIDATE,
        PhaseName.REVIEW,
    ]

    _PRIORITY_ORDER = {
        PriorityLevel.CRITICAL: 0,
        PriorityLevel.HIGH: 1,
        PriorityLevel.MEDIUM: 2,
        PriorityLevel.LOW: 3,
    }

    def __init__(
        self,
        state_store: FileStateStore,
        backlog_service: Optional[BacklogService] = None,
        phase_sequence: Optional[list[PhaseName]] = None,
    ) -> None:
        self.state_store = state_store
        self.backlog_service = backlog_service or BacklogService(state_store)
        self.phase_sequence = list(phase_sequence or self.DEFAULT_PHASE_SEQUENCE)

    def materialize_eligible_items(self, batch_size: int = 1) -> list[TaskRecord]:
        if batch_size <= 0:
            return []

        created: list[TaskRecord] = []
        for item in self.get_eligible_items()[:batch_size]:
            new_tasks = self.materialize_item(item.item_id)
            created.extend(new_tasks)
        return created

    def materialize_item(self, item_id: str) -> list[TaskRecord]:
        item = self.backlog_service.get_item(item_id)
        if not self.is_item_eligible(item):
            return []

        existing_tasks = {
            task.task_id: task
            for task in self.state_store.list_tasks()
            if task.backlog_item_id == item.item_id
        }

        created: list[TaskRecord] = []
        for phase in self.phase_sequence:
            task_id = self.make_task_id(item.item_id, phase)
            if task_id in existing_tasks:
                continue

            task = TaskRecord(
                task_id=task_id,
                backlog_item_id=item.item_id,
                phase=phase,
                dependencies=self._task_dependencies(item.item_id, phase),
                metadata={
                    "backlog_title": item.title,
                    "backlog_priority": item.priority.value,
                    "acceptance_criteria": list(item.acceptance_criteria),
                },
            )
            self.state_store.save_task(task)
            created.append(task)

        if created and item.status != BacklogStatus.ACTIVE:
            self.backlog_service.set_status(item.item_id, BacklogStatus.ACTIVE)

        return created

    def get_eligible_items(self) -> list[BacklogItem]:
        candidates = [
            item
            for item in self.backlog_service.list_items()
            if item.status in {BacklogStatus.PLANNED, BacklogStatus.BLOCKED, BacklogStatus.ACTIVE}
        ]
        eligible = [
            item
            for item in candidates
            if self.is_item_eligible(item) and self._has_missing_phase_tasks(item.item_id)
        ]
        return sorted(
            eligible,
            key=lambda item: (
                self._PRIORITY_ORDER[item.priority],
                item.created_at,
                item.item_id,
            ),
        )

    def is_item_eligible(self, item: BacklogItem) -> bool:
        if item.status not in {BacklogStatus.PLANNED, BacklogStatus.BLOCKED, BacklogStatus.ACTIVE}:
            return False

        for dependency_id in item.dependencies:
            dependency = self.backlog_service.get_item(dependency_id)
            if dependency.status != BacklogStatus.COMPLETED:
                return False
        return True

    def make_task_id(self, item_id: str, phase: PhaseName) -> str:
        return f"{item_id}__{phase.value}"

    def _task_dependencies(self, item_id: str, phase: PhaseName) -> list[str]:
        phases = list(self.phase_sequence)
        phase_index = phases.index(phase)
        if phase_index == 0:
            return []
        previous_phase = phases[phase_index - 1]
        return [self.make_task_id(item_id, previous_phase)]

    def _has_missing_phase_tasks(self, item_id: str) -> bool:
        existing_task_ids = {
            task.task_id for task in self.state_store.list_tasks() if task.backlog_item_id == item_id
        }
        expected_task_ids = {self.make_task_id(item_id, phase) for phase in self.phase_sequence}
        return not expected_task_ids.issubset(existing_task_ids)
