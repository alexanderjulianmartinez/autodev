"""Tests for the durable backlog service."""

from __future__ import annotations

import pytest

from autodev.core.backlog_service import BacklogService
from autodev.core.schemas import BacklogStatus, PriorityLevel
from autodev.core.state_store import FileStateStore


@pytest.fixture
def backlog_service(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    return BacklogService(store)


def test_create_item_persists_independently_of_execution(backlog_service):
    item = backlog_service.create_item(
        item_id="AD-005",
        title="Introduce backlog service",
        priority=PriorityLevel.HIGH,
        acceptance_criteria=["service persists backlog items"],
    )

    assert item.status == BacklogStatus.PLANNED
    assert backlog_service.get_item("AD-005") == item
    assert backlog_service.list_items() == [item]


def test_dependency_relationships_are_stored_and_validated(backlog_service):
    parent = backlog_service.create_item(item_id="AD-001", title="Complete terminology alignment")
    child = backlog_service.create_item(
        item_id="AD-005",
        title="Introduce backlog service",
        dependencies=[parent.item_id],
        status=BacklogStatus.BLOCKED,
    )

    assert child.dependencies == ["AD-001"]
    assert backlog_service.list_items(status=BacklogStatus.BLOCKED) == [child]


def test_missing_dependency_is_rejected(backlog_service):
    with pytest.raises(ValueError, match="unknown dependency"):
        backlog_service.create_item(
            item_id="AD-005",
            title="Introduce backlog service",
            dependencies=["AD-999"],
        )


def test_duplicate_and_self_dependencies_are_rejected(backlog_service):
    backlog_service.create_item(item_id="AD-001", title="Complete terminology alignment")

    with pytest.raises(ValueError, match="Duplicate dependencies"):
        backlog_service.create_item(
            item_id="AD-005",
            title="Introduce backlog service",
            dependencies=["AD-001", "AD-001"],
        )

    with pytest.raises(ValueError, match="cannot depend on itself"):
        backlog_service.create_item(
            item_id="AD-006",
            title="Materialize tasks",
            dependencies=["AD-006"],
        )


def test_cycle_detection_rejects_invalid_updates(backlog_service):
    backlog_service.create_item(item_id="AD-001", title="Complete terminology alignment")
    backlog_service.create_item(item_id="AD-002", title="Audit scaffold", dependencies=["AD-001"])

    with pytest.raises(ValueError, match="Cyclic backlog dependency"):
        backlog_service.update_item("AD-001", dependencies=["AD-002"])


def test_update_and_resolve_item_supports_backlog_statuses(backlog_service):
    item = backlog_service.create_item(item_id="AD-005", title="Introduce backlog service")

    active = backlog_service.set_status(item.item_id, BacklogStatus.ACTIVE)
    blocked = backlog_service.set_status(item.item_id, BacklogStatus.BLOCKED)
    completed = backlog_service.resolve_item(item.item_id)

    assert active.status == BacklogStatus.ACTIVE
    assert blocked.status == BacklogStatus.BLOCKED
    assert completed.status == BacklogStatus.COMPLETED


def test_update_item_can_change_priority_and_acceptance_criteria(backlog_service):
    backlog_service.create_item(item_id="AD-005", title="Introduce backlog service")

    updated = backlog_service.update_item(
        "AD-005",
        priority=PriorityLevel.CRITICAL,
        acceptance_criteria=["dependencies are validated", "items can be resolved"],
        labels=["priority:p0", "type:core"],
    )

    assert updated.priority == PriorityLevel.CRITICAL
    assert updated.acceptance_criteria == [
        "dependencies are validated",
        "items can be resolved",
    ]
    assert updated.labels == ["priority:p0", "type:core"]
