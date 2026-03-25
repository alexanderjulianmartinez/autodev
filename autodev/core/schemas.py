"""Durable runtime schemas for backlog, tasks, runs, validation, and review."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


class AutoDevModel(BaseModel):
    """Base model with strict schema behavior for persisted runtime state."""

    model_config = ConfigDict(extra="forbid")


class PriorityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class BacklogStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class PhaseName(str, Enum):
    PLAN = "plan"
    IMPLEMENT = "implement"
    VALIDATE = "validate"
    REVIEW = "review"
    PROMOTE = "promote"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ValidationStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class FailureClass(str, Enum):
    RETRYABLE = "retryable"
    VALIDATION_FAILURE = "validation_failure"
    POLICY_FAILURE = "policy_failure"
    ENVIRONMENT_FAILURE = "environment_failure"
    MANUAL_INTERVENTION = "manual_intervention"


class ReviewDecision(str, Enum):
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    BLOCKED = "blocked"
    AWAITING_HUMAN_APPROVAL = "awaiting_human_approval"


class IsolationMode(str, Enum):
    SNAPSHOT = "snapshot"
    BRANCH = "branch"
    WORKTREE = "worktree"


class BacklogItem(AutoDevModel):
    """A durable change request tracked independently of execution attempts."""

    item_id: str
    title: str
    description: str = ""
    status: BacklogStatus = BacklogStatus.PLANNED
    priority: PriorityLevel = PriorityLevel.MEDIUM
    dependencies: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    source: str = "manual"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetryHistoryEntry(AutoDevModel):
    """One scheduler retry decision for a task."""

    attempt_number: int = Field(ge=1)
    attempted_at: datetime
    failure_class: FailureClass
    message: str
    retry_scheduled: bool
    scheduled_for: Optional[datetime] = None
    delay_seconds: Optional[int] = Field(default=None, ge=0)


class TaskRecord(AutoDevModel):
    """A materialized runtime task for one phase of one backlog item."""

    task_id: str
    backlog_item_id: str
    phase: PhaseName
    status: TaskStatus = TaskStatus.PENDING
    dependencies: list[str] = Field(default_factory=list)
    retry_count: int = Field(default=0, ge=0)
    max_retries: int = Field(default=0, ge=0)
    next_eligible_at: Optional[datetime] = None
    retry_history: list[RetryHistoryEntry] = Field(default_factory=list)
    last_failure: Optional[FailureDetail] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FailureDetail(AutoDevModel):
    """Structured failure classification attached to task and phase results."""

    failure_class: FailureClass
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class TaskResult(AutoDevModel):
    """The persisted outcome of executing a single task."""

    task_id: str
    status: TaskStatus
    message: str = ""
    artifacts: list[str] = Field(default_factory=list)
    metrics: dict[str, Union[int, float, str, bool]] = Field(default_factory=dict)
    failure: Optional[FailureDetail] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ValidationCommandResult(AutoDevModel):
    """The outcome of one validation command."""

    command: str
    exit_code: int
    status: ValidationStatus
    stdout: str = ""
    stderr: str = ""
    duration_seconds: Optional[float] = Field(default=None, ge=0)


class ValidationResult(AutoDevModel):
    """Persisted validation results for a task or run phase."""

    task_id: str
    status: ValidationStatus
    summary: str = ""
    commands: list[ValidationCommandResult] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    profiles: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    failure: Optional[FailureDetail] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ReviewResult(AutoDevModel):
    """Structured review decision emitted by the review phase."""

    task_id: str
    decision: ReviewDecision
    summary: str
    checks: dict[str, bool] = Field(default_factory=dict)
    blocking_reasons: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    reviewed_at: datetime = Field(default_factory=utc_now)


class RunMetadata(AutoDevModel):
    """Durable metadata for one end-to-end runtime execution."""

    run_id: str
    backlog_item_id: str
    status: RunStatus = RunStatus.PENDING
    phase_sequence: list[PhaseName] = Field(
        default_factory=lambda: [
            PhaseName.PLAN,
            PhaseName.IMPLEMENT,
            PhaseName.VALIDATE,
            PhaseName.REVIEW,
        ]
    )
    workspace_path: str = ""
    isolation_mode: IsolationMode = IsolationMode.SNAPSHOT
    created_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
