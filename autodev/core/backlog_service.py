"""Backlog service for durable change requests and dependency tracking."""

from __future__ import annotations

from typing import Any, Iterable, Optional

from autodev.core.schemas import BacklogItem, BacklogStatus, PriorityLevel, utc_now
from autodev.core.state_store import FileStateStore


class BacklogService:
    """Create, update, list, and resolve durable backlog items."""

    def __init__(self, state_store: FileStateStore) -> None:
        self.state_store = state_store

    def create_item(
        self,
        item_id: str,
        title: str,
        description: str = "",
        *,
        status: BacklogStatus = BacklogStatus.PLANNED,
        priority: PriorityLevel = PriorityLevel.MEDIUM,
        dependencies: Optional[list[str]] = None,
        acceptance_criteria: Optional[list[str]] = None,
        labels: Optional[list[str]] = None,
        source: str = "manual",
        metadata: Optional[dict[str, Any]] = None,
    ) -> BacklogItem:
        if self.exists(item_id):
            raise ValueError(f"Backlog item already exists: {item_id!r}")

        dependency_list = list(dependencies or [])
        self.validate_dependencies(item_id, dependency_list)

        item = BacklogItem(
            item_id=item_id,
            title=title,
            description=description,
            status=status,
            priority=priority,
            dependencies=dependency_list,
            acceptance_criteria=list(acceptance_criteria or []),
            labels=list(labels or []),
            source=source,
            metadata=dict(metadata or {}),
        )
        self.state_store.save_backlog_item(item)
        return item

    def get_item(self, item_id: str) -> BacklogItem:
        return self.state_store.load_backlog_item(item_id)

    def exists(self, item_id: str) -> bool:
        try:
            self.get_item(item_id)
        except FileNotFoundError:
            return False
        return True

    def list_items(
        self,
        *,
        status: Optional[BacklogStatus] = None,
        priority: Optional[PriorityLevel] = None,
    ) -> list[BacklogItem]:
        items = self.state_store.list_backlog_items()
        if status is not None:
            items = [item for item in items if item.status == status]
        if priority is not None:
            items = [item for item in items if item.priority == priority]
        return items

    def update_item(
        self,
        item_id: str,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[BacklogStatus] = None,
        priority: Optional[PriorityLevel] = None,
        dependencies: Optional[list[str]] = None,
        acceptance_criteria: Optional[list[str]] = None,
        labels: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> BacklogItem:
        current = self.get_item(item_id)
        dependency_list = list(current.dependencies if dependencies is None else dependencies)
        self.validate_dependencies(item_id, dependency_list)

        updated = current.model_copy(
            update={
                "title": current.title if title is None else title,
                "description": current.description if description is None else description,
                "status": current.status if status is None else status,
                "priority": current.priority if priority is None else priority,
                "dependencies": dependency_list,
                "acceptance_criteria": (
                    current.acceptance_criteria
                    if acceptance_criteria is None
                    else list(acceptance_criteria)
                ),
                "labels": current.labels if labels is None else list(labels),
                "metadata": current.metadata if metadata is None else dict(metadata),
                "updated_at": utc_now(),
            }
        )
        self.state_store.save_backlog_item(updated)
        return updated

    def set_status(self, item_id: str, status: BacklogStatus) -> BacklogItem:
        return self.update_item(item_id, status=status)

    def resolve_item(self, item_id: str) -> BacklogItem:
        return self.update_item(item_id, status=BacklogStatus.COMPLETED)

    def validate_dependencies(self, item_id: str, dependencies: Iterable[str]) -> None:
        dependency_list = list(dependencies)

        if len(dependency_list) != len(set(dependency_list)):
            raise ValueError(f"Duplicate dependencies are not allowed for backlog item {item_id!r}")

        if item_id in dependency_list:
            raise ValueError(f"Backlog item {item_id!r} cannot depend on itself")

        for dependency_id in dependency_list:
            if not self.exists(dependency_id):
                raise ValueError(
                    f"Backlog item {item_id!r} has unknown dependency {dependency_id!r}"
                )

        graph = {
            item.item_id: list(item.dependencies) for item in self.state_store.list_backlog_items()
        }
        graph[item_id] = dependency_list
        self._assert_no_cycles(graph)

    def _assert_no_cycles(self, graph: dict[str, list[str]]) -> None:
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError(f"Cyclic backlog dependency detected at {node!r}")
            if node in visited:
                return

            visiting.add(node)
            for dependency in graph.get(node, []):
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)
