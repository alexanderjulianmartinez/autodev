"""Orchestrator: unified runtime coordinator for AutoDev pipelines."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from autodev.core.config import PipelineConfig
from urllib.parse import urlparse

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from autodev.agents.base import AgentContext
from autodev.agents.debugger import DebuggerAgent
from autodev.core.backlog_service import BacklogService
from autodev.core.failure_classifier import classify_phase_failure
from autodev.core.phase_registry import PhaseExecutionPayload, PhaseRegistry
from autodev.core.run_reporter import RunReporter
from autodev.core.schemas import (
    FailureDetail,
    IsolationMode,
    PhaseName,
    ReviewDecision,
    RunStatus,
    TaskResult,
    TaskStatus,
    utc_now,
)
from autodev.core.state_store import FileStateStore
from autodev.core.supervisor import Supervisor
from autodev.core.task_graph import TaskGraph, TaskScheduler
from autodev.core.workspace_manager import WorkspaceManager
from autodev.github.issue_intake import IssueIntakeService
from autodev.github.pr_creator import PRCreator
from autodev.github.repo_cloner import RepoCloner
from autodev.models.router import ModelRouter

logger = logging.getLogger(__name__)
console = Console()
SAFE_BACKLOG_TOKEN_PATTERN = re.compile(r"[^a-z0-9._-]+")


class PipelineState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Orchestrator:
    """Coordinates the canonical AutoDev phase pipeline."""

    def __init__(
        self,
        max_iterations: int = 3,
        dry_run: bool = False,
        work_dir: str | None = None,
        isolation_mode: IsolationMode = IsolationMode.SNAPSHOT,
        pipeline_config: Optional["PipelineConfig"] = None,
    ) -> None:
        from autodev.core.config import PipelineConfig as _PipelineConfig

        # pipeline_config provides validation/retry settings.
        # The explicit kwargs (max_iterations, dry_run, isolation_mode) always
        # take precedence — they represent caller intent (e.g. CLI flags).
        self.pipeline_config: _PipelineConfig = pipeline_config or _PipelineConfig()
        self.task_graph = TaskGraph.default_pipeline()
        self.model_router = ModelRouter()
        self.dry_run = dry_run
        self.work_dir = work_dir or tempfile.mkdtemp(prefix="autodev_")
        self.isolation_mode = isolation_mode
        self.state_store = FileStateStore(os.path.join(self.work_dir, "state"))
        self.backlog_service = BacklogService(self.state_store)
        self.supervisor = Supervisor(
            max_iterations=max_iterations,
            state_store=self.state_store,
            report_name="guardrails-session",
        )
        self.workspace_manager = WorkspaceManager(self.state_store)
        self.phase_registry = PhaseRegistry.default(
            model_router=self.model_router,
            supervisor=self.supervisor,
            workspace_manager=self.workspace_manager,
            default_workspace_path=self.work_dir,
            state_store=self.state_store,
        )
        self._state: PipelineState = PipelineState.PENDING
        self._stage_outputs: dict[str, Any] = {}

    def execute(self, pipeline_config: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Execute a configured stage list using the unified orchestrator state model."""
        self._state = PipelineState.RUNNING
        current_context = dict(context)

        try:
            for stage in pipeline_config.get("stages", []):
                stage_name = stage.get("name", "unnamed")
                self._stage_outputs[stage_name] = {"status": "completed"}
                current_context["last_stage"] = stage_name
            self._state = PipelineState.COMPLETED
        except Exception as exc:
            self._state = PipelineState.FAILED
            current_context["error"] = str(exc)
            logger.error("Pipeline failed at stage %r: %s", current_context.get("last_stage"), exc)

        return current_context

    # ------------------------------------------------------------------
    # Main entry points
    # ------------------------------------------------------------------

    def resume_pipeline(self, run_id: str) -> AgentContext:
        """Resume an interrupted run by re-executing its pipeline.

        Loads persisted run metadata to recover the original issue URL, then
        delegates to :meth:`run_pipeline`.  If the run is already completed the
        pipeline is re-executed so the caller can produce fresh artifacts.

        Raises
        ------
        FileNotFoundError
            If *run_id* does not correspond to a persisted run.
        ValueError
            If the persisted run has no ``issue_url`` in its metadata.
        """
        run = self.state_store.load_run(run_id)
        issue_url = str(run.metadata.get("issue_url", "")).strip()
        if not issue_url:
            raise ValueError(
                f"Run {run_id!r} has no issue_url in its persisted metadata and cannot be resumed."
            )
        logger.info("Resuming run %r for issue %s", run_id, issue_url)
        return self.run_pipeline(issue_url)

    def run_pipeline(self, issue_url: str) -> AgentContext:
        """Execute the full issue → plan → implement → validate → review → PR pipeline."""
        return self._run_pipeline_impl(issue_url, self._read_issue)

    def run_ci_pipeline(self, run_url: str) -> AgentContext:
        """Execute the CI fix pipeline for a failed GitHub Actions run."""
        return self._run_pipeline_impl(run_url, self._read_ci_run)

    def _run_pipeline_impl(
        self,
        entry_url: str,
        intake_fn: Callable[[AgentContext], AgentContext],
    ) -> AgentContext:
        """Shared pipeline body: intake → clone → plan → implement → validate → review → promote."""
        console.print(Panel(f"[bold cyan]AutoDev Pipeline[/bold cyan]\n{entry_url}", expand=False))
        self._state = PipelineState.RUNNING
        self._stage_outputs.clear()

        # Seed context with validation settings from pipeline_config.
        # Intake metadata (from GitHub issue / CI run) takes precedence via setdefault.
        _cfg_meta = self.pipeline_config.as_context_metadata()
        context = AgentContext(issue_url=entry_url, metadata=_cfg_meta)
        final_run_status: RunStatus | None = None

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True,
                console=console,
            ) as progress:
                # 1. Intake (issue or CI run)
                # Config defaults are seeded into context; intake adds on top.
                task = progress.add_task("Analyzing issue...", total=None)
                context = intake_fn(context)
                self._stage_outputs["intake"] = {"status": "completed"}
                progress.update(task, completed=True)

                progress.update(task, description="Preparing run workspace...")
                context = self._start_run(context)
                self._stage_outputs["run"] = {"status": "completed"}

                # 2. Clone repo
                progress.update(task, description="Cloning repository...")
                context = self._clone_repo(context)

                # 3. Plan
                progress.update(task, description="Generating plan...")
                context = self._plan(context)
                console.print(f"[green]Plan:[/green] {len(context.plan)} step(s)")

                # 4. Implement → Validate loop
                for iteration in range(self.supervisor.max_iterations):
                    progress.update(
                        task, description=f"Implementing changes (iteration {iteration + 1})..."
                    )
                    context = self._implement(context)
                    self._stage_outputs.setdefault("implement", {"status": "completed"})[
                        "iteration"
                    ] = iteration + 1

                    progress.update(task, description="Running validation...")
                    context = self._validate(context)
                    self._stage_outputs.setdefault("validate", {"status": "completed"})[
                        "iteration"
                    ] = iteration + 1

                    if "PASSED" in context.validation_results or context.validation_results == "":
                        break

                    progress.update(task, description="Debugging validation failures...")
                    context = self._debug(context)
                    self.supervisor.increment()
                    if self.supervisor.check_iteration_limit():
                        logger.warning("Max iterations reached; proceeding with current state.")
                        break

                # 5. Review
                progress.update(task, description="Reviewing changes...")
                context = self._review(context)

                # 6. Open PR
                if self._review_allows_promotion(context):
                    promotion_mode = self._promotion_mode(context)
                    if self.dry_run and promotion_mode != "patch_bundle":
                        self._stage_outputs["promote"] = {
                            "status": "skipped",
                            "message": (
                                f"Dry run: skipping remote promotion workflow {promotion_mode}."
                            ),
                            "artifacts": [],
                            "metrics": {
                                "review_decision": str(
                                    context.metadata.get("review_decision", "unknown")
                                ),
                                "promotion_mode": promotion_mode,
                            },
                        }
                        console.print("[yellow]Dry run: skipping remote promotion[/yellow]")
                    else:
                        progress.update(
                            task,
                            description=self._promotion_progress_message(promotion_mode),
                        )
                        context = self._promote(context)
                else:
                    self._stage_outputs["promote"] = {
                        "status": "blocked",
                        "message": self._promotion_blocked_message(context),
                        "artifacts": [],
                        "metrics": {
                            "review_decision": str(
                                context.metadata.get("review_decision", "unknown")
                            ),
                            "promotion_mode": self._promotion_mode(context),
                        },
                    }
                    console.print("[yellow]Promotion skipped: review not approved[/yellow]")

            self._state = PipelineState.COMPLETED
            final_run_status = RunStatus.COMPLETED
            console.print(Panel("[bold green]Pipeline complete![/bold green]", expand=False))
            return context
        except Exception:
            self._state = PipelineState.FAILED
            final_run_status = RunStatus.FAILED
            logger.exception("Pipeline failed while processing %s", entry_url)
            raise
        finally:
            run_id = context.metadata.get("run_id")
            if run_id and final_run_status is not None:
                try:
                    self.workspace_manager.finalize_run(
                        run_id,
                        status=final_run_status,
                        quarantine_on_failure=final_run_status == RunStatus.FAILED,
                    )
                except Exception as finalize_error:
                    logger.exception("Failed to finalize run %s", run_id)
                    finalize_error_message = str(finalize_error)
                    try:
                        self.state_store.update_run(
                            run_id,
                            lambda current: current.model_copy(
                                update={
                                    "metadata": {
                                        **current.metadata,
                                        "finalize_run_error": finalize_error_message,
                                        "finalize_run_error_at": utc_now().isoformat(),
                                    }
                                }
                            ),
                        )
                    except Exception:
                        logger.exception("Failed to persist finalize error for run %s", run_id)
                try:
                    RunReporter(self.state_store).write(
                        run_id,
                        status=final_run_status,
                        stage_outputs=dict(self._stage_outputs),
                        context_metadata=dict(context.metadata),
                        files_modified=[str(p) for p in context.files_modified],
                    )
                except Exception:
                    logger.exception("RunReporter failed for run %s", run_id)

    # ------------------------------------------------------------------
    # Private stage helpers
    # ------------------------------------------------------------------

    def register_phase_handler(self, phase: PhaseName, handler: Any) -> None:
        self.phase_registry.register(phase, handler)

    def _execute_phase(self, phase: PhaseName, context: AgentContext) -> AgentContext:
        payload = PhaseExecutionPayload.from_context(
            phase,
            context,
            task_id=self._phase_task_id(context, phase),
        )
        try:
            result = self.phase_registry.execute(payload)
        except Exception as exc:
            failure = classify_phase_failure(
                phase,
                message=str(exc),
                exception=exc,
                metadata=payload.metadata,
            )
            self._record_phase_result(
                payload=payload,
                status=TaskStatus.FAILED,
                message=str(exc),
                artifacts=[],
                metrics={},
                failure=failure,
                started_at=utc_now(),
                completed_at=utc_now(),
            )
            raise

        failure = result.failure
        if result.status == TaskStatus.FAILED and failure is None:
            failure = classify_phase_failure(
                phase,
                message=result.message,
                metadata={
                    **payload.metadata,
                    **result.context.metadata,
                    "validation_results": result.context.validation_results,
                },
                metrics=result.metrics,
            )
            result = result.model_copy(update={"failure": failure})

        self._stage_outputs[phase.value] = {
            "status": result.status.value,
            "message": result.message,
            "artifacts": list(result.artifacts),
            "metrics": dict(result.metrics),
        }
        if failure is not None:
            self._stage_outputs[phase.value]["failure_class"] = failure.failure_class.value
        self._persist_task_result(payload, result)
        if result.status == TaskStatus.FAILED and failure is not None:
            self._record_scheduler_failure(payload, failure)
        return result.context

    def _persist_task_result(self, payload: PhaseExecutionPayload, result: Any) -> None:
        run_id = str(payload.metadata.get("run_id", "")).strip()
        if not run_id:
            return
        task_result = TaskResult(
            task_id=payload.task_id,
            status=result.status,
            message=result.message,
            artifacts=list(result.artifacts),
            metrics=dict(result.metrics),
            failure=result.failure,
            started_at=result.started_at,
            completed_at=result.completed_at,
        )
        task_result_path = self.state_store.save_task_result(run_id, task_result)
        self._stage_outputs.setdefault(payload.phase.value, {}).setdefault("artifacts", [])
        if str(task_result_path) not in self._stage_outputs[payload.phase.value]["artifacts"]:
            self._stage_outputs[payload.phase.value]["artifacts"].append(str(task_result_path))

    def _record_phase_result(
        self,
        *,
        payload: PhaseExecutionPayload,
        status: TaskStatus,
        message: str,
        artifacts: list[str],
        metrics: dict[str, Any],
        failure: FailureDetail | None,
        started_at,
        completed_at,
    ) -> None:
        self._stage_outputs[payload.phase.value] = {
            "status": status.value,
            "message": message,
            "artifacts": list(artifacts),
            "metrics": dict(metrics),
        }
        if failure is not None:
            self._stage_outputs[payload.phase.value]["failure_class"] = failure.failure_class.value

        run_id = str(payload.metadata.get("run_id", "")).strip()
        if not run_id:
            return
        self.state_store.save_task_result(
            run_id,
            TaskResult(
                task_id=payload.task_id,
                status=status,
                message=message,
                artifacts=list(artifacts),
                metrics=dict(metrics),
                failure=failure,
                started_at=started_at,
                completed_at=completed_at,
            ),
        )
        if failure is not None:
            self._record_scheduler_failure(payload, failure)

    def _record_scheduler_failure(
        self,
        payload: PhaseExecutionPayload,
        failure: FailureDetail,
    ) -> None:
        durable_task = self._load_durable_task(payload)
        if durable_task is None:
            return
        scheduler = TaskScheduler([durable_task], state_store=self.state_store)
        scheduler.record_failure(durable_task.task_id, failure)

    def _load_durable_task(self, payload: PhaseExecutionPayload) -> Any | None:
        candidate_ids: list[str] = [payload.task_id]
        backlog_item_id = str(payload.metadata.get("backlog_item_id", "")).strip()
        if backlog_item_id:
            candidate_ids.append(f"{backlog_item_id}__{payload.phase.value}")

        seen: set[str] = set()
        for candidate_id in candidate_ids:
            if not candidate_id or candidate_id in seen:
                continue
            seen.add(candidate_id)
            try:
                return self.state_store.load_task(candidate_id)
            except Exception:
                continue
        return None

    def _read_issue(self, context: AgentContext) -> AgentContext:
        try:
            intake = IssueIntakeService(self.backlog_service)
            item = intake.intake(context.issue_url)
            meta = dict(context.metadata)
            meta["issue_title"] = item.title
            meta["issue_body"] = item.description
            meta["repo_full_name"] = item.metadata.get("repo_full_name", "")
            meta["backlog_item_id"] = item.item_id
            return context.model_copy(update={"metadata": meta})
        except Exception as exc:
            logger.warning("Could not read issue (%s); continuing without it.", exc)
            return context

    def _read_ci_run(self, context: AgentContext) -> AgentContext:
        from autodev.github.ci_intake import CIIntakeService

        try:
            intake = CIIntakeService(self.backlog_service)
            item = intake.intake(context.issue_url)
            meta = dict(context.metadata)
            meta["issue_title"] = item.title
            meta["issue_body"] = item.description
            meta["repo_full_name"] = item.metadata.get("repo_full_name", "")
            meta["backlog_item_id"] = item.item_id
            meta["run_url"] = item.metadata.get("run_url", context.issue_url)
            meta["validation_commands"] = item.metadata.get("validation_commands", [])
            return context.model_copy(update={"metadata": meta})
        except Exception as exc:
            logger.warning("Could not read CI run (%s); continuing without it.", exc)
            return context

    def _start_run(self, context: AgentContext) -> AgentContext:
        metadata = dict(context.metadata)
        backlog_item_id = metadata.get("backlog_item_id") or self._derive_backlog_item_id(
            context.issue_url
        )
        run_metadata = {"issue_url": context.issue_url}
        if metadata.get("repo_full_name"):
            run_metadata["repo_full_name"] = metadata["repo_full_name"]

        run = self.workspace_manager.create_run(
            backlog_item_id=backlog_item_id,
            isolation_mode=self.isolation_mode,
            metadata=run_metadata,
        )
        self.supervisor.configure_reporting(report_name=f"guardrails-{run.run_id}")
        metadata.update(
            {
                "run_id": run.run_id,
                "backlog_item_id": backlog_item_id,
                "workspace_path": run.workspace_path,
                "isolation_mode": run.isolation_mode.value,
            }
        )
        return context.model_copy(update={"repo_path": run.workspace_path, "metadata": metadata})

    def _clone_repo(self, context: AgentContext) -> AgentContext:
        repo_full_name = context.metadata.get("repo_full_name", "")
        if not repo_full_name:
            return context
        try:
            run_id = context.metadata.get("run_id")
            if run_id:
                path = str(self.workspace_manager.clone_repo(run_id, repo_full_name))
                run = self.state_store.load_run(run_id)
            else:
                cloner = RepoCloner()
                dest = os.path.join(self.work_dir, repo_full_name.replace("/", "_"))
                path = cloner.clone(repo_full_name, dest)
                run = None

            metadata = dict(context.metadata)
            metadata["workspace_path"] = path
            if run is not None:
                isolation_branch = run.metadata.get("isolation_branch")
                if isolation_branch:
                    metadata["isolation_branch"] = isolation_branch
            return context.model_copy(update={"repo_path": path, "metadata": metadata})
        except Exception as exc:
            logger.warning("Could not clone repo (%s); continuing.", exc)
            return context

    def _plan(self, context: AgentContext) -> AgentContext:
        updated = self._execute_phase(PhaseName.PLAN, context)
        run_id = updated.metadata.get("run_id") or context.metadata.get("run_id")
        if not run_id:
            return updated

        planning_payload = {
            "generated_at": utc_now().isoformat(),
            "issue_url": updated.issue_url,
            "plan": list(updated.plan),
            "planning_mode": updated.metadata.get("planning_mode", "fallback"),
            "likely_target_files": list(updated.metadata.get("likely_target_files", [])),
            "validation_hints": list(updated.metadata.get("validation_hints", [])),
            "acceptance_criteria": list(updated.metadata.get("acceptance_criteria", [])),
        }
        artifact_path = self.workspace_manager.save_planning_artifact(run_id, planning_payload)
        metadata = dict(updated.metadata)
        metadata["planning_artifact_path"] = str(artifact_path)
        self._stage_outputs.setdefault("plan", {}).setdefault("artifacts", [])
        if str(artifact_path) not in self._stage_outputs["plan"]["artifacts"]:
            self._stage_outputs["plan"]["artifacts"].append(str(artifact_path))
        return updated.model_copy(update={"metadata": metadata})

    def _implement(self, context: AgentContext) -> AgentContext:
        updated = self._execute_phase(PhaseName.IMPLEMENT, context)
        run_id = updated.metadata.get("run_id") or context.metadata.get("run_id")
        if not run_id:
            return updated

        artifacts = self.workspace_manager.capture_implementation_artifacts(run_id)
        files_modified = self._changed_files_from_artifact(artifacts["changed_files"])
        final_files_modified = files_modified or list(updated.files_modified)
        metadata = dict(updated.metadata)
        metadata["implementation_diff_path"] = str(artifacts["diff"])
        metadata["changed_files_path"] = str(artifacts["changed_files"])
        metadata["implementation_change_summary"] = final_files_modified
        self._stage_outputs.setdefault("implement", {}).setdefault("artifacts", [])
        for artifact in (artifacts["diff"], artifacts["changed_files"]):
            if str(artifact) not in self._stage_outputs["implement"]["artifacts"]:
                self._stage_outputs["implement"]["artifacts"].append(str(artifact))
        self._stage_outputs.setdefault("implement", {}).setdefault("metrics", {})[
            "files_modified"
        ] = len(final_files_modified)
        return updated.model_copy(
            update={
                "files_modified": final_files_modified,
                "metadata": metadata,
            }
        )

    def _validate(self, context: AgentContext) -> AgentContext:
        return self._execute_phase(PhaseName.VALIDATE, context)

    def _debug(self, context: AgentContext) -> AgentContext:
        debugger = DebuggerAgent(model_router=self.model_router)
        return debugger.run("debug validation failures", context)

    def _review(self, context: AgentContext) -> AgentContext:
        return self._execute_phase(PhaseName.REVIEW, context)

    def _promote(self, context: AgentContext) -> AgentContext:
        if not self._review_allows_promotion(context):
            metadata = dict(context.metadata)
            metadata["promotion_skipped_reason"] = self._promotion_blocked_message(context)
            self._stage_outputs["promote"] = {
                "status": "blocked",
                "message": metadata["promotion_skipped_reason"],
                "artifacts": [],
                "metrics": {
                    "review_decision": str(metadata.get("review_decision", "unknown")),
                    "promotion_mode": self._promotion_mode(context),
                },
            }
            updated = context.model_copy(update={"metadata": metadata})
            self._persist_promotion_metadata(updated)
            return updated

        promotion_mode = self._promotion_mode(context)
        metadata = dict(context.metadata)
        promotion_branch = self._promotion_branch_name(context)
        metadata["promotion_mode"] = promotion_mode
        metadata["promotion_branch"] = promotion_branch
        updated = context.model_copy(update={"metadata": metadata})

        if promotion_mode == "patch_bundle":
            patch_path = self._emit_patch_bundle(updated)
            metadata = dict(updated.metadata)
            metadata["promotion_patch_path"] = str(patch_path)
            updated = updated.model_copy(update={"metadata": metadata})
            self._stage_outputs["promote"] = {
                "status": "completed",
                "message": f"Patch bundle created at {patch_path}.",
                "artifacts": [str(patch_path)],
                "metrics": {
                    "review_decision": str(metadata.get("review_decision", "approved")),
                    "promotion_mode": promotion_mode,
                    "promotion_branch": promotion_branch,
                },
            }
            self._persist_promotion_metadata(updated)
            return updated

        updated = self._push_branch(updated)
        if promotion_mode == "branch_push":
            metadata = dict(updated.metadata)
            self._stage_outputs["promote"] = {
                "status": "completed",
                "message": f"Branch pushed: {metadata['promotion_branch']}",
                "artifacts": [],
                "metrics": {
                    "review_decision": str(metadata.get("review_decision", "approved")),
                    "promotion_mode": promotion_mode,
                    "promotion_branch": str(metadata.get("promotion_branch", "")),
                    "commit_created": bool(metadata.get("promotion_commit_created", False)),
                },
            }
            self._persist_promotion_metadata(updated)
            return updated

        metadata = dict(updated.metadata)
        metadata["promotion_pr_title"] = self._build_pr_title(updated)
        metadata["promotion_pr_body"] = self._build_pr_body(updated)
        updated = updated.model_copy(update={"metadata": metadata})
        updated = self._open_pr(updated)
        self._persist_promotion_metadata(updated)
        return updated

    def _push_branch(self, context: AgentContext) -> AgentContext:
        repo_path = self._promotion_repo_path(context)
        metadata = dict(context.metadata)
        branch_name = str(metadata.get("promotion_branch", self._promotion_branch_name(context)))
        commit_message = self._build_promotion_commit_message(context)

        self._ensure_promotion_branch(repo_path, branch_name)
        commit_created = self._commit_promotion_changes(repo_path, commit_message)
        self.workspace_manager.git_tool.push(repo_path, branch_name)

        metadata["promotion_branch"] = branch_name
        metadata["promotion_commit_message"] = commit_message
        metadata["promotion_commit_created"] = commit_created
        metadata["promotion_pushed"] = True
        return context.model_copy(update={"metadata": metadata})

    def _open_pr(self, context: AgentContext) -> AgentContext:
        if not self._review_allows_promotion(context):
            metadata = dict(context.metadata)
            metadata["promotion_skipped_reason"] = self._promotion_blocked_message(context)
            self._stage_outputs["promote"] = {
                "status": "blocked",
                "message": metadata["promotion_skipped_reason"],
                "artifacts": [],
                "metrics": {"review_decision": str(metadata.get("review_decision", "unknown"))},
            }
            return context.model_copy(update={"metadata": metadata})
        repo_full_name = context.metadata.get("repo_full_name", "")
        if not repo_full_name:
            logger.warning("No repo_full_name in context; skipping PR creation.")
            return context
        try:
            creator = PRCreator()
            title = str(context.metadata.get("promotion_pr_title", self._build_pr_title(context)))
            body = str(context.metadata.get("promotion_pr_body", self._build_pr_body(context)))
            branch_name = str(
                context.metadata.get(
                    "promotion_branch",
                    context.metadata.get("isolation_branch", "autodev/changes"),
                )
            )
            pr_url = creator.create(
                repo_full_name=repo_full_name,
                branch_name=branch_name,
                title=title,
                body=body,
            )
            meta = dict(context.metadata)
            meta["pr_url"] = pr_url
            meta["promotion_branch"] = branch_name
            meta["promotion_pr_title"] = title
            meta["promotion_pr_body"] = body
            self._stage_outputs["promote"] = {
                "status": "completed",
                "message": "Pull request opened.",
                "artifacts": [],
                "metrics": {
                    "review_decision": str(meta.get("review_decision", "approved")),
                    "promotion_mode": str(meta.get("promotion_mode", "pull_request")),
                    "promotion_branch": branch_name,
                },
            }
            console.print(f"[green]PR opened:[/green] {pr_url}")
            return context.model_copy(update={"metadata": meta})
        except Exception as exc:
            logger.warning("Could not open PR (%s).", exc)
            return context

    def _promotion_mode(self, context: AgentContext) -> str:
        raw_mode = context.metadata.get("promotion_mode")
        if raw_mode is None:
            raw_mode = context.metadata.get("promotion", {}).get("mode", "pull_request")
        candidate = str(raw_mode or "pull_request").strip().lower()
        aliases = {
            "patch": "patch_bundle",
            "patch_bundle": "patch_bundle",
            "bundle": "patch_bundle",
            "branch": "branch_push",
            "branch_push": "branch_push",
            "push": "branch_push",
            "pr": "pull_request",
            "pull_request": "pull_request",
            "pull-request": "pull_request",
        }
        return aliases.get(candidate, "pull_request")

    def _promotion_progress_message(self, promotion_mode: str) -> str:
        if promotion_mode == "patch_bundle":
            return "Creating patch bundle..."
        if promotion_mode == "branch_push":
            return "Pushing promotion branch..."
        return "Opening pull request..."

    def _promotion_branch_name(self, context: AgentContext) -> str:
        metadata = context.metadata
        existing = str(
            metadata.get("promotion_branch", metadata.get("isolation_branch", ""))
        ).strip()
        if existing:
            return existing

        raw_token = str(
            metadata.get("backlog_item_id")
            or self._derive_backlog_item_id(context.issue_url)
            or "changes"
        ).strip()
        normalized = SAFE_BACKLOG_TOKEN_PATTERN.sub("-", raw_token.lower()).strip("-._")
        return f"autodev/{normalized or 'changes'}"

    def _promotion_repo_path(self, context: AgentContext) -> str:
        repo_path = str(context.repo_path or context.metadata.get("workspace_path", "")).strip()
        if not repo_path:
            raise RuntimeError("Promotion requires a repository workspace path.")
        return repo_path

    def _emit_patch_bundle(self, context: AgentContext) -> Path:
        diff_path = str(context.metadata.get("implementation_diff_path", "")).strip()
        patch_text = ""
        if diff_path:
            try:
                patch_text = Path(diff_path).read_text(encoding="utf-8")
            except OSError:
                patch_text = ""
        if not patch_text:
            patch_text = self._git_stdout(self._promotion_repo_path(context), ["diff", "--binary"])

        run_id = str(context.metadata.get("run_id", "")).strip()
        if run_id:
            promotion_dir = self.state_store.run_dir(run_id) / "promotion"
        else:
            promotion_dir = Path(self.work_dir) / "promotion"
        promotion_dir.mkdir(parents=True, exist_ok=True)

        branch_slug = (
            SAFE_BACKLOG_TOKEN_PATTERN.sub(
                "-",
                self._promotion_branch_name(context).replace("/", "-"),
            ).strip("-._")
            or "changes"
        )
        patch_path = promotion_dir / f"{branch_slug}.patch"
        patch_path.write_text(patch_text, encoding="utf-8")
        return patch_path

    def _build_promotion_commit_message(self, context: AgentContext) -> str:
        issue_title = str(context.metadata.get("issue_title", "")).strip()
        if issue_title:
            return f"[AutoDev] {issue_title}"
        return f"[AutoDev] Apply {context.metadata.get('backlog_item_id', 'changes')}"

    def _build_pr_title(self, context: AgentContext) -> str:
        issue_title = str(context.metadata.get("issue_title", "")).strip()
        if issue_title:
            return f"[AutoDev] {issue_title}"
        files = list(context.files_modified)
        if files:
            return f"[AutoDev] Update {files[0]}"
        return f"[AutoDev] Promote {context.metadata.get('backlog_item_id', 'changes')}"

    def _build_pr_body(self, context: AgentContext) -> str:
        metadata = context.metadata
        summary = str(metadata.get("review_summary", metadata.get("review", ""))).strip()
        acceptance_criteria = [str(item) for item in metadata.get("acceptance_criteria", [])]
        files_modified = [str(path) for path in context.files_modified]
        validation_excerpt = self._validation_summary_line(context.validation_results)

        lines = ["## Summary"]
        if summary:
            lines.append(summary)
        else:
            lines.append("Automated changes generated by AutoDev.")

        if files_modified:
            lines.extend(["", "## Files Modified", *[f"- {path}" for path in files_modified]])

        if acceptance_criteria:
            lines.extend(
                ["", "## Acceptance Criteria", *[f"- {item}" for item in acceptance_criteria]]
            )

        if validation_excerpt:
            lines.extend(["", "## Validation", f"- {validation_excerpt}"])

        artifact_lines = self._promotion_artifact_lines(context)
        if artifact_lines:
            lines.extend(["", "## Run Artifacts", *artifact_lines])

        issue_url = str(context.issue_url).strip()
        if issue_url:
            lines.extend(["", "## Source", f"- Issue: {issue_url}"])

        return "\n".join(lines).strip()

    def _promotion_artifact_lines(self, context: AgentContext) -> list[str]:
        metadata = context.metadata
        artifact_keys = (
            ("planning_artifact_path", "Planning artifact"),
            ("implementation_diff_path", "Implementation diff"),
            ("changed_files_path", "Changed files manifest"),
            ("validation_result_path", "Validation result"),
            ("review_result_path", "Review result"),
        )
        lines: list[str] = []
        for key, label in artifact_keys:
            value = str(metadata.get(key, "")).strip()
            if value:
                lines.append(f"- {label}: {value}")
        return lines

    def _validation_summary_line(self, validation_results: str) -> str:
        for line in validation_results.splitlines():
            candidate = line.strip()
            if candidate:
                return candidate
        return ""

    def _persist_promotion_metadata(self, context: AgentContext) -> None:
        run_id = str(context.metadata.get("run_id", "")).strip()
        if not run_id:
            return

        promotion_snapshot = {
            "mode": self._promotion_mode(context),
            "branch": str(context.metadata.get("promotion_branch", "")).strip(),
            "patch_path": str(context.metadata.get("promotion_patch_path", "")).strip(),
            "pushed": bool(context.metadata.get("promotion_pushed", False)),
            "commit_message": str(context.metadata.get("promotion_commit_message", "")).strip(),
            "commit_created": bool(context.metadata.get("promotion_commit_created", False)),
            "pr_title": str(context.metadata.get("promotion_pr_title", "")).strip(),
            "pr_body": str(context.metadata.get("promotion_pr_body", "")).strip(),
            "pr_url": str(context.metadata.get("pr_url", "")).strip(),
            "skipped_reason": str(context.metadata.get("promotion_skipped_reason", "")).strip(),
            "recorded_at": utc_now().isoformat(),
        }

        self.state_store.update_run(
            run_id,
            lambda current: current.model_copy(
                update={
                    "metadata": {
                        **current.metadata,
                        "promotion": promotion_snapshot,
                        "promotion_branch": promotion_snapshot["branch"],
                    }
                }
            ),
        )

    def _ensure_promotion_branch(self, repo_path: str, branch_name: str) -> None:
        current_branch = self._git_stdout(repo_path, ["branch", "--show-current"]).strip()
        if current_branch == branch_name:
            return

        try:
            self._run_git(repo_path, ["checkout", branch_name])
        except RuntimeError:
            self._run_git(repo_path, ["checkout", "-b", branch_name])

    def _commit_promotion_changes(self, repo_path: str, commit_message: str) -> bool:
        status = self._git_stdout(repo_path, ["status", "--short"])
        if not status.strip():
            return False
        self.workspace_manager.git_tool.commit(repo_path, commit_message)
        return True

    def _git_stdout(self, repo_path: str, args: list[str]) -> str:
        return self._run_git(repo_path, args)

    def _run_git(self, repo_path: str, args: list[str]) -> str:
        return self.workspace_manager.git_tool.run_git(["-C", repo_path, *args])

    def _review_allows_promotion(self, context: AgentContext) -> bool:
        decision = str(context.metadata.get("review_decision", "")).strip()
        return decision == ReviewDecision.APPROVED.value

    def _promotion_blocked_message(self, context: AgentContext) -> str:
        decision = str(context.metadata.get("review_decision", "unknown")).strip() or "unknown"
        summary = str(
            context.metadata.get("review_summary", context.metadata.get("review", ""))
        ).strip()
        if summary:
            return f"Promotion blocked by review decision {decision}: {summary}"
        return f"Promotion blocked by review decision {decision}."

    @property
    def state(self) -> PipelineState:
        return self._state

    @property
    def stage_outputs(self) -> dict[str, Any]:
        return dict(self._stage_outputs)

    def reset(self) -> None:
        self._state = PipelineState.PENDING
        self._stage_outputs.clear()

    @staticmethod
    def _derive_backlog_item_id(issue_url: str) -> str:
        if not issue_url:
            return "issue-adhoc"

        parsed = urlparse(issue_url)
        path_segments = [segment for segment in parsed.path.split("/") if segment]
        raw_token = path_segments[-1] if path_segments else "adhoc"
        normalized = SAFE_BACKLOG_TOKEN_PATTERN.sub("-", raw_token.lower()).strip("-._")
        return f"issue-{normalized or 'adhoc'}"

    @staticmethod
    def _phase_task_id(context: AgentContext, phase: PhaseName) -> str:
        run_id = str(context.metadata.get("run_id", "adhoc"))
        return f"{run_id}-{phase.value}"

    @staticmethod
    def _changed_files_from_artifact(changed_files_path: os.PathLike[str] | str) -> list[str]:
        try:
            payload = json.loads(Path(changed_files_path).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        if not payload.get("success"):
            return []

        changed_files: list[str] = []
        for entry in payload.get("files", []):
            path = str(entry.get("path", "")).strip()
            if path and path not in changed_files:
                changed_files.append(path)
        return changed_files


RuntimeOrchestrator = Orchestrator
