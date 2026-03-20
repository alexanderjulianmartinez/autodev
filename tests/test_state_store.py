"""Tests for the file-backed runtime state store."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from autodev.core.schemas import (
    BacklogItem,
    BacklogStatus,
    ReviewDecision,
    ReviewResult,
    RunMetadata,
    RunStatus,
    TaskRecord,
    TaskResult,
    TaskStatus,
)
from autodev.core.state_store import FileStateStore


def test_backlog_items_persist_and_list(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    backlog = BacklogItem(
        item_id="AD-004",
        title="Implement persistent state store",
        status=BacklogStatus.ACTIVE,
        acceptance_criteria=["persists to disk"],
    )

    path = store.save_backlog_item(backlog)
    loaded = store.load_backlog_item("AD-004")
    listed = store.list_backlog_items()

    assert path == tmp_path / "state" / "backlog" / "AD-004.json"
    assert loaded == backlog
    assert listed == [backlog]


def test_task_update_rewrites_existing_state(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    task = TaskRecord(
        task_id="AD-004__validate",
        backlog_item_id="AD-004",
        phase="validate",
    )
    store.save_task(task)

    updated = store.update_task(
        "AD-004__validate",
        lambda current: current.model_copy(update={"status": TaskStatus.RUNNING, "retry_count": 1}),
    )
    payload = json.loads((tmp_path / "state" / "tasks" / "AD-004__validate.json").read_text())

    assert updated.status == TaskStatus.RUNNING
    assert updated.retry_count == 1
    assert payload["status"] == "running"
    assert store.load_task("AD-004__validate").retry_count == 1


def test_run_metadata_and_review_result_persist_under_run_directory(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    now = datetime(2026, 3, 18, 15, 30, tzinfo=timezone.utc)
    run = RunMetadata(
        run_id="run-004",
        backlog_item_id="AD-004",
        status=RunStatus.RUNNING,
        workspace_path="/tmp/autodev/run-004",
        started_at=now,
    )
    review = ReviewResult(
        task_id="AD-004__review",
        decision=ReviewDecision.APPROVED,
        summary="Validation passed and diff is reviewable.",
        checks={"validation_passed": True, "diff_present": True},
        reviewed_at=now,
    )

    run_path = store.save_run(run)
    review_path = store.save_review_result(run.run_id, review)

    assert run_path == tmp_path / "state" / "runs" / "run-004" / "metadata.json"
    assert (
        review_path == tmp_path / "state" / "runs" / "run-004" / "reviews" / "AD-004__review.json"
    )
    assert store.load_run("run-004") == run
    assert store.load_review_result("run-004", "AD-004__review") == review
    assert store.list_runs() == [run]
    assert store.list_review_results("run-004") == [review]


def test_reports_and_scheduler_history_persist(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))

    report_path = store.save_report("run-004-summary", {"status": "running"})
    state_path = store.save_scheduler_state({"last_run_id": "run-004", "retry_queue": []})
    history_path = store.append_scheduler_history({"event": "run_started", "run_id": "run-004"})
    store.append_scheduler_history({"event": "run_completed", "run_id": "run-004"})

    assert report_path == tmp_path / "state" / "reports" / "run-004-summary.json"
    assert state_path == tmp_path / "state" / "scheduler" / "state.json"
    assert history_path == tmp_path / "state" / "scheduler" / "history.json"
    assert store.load_report("run-004-summary") == {"status": "running"}
    assert store.load_scheduler_state()["last_run_id"] == "run-004"
    assert [entry["event"] for entry in store.load_scheduler_history()] == [
        "run_started",
        "run_completed",
    ]


def test_report_entries_can_be_appended_and_reloaded(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))

    first_path = store.append_report_entry("guardrails", {"allowed": False, "operation": "shell"})
    second_path = store.append_report_entry("guardrails", {"allowed": True, "operation": "file"})

    assert first_path == tmp_path / "state" / "reports" / "guardrails.json"
    assert second_path == tmp_path / "state" / "reports" / "guardrails.json"
    assert store.load_report_entries("guardrails") == [
        {"allowed": False, "operation": "shell"},
        {"allowed": True, "operation": "file"},
    ]


def test_interrupted_run_can_be_reloaded_without_losing_state(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    run = RunMetadata(
        run_id="run-restore",
        backlog_item_id="AD-004",
        status=RunStatus.RUNNING,
        workspace_path="/tmp/autodev/run-restore",
    )
    result = TaskResult(
        task_id="AD-004__implement",
        status=TaskStatus.COMPLETED,
        message="Implementation completed before interruption.",
    )
    review = ReviewResult(
        task_id="AD-004__review",
        decision=ReviewDecision.CHANGES_REQUESTED,
        summary="Awaiting another validation attempt.",
    )

    store.save_run(run)
    store.save_task_result(run.run_id, result)
    store.save_review_result(run.run_id, review)

    reloaded_store = FileStateStore(str(tmp_path / "state"))

    assert reloaded_store.load_run("run-restore") == run
    assert reloaded_store.load_task_result("run-restore", "AD-004__implement") == result
    assert reloaded_store.load_review_result("run-restore", "AD-004__review") == review


def test_run_dir_rejects_traversal_run_id(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))

    with pytest.raises(ValueError, match="Invalid run identifier"):
        store.run_dir("../escape")


def test_run_dir_rejects_path_separator_in_run_id(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))

    with pytest.raises(ValueError, match="Invalid run identifier"):
        store.run_dir("nested/run")


def test_run_dir_accepts_safe_run_id(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))

    run_dir = store.run_dir("run-011_safe.case")

    assert run_dir == tmp_path / "state" / "runs" / "run-011_safe.case"
