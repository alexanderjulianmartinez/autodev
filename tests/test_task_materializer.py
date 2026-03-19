"""Tests for durable task materialization."""

from __future__ import annotations

from autodev.core.backlog_service import BacklogService
from autodev.core.schemas import BacklogStatus, PhaseName, PriorityLevel
from autodev.core.state_store import FileStateStore
from autodev.core.task_materializer import TaskMaterializer


def build_materializer(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    backlog = BacklogService(store)
    materializer = TaskMaterializer(store, backlog)
    return store, backlog, materializer


def test_materialize_item_creates_canonical_phase_tasks(tmp_path):
    store, backlog, materializer = build_materializer(tmp_path)
    backlog.create_item(item_id="AD-006", title="Build task materializer")

    tasks = materializer.materialize_item("AD-006")

    assert [task.task_id for task in tasks] == [
        "AD-006__plan",
        "AD-006__implement",
        "AD-006__validate",
        "AD-006__review",
    ]
    assert [task.phase for task in tasks] == [
        PhaseName.PLAN,
        PhaseName.IMPLEMENT,
        PhaseName.VALIDATE,
        PhaseName.REVIEW,
    ]
    assert tasks[0].dependencies == []
    assert tasks[1].dependencies == ["AD-006__plan"]
    assert tasks[2].dependencies == ["AD-006__implement"]
    assert tasks[3].dependencies == ["AD-006__validate"]
    assert [task.task_id for task in store.list_tasks()] == [
        "AD-006__implement",
        "AD-006__plan",
        "AD-006__review",
        "AD-006__validate",
    ]
    assert backlog.get_item("AD-006").status == BacklogStatus.ACTIVE


def test_materialization_respects_backlog_dependencies(tmp_path):
    _store, backlog, materializer = build_materializer(tmp_path)
    backlog.create_item(item_id="AD-001", title="Complete terminology alignment")
    backlog.create_item(
        item_id="AD-006",
        title="Build task materializer",
        dependencies=["AD-001"],
        status=BacklogStatus.BLOCKED,
    )

    assert materializer.materialize_item("AD-006") == []

    backlog.resolve_item("AD-001")
    tasks = materializer.materialize_eligible_items()

    assert [task.task_id for task in tasks] == [
        "AD-006__plan",
        "AD-006__implement",
        "AD-006__validate",
        "AD-006__review",
    ]


def test_materialize_eligible_items_respects_bounded_batch_and_priority(tmp_path):
    _store, backlog, materializer = build_materializer(tmp_path)
    backlog.create_item(item_id="AD-low", title="Low priority", priority=PriorityLevel.LOW)
    backlog.create_item(item_id="AD-high", title="High priority", priority=PriorityLevel.HIGH)

    first_batch = materializer.materialize_eligible_items(batch_size=1)
    second_batch = materializer.materialize_eligible_items(batch_size=1)

    assert [task.task_id for task in first_batch] == [
        "AD-high__plan",
        "AD-high__implement",
        "AD-high__validate",
        "AD-high__review",
    ]
    assert [task.task_id for task in second_batch] == [
        "AD-low__plan",
        "AD-low__implement",
        "AD-low__validate",
        "AD-low__review",
    ]


def test_duplicate_task_generation_is_prevented(tmp_path):
    store, backlog, materializer = build_materializer(tmp_path)
    backlog.create_item(item_id="AD-006", title="Build task materializer")

    first = materializer.materialize_item("AD-006")
    second = materializer.materialize_item("AD-006")

    assert len(first) == 4
    assert second == []
    assert [task.task_id for task in store.list_tasks()] == [
        "AD-006__implement",
        "AD-006__plan",
        "AD-006__review",
        "AD-006__validate",
    ]


def test_existing_partial_task_set_only_materializes_missing_phases(tmp_path):
    store, backlog, materializer = build_materializer(tmp_path)
    backlog.create_item(item_id="AD-006", title="Build task materializer")
    initial = materializer.materialize_item("AD-006")
    assert len(initial) == 4

    plan_task = store.load_task("AD-006__plan")
    implement_task = store.load_task("AD-006__implement")
    store.tasks_dir.joinpath("AD-006__validate.json").unlink()
    store.tasks_dir.joinpath("AD-006__review.json").unlink()

    rematerialized = materializer.materialize_item("AD-006")

    assert plan_task == store.load_task("AD-006__plan")
    assert implement_task == store.load_task("AD-006__implement")
    assert [task.task_id for task in rematerialized] == [
        "AD-006__validate",
        "AD-006__review",
    ]
