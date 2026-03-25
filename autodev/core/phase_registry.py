"""Formal phase registry and execution contracts for runtime phases."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Union

from pydantic import Field

from autodev.agents.base import AgentContext
from autodev.agents.planner import PlannerAgent
from autodev.agents.reviewer import ReviewerAgent
from autodev.core.schemas import AutoDevModel, PhaseName, TaskStatus, ValidationStatus, utc_now
from autodev.tools.test_runner import TestRunner


class PhaseExecutionPayload(AutoDevModel):
    """Normalized payload passed to all phase handlers."""

    phase: PhaseName
    task_id: str
    issue_url: str = ""
    repo_path: str = ""
    plan: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    validation_results: str = ""
    iteration: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_context(
        cls,
        phase: PhaseName,
        context: AgentContext,
        *,
        task_id: str,
    ) -> "PhaseExecutionPayload":
        return cls(
            phase=phase,
            task_id=task_id,
            issue_url=context.issue_url,
            repo_path=context.repo_path,
            plan=list(context.plan),
            files_modified=list(context.files_modified),
            validation_results=context.validation_results,
            iteration=context.iteration,
            metadata=dict(context.metadata),
        )

    def to_context(self) -> AgentContext:
        return AgentContext(
            issue_url=self.issue_url,
            repo_path=self.repo_path,
            plan=list(self.plan),
            files_modified=list(self.files_modified),
            validation_results=self.validation_results,
            iteration=self.iteration,
            metadata=dict(self.metadata),
        )


class PhaseExecutionResult(AutoDevModel):
    """Structured result returned by all phase handlers."""

    phase: PhaseName
    task_id: str
    status: TaskStatus
    message: str = ""
    artifacts: list[str] = Field(default_factory=list)
    metrics: dict[str, Union[int, float, str, bool]] = Field(default_factory=dict)
    context: AgentContext
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime = Field(default_factory=utc_now)


class PhaseHandler(ABC):
    """Abstract base class for swappable phase handlers."""

    @abstractmethod
    def execute(self, payload: PhaseExecutionPayload) -> PhaseExecutionResult:
        """Execute the phase for one normalized payload."""


class PlannerPhaseHandler(PhaseHandler):
    def __init__(self, *, model_router: Any = None) -> None:
        self._model_router = model_router

    def execute(self, payload: PhaseExecutionPayload) -> PhaseExecutionResult:
        agent = PlannerAgent(model_router=self._model_router)
        updated = agent.run("plan change request", payload.to_context())
        target_files = list(updated.metadata.get("likely_target_files", []))
        validation_hints = list(updated.metadata.get("validation_hints", []))
        acceptance_criteria = list(updated.metadata.get("acceptance_criteria", []))
        return PhaseExecutionResult(
            phase=payload.phase,
            task_id=payload.task_id,
            status=TaskStatus.COMPLETED,
            message=f"Generated {len(updated.plan)} plan step(s)",
            metrics={
                "plan_steps": len(updated.plan),
                "target_files": len(target_files),
                "validation_hints": len(validation_hints),
                "acceptance_criteria": len(acceptance_criteria),
            },
            context=updated,
        )


class ImplementPhaseHandler(PhaseHandler):
    def __init__(
        self,
        *,
        model_router: Any = None,
        workspace_manager: Any = None,
        supervisor: Any = None,
    ) -> None:
        self._model_router = model_router
        self._workspace_manager = workspace_manager
        self._supervisor = supervisor

    def execute(self, payload: PhaseExecutionPayload) -> PhaseExecutionResult:
        from autodev.agents.coder import CoderAgent

        agent = CoderAgent(
            model_router=self._model_router,
            workspace_manager=self._workspace_manager,
            supervisor=self._supervisor,
        )
        updated = agent.run("implement change request", payload.to_context())
        implementation_status = str(updated.metadata.get("implementation_status", "applied"))
        status = (
            TaskStatus.COMPLETED
            if implementation_status in {"applied", "noop"}
            else TaskStatus.FAILED
        )
        return PhaseExecutionResult(
            phase=payload.phase,
            task_id=payload.task_id,
            status=status,
            message=f"Tracked {len(updated.files_modified)} modified file(s)",
            metrics={
                "files_modified": len(updated.files_modified),
                "implementation_status": implementation_status,
            },
            context=updated,
        )


class ValidatePhaseHandler(PhaseHandler):
    def __init__(
        self,
        *,
        supervisor: Any = None,
        default_workspace_path: str | None = None,
    ) -> None:
        self._supervisor = supervisor
        self._default_workspace_path = default_workspace_path or "."

    def execute(self, payload: PhaseExecutionPayload) -> PhaseExecutionResult:
        runner = TestRunner(supervisor=self._supervisor)
        repo_path = payload.repo_path or self._default_workspace_path
        result = runner.run(repo_path)
        validation_status = ValidationStatus.PASSED if result.passed else ValidationStatus.FAILED
        output = f"{validation_status.value.upper()}\n{result.output}\n{result.error}".strip()
        updated = payload.to_context().model_copy(update={"validation_results": output})
        return PhaseExecutionResult(
            phase=payload.phase,
            task_id=payload.task_id,
            status=TaskStatus.COMPLETED if result.passed else TaskStatus.FAILED,
            message="Validation passed" if result.passed else "Validation failed",
            metrics={
                "passed": result.passed,
                "return_code": result.return_code,
            },
            context=updated,
        )


class ReviewPhaseHandler(PhaseHandler):
    def __init__(self, *, model_router: Any = None) -> None:
        self._model_router = model_router

    def execute(self, payload: PhaseExecutionPayload) -> PhaseExecutionResult:
        agent = ReviewerAgent(model_router=self._model_router)
        updated = agent.run("review change request", payload.to_context())
        review_summary = str(updated.metadata.get("review", "Review completed."))
        return PhaseExecutionResult(
            phase=payload.phase,
            task_id=payload.task_id,
            status=TaskStatus.COMPLETED,
            message=review_summary,
            metrics={"review_passed": bool(updated.metadata.get("review_passed", False))},
            context=updated,
        )


class PromotePhaseHandler(PhaseHandler):
    def execute(self, payload: PhaseExecutionPayload) -> PhaseExecutionResult:
        return PhaseExecutionResult(
            phase=payload.phase,
            task_id=payload.task_id,
            status=TaskStatus.COMPLETED,
            message="Promotion handler is registered but not invoked by the default runtime.",
            metrics={"skipped": True},
            context=payload.to_context(),
        )


class PhaseRegistry:
    """Registry for phase handlers behind stable execution contracts."""

    def __init__(self) -> None:
        self._handlers: dict[PhaseName, PhaseHandler] = {}

    @classmethod
    def default(
        cls,
        *,
        model_router: Any = None,
        supervisor: Any = None,
        workspace_manager: Any = None,
        default_workspace_path: str | None = None,
    ) -> "PhaseRegistry":
        registry = cls()
        registry.register(PhaseName.PLAN, PlannerPhaseHandler(model_router=model_router))
        registry.register(
            PhaseName.IMPLEMENT,
            ImplementPhaseHandler(
                model_router=model_router,
                workspace_manager=workspace_manager,
                supervisor=supervisor,
            ),
        )
        registry.register(
            PhaseName.VALIDATE,
            ValidatePhaseHandler(
                supervisor=supervisor,
                default_workspace_path=default_workspace_path,
            ),
        )
        registry.register(PhaseName.REVIEW, ReviewPhaseHandler(model_router=model_router))
        registry.register(PhaseName.PROMOTE, PromotePhaseHandler())
        return registry

    @property
    def phases(self) -> tuple[PhaseName, ...]:
        return tuple(self._handlers.keys())

    def register(self, phase: PhaseName, handler: PhaseHandler) -> None:
        self._handlers[phase] = handler

    def get(self, phase: PhaseName) -> PhaseHandler:
        try:
            return self._handlers[phase]
        except KeyError as exc:
            raise KeyError(f"No handler registered for phase {phase.value!r}") from exc

    def execute(self, payload: PhaseExecutionPayload) -> PhaseExecutionResult:
        started_at = utc_now()
        result = self.get(payload.phase).execute(payload)
        completed_at = utc_now()
        return result.model_copy(
            update={
                "started_at": started_at,
                "completed_at": completed_at,
            }
        )
