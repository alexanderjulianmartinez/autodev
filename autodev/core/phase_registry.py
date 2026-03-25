"""Formal phase registry and execution contracts for runtime phases."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from pydantic import Field

from autodev.agents.base import AgentContext
from autodev.agents.planner import PlannerAgent
from autodev.agents.reviewer import ReviewerAgent
from autodev.core.failure_classifier import classify_phase_failure
from autodev.core.schemas import (
    AutoDevModel,
    FailureClass,
    FailureDetail,
    PhaseName,
    ReviewDecision,
    ReviewResult,
    TaskStatus,
    ValidationResult,
    ValidationStatus,
    utc_now,
)
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
    failure: Optional[FailureDetail] = None
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
        state_store: Any = None,
    ) -> None:
        self._supervisor = supervisor
        self._default_workspace_path = default_workspace_path or "."
        self._state_store = state_store

    def execute(self, payload: PhaseExecutionPayload) -> PhaseExecutionResult:
        runner = TestRunner(supervisor=self._supervisor)
        repo_path = payload.repo_path or self._default_workspace_path
        changed_files = self._resolve_changed_files(payload)
        explicit_commands = self._resolve_validation_commands(payload)
        validation_policy = self._resolve_validation_policy(payload)
        validation_result = runner.run_validation(
            repo_path=repo_path,
            task_id=payload.task_id,
            changed_files=changed_files,
            explicit_commands=explicit_commands,
            validation_breadth=validation_policy["validation_breadth"],
            stop_on_first_failure=validation_policy["stop_on_first_failure"],
        )
        failure = None
        if validation_result.status == ValidationStatus.FAILED:
            combined_output = "\n".join(
                part
                for part in [
                    validation_result.summary,
                    *[command.stderr for command in validation_result.commands],
                ]
                if part
            )
            failure = classify_phase_failure(
                payload.phase,
                message=combined_output,
                metadata={
                    **payload.metadata,
                    "validation_results": combined_output,
                },
                metrics={
                    "commands": len(validation_result.commands),
                },
            )
            validation_result = validation_result.model_copy(update={"failure": failure})
        metadata = dict(payload.metadata)
        artifacts: list[str] = []
        run_id = str(metadata.get("run_id", "")).strip()
        if run_id and self._state_store is not None:
            validation_path = self._state_store.save_validation_result(run_id, validation_result)
            metadata["validation_result_path"] = str(validation_path)
            artifacts.append(str(validation_path))
        metadata["validation_profiles"] = list(validation_result.profiles)
        metadata["validation_command_list"] = [
            command.command for command in validation_result.commands
        ]
        metadata["validation_breadth"] = validation_result.metadata.get("validation_breadth")
        metadata["validation_stop_on_first_failure"] = validation_result.metadata.get(
            "stop_on_first_failure"
        )
        metadata["validation_selection_reason"] = validation_result.metadata.get(
            "selection_reason", ""
        )
        output = self._format_validation_output(validation_result)
        updated = payload.to_context().model_copy(
            update={
                "validation_results": output,
                "metadata": metadata,
            }
        )
        return PhaseExecutionResult(
            phase=payload.phase,
            task_id=payload.task_id,
            status=(
                TaskStatus.COMPLETED
                if validation_result.status == ValidationStatus.PASSED
                else TaskStatus.FAILED
            ),
            message=validation_result.summary,
            artifacts=artifacts,
            metrics={
                "passed": validation_result.status == ValidationStatus.PASSED,
                "commands": len(validation_result.commands),
                "profiles": ",".join(validation_result.profiles),
                "stop_on_first_failure": bool(
                    validation_result.metadata.get("stop_on_first_failure", True)
                ),
                "validation_breadth": str(
                    validation_result.metadata.get("validation_breadth", "targeted")
                ),
            },
            failure=failure,
            context=updated,
        )

    def _resolve_validation_policy(self, payload: PhaseExecutionPayload) -> dict[str, Any]:
        metadata = payload.metadata
        backlog_metadata = self._load_backlog_metadata(payload)
        breadth = metadata.get("validation_breadth")
        if breadth is None:
            breadth = backlog_metadata.get("validation_breadth")

        continue_on_error = self._coerce_bool(
            metadata.get("validation_continue_on_error", metadata.get("continue_on_error"))
        )
        if continue_on_error is None:
            continue_on_error = self._coerce_bool(
                backlog_metadata.get(
                    "validation_continue_on_error",
                    backlog_metadata.get("continue_on_error"),
                )
            )

        stop_on_first_failure = self._coerce_bool(
            metadata.get("validation_stop_on_first_failure", metadata.get("stop_on_first_failure"))
        )
        if stop_on_first_failure is None:
            stop_on_first_failure = self._coerce_bool(
                backlog_metadata.get(
                    "validation_stop_on_first_failure",
                    backlog_metadata.get("stop_on_first_failure"),
                )
            )

        if continue_on_error is not None:
            resolved_stop_on_first_failure = not continue_on_error
        elif stop_on_first_failure is not None:
            resolved_stop_on_first_failure = stop_on_first_failure
        else:
            resolved_stop_on_first_failure = True

        return {
            "validation_breadth": self._normalize_validation_breadth(breadth),
            "stop_on_first_failure": resolved_stop_on_first_failure,
        }

    def _load_backlog_metadata(self, payload: PhaseExecutionPayload) -> dict[str, Any]:
        backlog_item_id = str(payload.metadata.get("backlog_item_id", "")).strip()
        if not backlog_item_id or self._state_store is None:
            return {}
        try:
            backlog_item = self._state_store.load_backlog_item(backlog_item_id)
        except Exception:
            return {}
        return dict(backlog_item.metadata)

    def _resolve_validation_commands(self, payload: PhaseExecutionPayload) -> list[str] | None:
        metadata = payload.metadata
        commands = metadata.get("validation_commands") or metadata.get("validation_command")
        normalized = self._normalize_commands(commands)
        if normalized:
            return normalized

        backlog_item_id = str(metadata.get("backlog_item_id", "")).strip()
        if not backlog_item_id or self._state_store is None:
            return None
        try:
            backlog_item = self._state_store.load_backlog_item(backlog_item_id)
        except Exception:
            return None

        backlog_commands = backlog_item.metadata.get(
            "validation_commands"
        ) or backlog_item.metadata.get("validation_command")
        normalized = self._normalize_commands(backlog_commands)
        return normalized or None

    def _resolve_changed_files(self, payload: PhaseExecutionPayload) -> list[str]:
        changed_files = [str(path) for path in payload.files_modified if str(path).strip()]
        if changed_files:
            return changed_files

        summary_files = payload.metadata.get("implementation_change_summary", [])
        changed_files = [str(path) for path in summary_files if str(path).strip()]
        if changed_files:
            return changed_files

        changed_files_path = str(payload.metadata.get("changed_files_path", "")).strip()
        if not changed_files_path:
            return []
        try:
            artifact_payload = json.loads(Path(changed_files_path).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        return [
            str(entry.get("path", "")).strip()
            for entry in artifact_payload.get("files", [])
            if str(entry.get("path", "")).strip()
        ]

    def _normalize_commands(self, commands: Any) -> list[str]:
        if commands is None:
            return []
        if isinstance(commands, str):
            command = commands.strip()
            return [command] if command else []
        normalized: list[str] = []
        for command in commands:
            candidate = str(command).strip()
            if candidate:
                normalized.append(candidate)
        return normalized

    def _normalize_validation_breadth(self, value: Any) -> str:
        candidate = str(value or "targeted").strip().lower()
        if candidate == TestRunner.BROADER_FALLBACK_BREADTH:
            return TestRunner.BROADER_FALLBACK_BREADTH
        return TestRunner.DEFAULT_VALIDATION_BREADTH

    def _coerce_bool(self, value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        lowered = str(value).strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return None

    def _format_validation_output(self, validation_result: ValidationResult) -> str:
        sections = [validation_result.status.value.upper(), validation_result.summary]
        policy_lines = []
        if validation_result.metadata:
            policy_lines.append(
                "Policy: "
                f"breadth={validation_result.metadata.get('validation_breadth', 'targeted')}, "
                "stop_on_first_failure="
                f"{validation_result.metadata.get('stop_on_first_failure', True)}"
            )
            selection_reason = str(validation_result.metadata.get("selection_reason", "")).strip()
            if selection_reason:
                policy_lines.append(f"Reason: {selection_reason}")
        if policy_lines:
            sections.append("\n".join(policy_lines))
        for command_result in validation_result.commands:
            command_lines = [
                f"$ {command_result.command}",
                f"exit_code={command_result.exit_code}",
            ]
            if command_result.stdout:
                command_lines.append(command_result.stdout.rstrip())
            if command_result.stderr:
                command_lines.append(command_result.stderr.rstrip())
            sections.append("\n".join(command_lines).strip())
        return "\n\n".join(section for section in sections if section).strip()


class ReviewPhaseHandler(PhaseHandler):
    def __init__(self, *, model_router: Any = None, state_store: Any = None) -> None:
        self._model_router = model_router
        self._state_store = state_store

    def execute(self, payload: PhaseExecutionPayload) -> PhaseExecutionResult:
        agent = ReviewerAgent(model_router=self._model_router)
        updated = agent.run("review change request", payload.to_context())
        review_summary = str(
            updated.metadata.get(
                "review_summary",
                updated.metadata.get("review", "Review completed."),
            )
        )
        review_decision = ReviewDecision(
            str(updated.metadata.get("review_decision", ReviewDecision.BLOCKED.value))
        )
        checks = dict(updated.metadata.get("review_checks", {}))
        blocking_reasons = [
            str(reason) for reason in updated.metadata.get("review_blocking_reasons", [])
        ]
        review_result = ReviewResult(
            task_id=payload.task_id,
            decision=review_decision,
            summary=review_summary,
            checks=checks,
            blocking_reasons=blocking_reasons,
            metadata={
                "files_modified": list(updated.files_modified),
                "implementation_diff_path": str(
                    updated.metadata.get("implementation_diff_path", "")
                ),
                "validation_result_path": str(updated.metadata.get("validation_result_path", "")),
                "acceptance_criteria": list(updated.metadata.get("acceptance_criteria", [])),
                "policy_gate_failures": list(updated.metadata.get("policy_gate_failures", [])),
                "secret_exposure_findings": list(
                    updated.metadata.get("secret_exposure_findings", [])
                ),
            },
        )
        metadata = dict(updated.metadata)
        artifacts: list[str] = []
        run_id = str(metadata.get("run_id", "")).strip()
        if run_id and self._state_store is not None:
            review_path = self._state_store.save_review_result(run_id, review_result)
            metadata["review_result_path"] = str(review_path)
            artifacts.append(str(review_path))
        metadata["review_decision"] = review_decision.value
        metadata["review_summary"] = review_summary
        metadata["review_checks"] = checks
        metadata["review_blocking_reasons"] = blocking_reasons
        metadata["review_passed"] = review_decision == ReviewDecision.APPROVED
        updated = updated.model_copy(update={"metadata": metadata})
        failure = self._failure_for_review_decision(
            review_decision,
            review_summary,
            blocking_reasons,
        )
        return PhaseExecutionResult(
            phase=payload.phase,
            task_id=payload.task_id,
            status=(
                TaskStatus.COMPLETED
                if review_decision == ReviewDecision.APPROVED
                else TaskStatus.FAILED
            ),
            message=review_summary,
            artifacts=artifacts,
            metrics={
                "review_passed": review_decision == ReviewDecision.APPROVED,
                "review_decision": review_decision.value,
                "blocking_reasons": len(blocking_reasons),
            },
            failure=failure,
            context=updated,
        )

    def _failure_for_review_decision(
        self,
        decision: ReviewDecision,
        summary: str,
        blocking_reasons: list[str],
    ) -> Optional[FailureDetail]:
        if decision == ReviewDecision.APPROVED:
            return None
        if decision == ReviewDecision.CHANGES_REQUESTED:
            failure_class = FailureClass.VALIDATION_FAILURE
        else:
            failure_class = FailureClass.POLICY_FAILURE
        return FailureDetail(
            failure_class=failure_class,
            message=summary,
            details={
                "decision": decision.value,
                "blocking_reasons": list(blocking_reasons),
            },
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
        state_store: Any = None,
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
                state_store=state_store,
            ),
        )
        registry.register(
            PhaseName.REVIEW,
            ReviewPhaseHandler(model_router=model_router, state_store=state_store),
        )
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
