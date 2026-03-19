"""Tests for deterministic task scheduling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from autodev.core.schemas import FailureClass, FailureDetail, PhaseName, TaskRecord, TaskStatus
from autodev.core.state_store import FileStateStore
from autodev.core.task_graph import TaskScheduler


def make_task(
    task_id: str,
    phase: PhaseName,
    *,
    status: TaskStatus = TaskStatus.PENDING,
    dependencies: Optional[list[str]] = None,
    backlog_item_id: str = "AD-007",
    backlog_priority: str = "medium",
    max_retries: int = 0,
) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        backlog_item_id=backlog_item_id,
        phase=phase,
        status=status,
        dependencies=list(dependencies or []),
        max_retries=max_retries,
        metadata={"backlog_priority": backlog_priority},
    )


def test_validate_rejects_duplicate_task_ids():
    scheduler = TaskScheduler(
        [
            make_task("AD-007__plan", PhaseName.PLAN),
            make_task("AD-007__plan", PhaseName.IMPLEMENT),
        ]
    )

    try:
        scheduler.validate()
    except ValueError as exc:
        assert "Duplicate task IDs" in str(exc)
    else:
        raise AssertionError("Expected duplicate task ID validation to fail")


def test_validate_rejects_missing_dependencies():
    scheduler = TaskScheduler(
        [
            make_task(
                "AD-007__implement",
                PhaseName.IMPLEMENT,
                dependencies=["AD-007__plan"],
            )
        ]
    )

    try:
        scheduler.validate()
    except ValueError as exc:
        assert "missing dependency" in str(exc)
    else:
        raise AssertionError("Expected missing dependency validation to fail")


def test_validate_rejects_cycles():
    scheduler = TaskScheduler(
        [
            make_task("AD-007__plan", PhaseName.PLAN, dependencies=["AD-007__review"]),
            make_task("AD-007__review", PhaseName.REVIEW, dependencies=["AD-007__plan"]),
        ]
    )

    try:
        scheduler.validate()
    except ValueError as exc:
        assert "Cycle detected" in str(exc)
    else:
        raise AssertionError("Expected cyclic dependency validation to fail")


def test_runnable_tasks_come_from_completion_state_not_timestamps():
    scheduler = TaskScheduler(
        [
            make_task("AD-007__plan", PhaseName.PLAN, status=TaskStatus.COMPLETED),
            make_task(
                "AD-007__implement",
                PhaseName.IMPLEMENT,
                dependencies=["AD-007__plan"],
                status=TaskStatus.PENDING,
            ),
            make_task(
                "AD-007__validate",
                PhaseName.VALIDATE,
                dependencies=["AD-007__implement"],
                status=TaskStatus.PENDING,
            ),
        ]
    )

    runnable = scheduler.get_runnable_tasks()

    assert [task.task_id for task in runnable] == ["AD-007__implement"]


def test_choose_next_task_uses_deterministic_tie_break_rule():
    scheduler = TaskScheduler(
        [
            make_task(
                "AD-200__plan",
                PhaseName.PLAN,
                backlog_item_id="AD-200",
                backlog_priority="medium",
            ),
            make_task(
                "AD-100__plan",
                PhaseName.PLAN,
                backlog_item_id="AD-100",
                backlog_priority="high",
            ),
            make_task(
                "AD-050__implement",
                PhaseName.IMPLEMENT,
                backlog_item_id="AD-050",
                backlog_priority="high",
            ),
            make_task(
                "AD-300__plan",
                PhaseName.PLAN,
                backlog_item_id="AD-300",
                backlog_priority="high",
            ),
        ]
    )

    runnable = scheduler.get_runnable_tasks()

    assert [task.task_id for task in runnable] == [
        "AD-100__plan",
        "AD-300__plan",
        "AD-050__implement",
        "AD-200__plan",
    ]
    assert scheduler.choose_next_task() == runnable[0]


def test_retryable_failure_uses_bounded_backoff_and_becomes_runnable_when_due(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    now = datetime(2026, 3, 18, 16, 0, tzinfo=timezone.utc)
    task = make_task("AD-008__validate", PhaseName.VALIDATE, max_retries=2)
    store.save_task(task)
    scheduler = TaskScheduler([task], state_store=store)

    updated = scheduler.record_failure(
        task.task_id,
        FailureDetail(failure_class=FailureClass.RETRYABLE, message="Transient network failure"),
        now=now,
        backoff_base_seconds=30,
    )

    assert updated.status == TaskStatus.PENDING
    assert updated.retry_count == 1
    assert updated.next_eligible_at == now + timedelta(seconds=30)
    assert updated.retry_history[-1].retry_scheduled is True
    assert scheduler.get_runnable_tasks(now=now) == []
    assert [
        task.task_id for task in scheduler.get_runnable_tasks(now=now + timedelta(seconds=30))
    ] == ["AD-008__validate"]


def test_exhausted_retryable_failure_becomes_blocked(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    now = datetime(2026, 3, 18, 16, 30, tzinfo=timezone.utc)
    task = make_task("AD-008__validate", PhaseName.VALIDATE, max_retries=1)
    store.save_task(task)
    scheduler = TaskScheduler([task], state_store=store)

    first = scheduler.record_failure(
        task.task_id,
        FailureDetail(failure_class=FailureClass.RETRYABLE, message="Temporary failure"),
        now=now,
        backoff_base_seconds=10,
    )
    second = scheduler.record_failure(
        task.task_id,
        FailureDetail(failure_class=FailureClass.RETRYABLE, message="Temporary failure again"),
        now=now + timedelta(seconds=10),
        backoff_base_seconds=10,
    )

    assert first.status == TaskStatus.PENDING
    assert second.status == TaskStatus.BLOCKED
    assert second.retry_count == 1
    assert second.retry_history[-1].retry_scheduled is False


def test_non_retryable_failure_remains_blocked_until_reset(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    now = datetime(2026, 3, 18, 17, 0, tzinfo=timezone.utc)
    task = make_task("AD-008__validate", PhaseName.VALIDATE, max_retries=3)
    store.save_task(task)
    scheduler = TaskScheduler([task], state_store=store)

    blocked = scheduler.record_failure(
        task.task_id,
        FailureDetail(
            failure_class=FailureClass.VALIDATION_FAILURE,
            message="Targeted validation failed",
        ),
        now=now,
        backoff_base_seconds=15,
    )

    assert blocked.status == TaskStatus.BLOCKED
    assert blocked.next_eligible_at is None
    assert scheduler.get_runnable_tasks(now=now + timedelta(minutes=5)) == []

    reset = scheduler.reset_task_for_new_attempt(task.task_id, now=now + timedelta(minutes=6))

    assert reset.status == TaskStatus.PENDING
    assert reset.last_failure is None
    assert [
        task.task_id for task in scheduler.get_runnable_tasks(now=now + timedelta(minutes=6))
    ] == ["AD-008__validate"]


def test_retry_history_is_persisted_in_scheduler_state(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    now = datetime(2026, 3, 18, 18, 0, tzinfo=timezone.utc)
    task = make_task("AD-008__validate", PhaseName.VALIDATE, max_retries=2)
    store.save_task(task)
    scheduler = TaskScheduler([task], state_store=store)

    scheduler.record_failure(
        task.task_id,
        FailureDetail(failure_class=FailureClass.RETRYABLE, message="Model timeout"),
        now=now,
        backoff_base_seconds=20,
    )

    scheduler_state = store.load_scheduler_state()
    scheduler_history = store.load_scheduler_history()

    assert scheduler_state["tasks"][0]["task_id"] == "AD-008__validate"
    assert scheduler_state["tasks"][0]["retry_history"][0]["failure_class"] == "retryable"
    assert scheduler_state["tasks"][0]["retry_history"][0]["delay_seconds"] == 20
    assert scheduler_history[-1]["event"] == "task_failure_recorded"
