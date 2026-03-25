"""Tests for durable runtime schemas."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from autodev.core.schemas import (
    BacklogItem,
    BacklogStatus,
    FailureClass,
    FailureDetail,
    PhaseName,
    PriorityLevel,
    RetryHistoryEntry,
    ReviewDecision,
    ReviewResult,
    RunMetadata,
    RunStatus,
    TaskRecord,
    TaskResult,
    TaskStatus,
    ValidationCommandResult,
    ValidationResult,
    ValidationStatus,
)


class TestBacklogItem:
    def test_requires_item_id_and_title(self):
        with pytest.raises(ValidationError):
            BacklogItem()

    def test_defaults_are_stable(self):
        item = BacklogItem(item_id="AD-003", title="Define durable schemas")

        assert item.status == BacklogStatus.PLANNED
        assert item.priority == PriorityLevel.MEDIUM
        assert item.dependencies == []
        assert item.acceptance_criteria == []
        assert item.labels == []
        assert item.metadata == {}
        assert item.source == "manual"
        assert item.created_at.tzinfo == timezone.utc
        assert item.updated_at.tzinfo == timezone.utc


class TestTaskSchemas:
    def test_task_record_requires_identifiers_and_phase(self):
        with pytest.raises(ValidationError):
            TaskRecord(task_id="AD-003__plan")

    def test_task_record_defaults(self):
        task = TaskRecord(
            task_id="AD-003__plan",
            backlog_item_id="AD-003",
            phase=PhaseName.PLAN,
        )

        assert task.status == TaskStatus.PENDING
        assert task.retry_count == 0
        assert task.max_retries == 0
        assert task.dependencies == []
        assert task.retry_history == []
        assert task.last_failure is None
        assert task.metadata == {}

    def test_retry_history_entry_serializes_cleanly(self):
        entry = RetryHistoryEntry(
            attempt_number=1,
            attempted_at=datetime(2026, 3, 18, 12, 15, tzinfo=timezone.utc),
            failure_class=FailureClass.RETRYABLE,
            message="Transient API failure",
            retry_scheduled=True,
            scheduled_for=datetime(2026, 3, 18, 12, 16, tzinfo=timezone.utc),
            delay_seconds=60,
        )

        entry_copy = RetryHistoryEntry.model_validate_json(entry.model_dump_json())
        assert entry_copy.model_dump(mode="json") == entry.model_dump(mode="json")

    def test_task_result_supports_failure_detail(self):
        result = TaskResult(
            task_id="AD-003__validate",
            status=TaskStatus.FAILED,
            failure=FailureDetail(
                failure_class=FailureClass.VALIDATION_FAILURE,
                message="Targeted validation failed",
            ),
        )

        assert result.failure is not None
        assert result.failure.failure_class == FailureClass.VALIDATION_FAILURE


class TestValidationAndReviewSchemas:
    def test_validation_result_defaults(self):
        result = ValidationResult(task_id="AD-003__validate", status=ValidationStatus.PENDING)

        assert result.summary == ""
        assert result.commands == []
        assert result.changed_files == []
        assert result.profiles == []
        assert result.metadata == {}
        assert result.failure is None

    def test_review_result_requires_summary_and_decision(self):
        with pytest.raises(ValidationError):
            ReviewResult(task_id="AD-003__review")

    def test_round_trip_serialization(self):
        now = datetime(2026, 3, 18, 12, 0, tzinfo=timezone.utc)
        backlog = BacklogItem(
            item_id="AD-003",
            title="Define durable schemas",
            description="Introduce persistent runtime schema objects.",
            priority=PriorityLevel.HIGH,
            acceptance_criteria=["schemas cover MVP runtime state"],
            labels=["priority:p0", "type:core"],
            metadata={"source_issue": "docs/backlog.md"},
            created_at=now,
            updated_at=now,
        )
        task = TaskRecord(
            task_id="AD-003__review",
            backlog_item_id=backlog.item_id,
            phase=PhaseName.REVIEW,
            status=TaskStatus.COMPLETED,
            dependencies=["AD-003__validate"],
            metadata={"attempt": 1},
            created_at=now,
            updated_at=now,
        )
        validation = ValidationResult(
            task_id="AD-003__validate",
            status=ValidationStatus.FAILED,
            summary="Validation failed on the targeted test command.",
            commands=[
                ValidationCommandResult(
                    command="pytest tests/test_schemas.py",
                    exit_code=1,
                    status=ValidationStatus.FAILED,
                    stdout="",
                    stderr="assertion failed",
                    duration_seconds=0.42,
                )
            ],
            changed_files=["autodev/core/schemas.py"],
            profiles=["pytest"],
            metadata={
                "validation_breadth": "targeted",
                "stop_on_first_failure": True,
                "selection_reason": "Strict targeted validation was inferred from changed files.",
            },
            failure=FailureDetail(
                failure_class=FailureClass.VALIDATION_FAILURE,
                message="Schema validation tests failed",
                details={"command_count": 1},
            ),
            started_at=now,
            completed_at=now,
        )
        review = ReviewResult(
            task_id="AD-003__review",
            decision=ReviewDecision.CHANGES_REQUESTED,
            summary="Validation must pass before approval.",
            checks={"validation_passed": False, "diff_present": True},
            blocking_reasons=["validation failed"],
            metadata={"reviewer": "autodev"},
            reviewed_at=now,
        )
        run = RunMetadata(
            run_id="run-001",
            backlog_item_id=backlog.item_id,
            status=RunStatus.RUNNING,
            workspace_path="/tmp/autodev/run-001",
            started_at=now,
            metadata={"operator": "local"},
        )

        backlog_copy = BacklogItem.model_validate_json(backlog.model_dump_json())
        task_copy = TaskRecord.model_validate_json(task.model_dump_json())
        validation_copy = ValidationResult.model_validate_json(validation.model_dump_json())
        review_copy = ReviewResult.model_validate_json(review.model_dump_json())
        run_copy = RunMetadata.model_validate_json(run.model_dump_json())

        assert backlog_copy.model_dump(mode="json") == backlog.model_dump(mode="json")
        assert task_copy.model_dump(mode="json") == task.model_dump(mode="json")
        assert validation_copy.model_dump(mode="json") == validation.model_dump(mode="json")
        assert review_copy.model_dump(mode="json") == review.model_dump(mode="json")
        assert run_copy.model_dump(mode="json") == run.model_dump(mode="json")
