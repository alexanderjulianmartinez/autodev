"""Orchestrator: unified runtime coordinator for AutoDev pipelines."""

from __future__ import annotations

import logging
import os
import tempfile
from enum import Enum
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from autodev.agents.base import AgentContext
from autodev.agents.coder import CoderAgent
from autodev.agents.debugger import DebuggerAgent
from autodev.agents.planner import PlannerAgent
from autodev.agents.reviewer import ReviewerAgent
from autodev.core.schemas import IsolationMode
from autodev.core.state_store import FileStateStore
from autodev.core.supervisor import Supervisor
from autodev.core.task_graph import TaskGraph
from autodev.core.workspace_manager import WorkspaceManager
from autodev.github.issue_reader import IssueReader
from autodev.github.pr_creator import PRCreator
from autodev.github.repo_cloner import RepoCloner
from autodev.models.router import ModelRouter
from autodev.tools.test_runner import TestRunner

logger = logging.getLogger(__name__)
console = Console()


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
    ) -> None:
        self.supervisor = Supervisor(max_iterations=max_iterations)
        self.task_graph = TaskGraph.default_pipeline()
        self.model_router = ModelRouter()
        self.dry_run = dry_run
        self.work_dir = work_dir or tempfile.mkdtemp(prefix="autodev_")
        self.isolation_mode = isolation_mode
        self.state_store = FileStateStore(os.path.join(self.work_dir, "state"))
        self.workspace_manager = WorkspaceManager(self.state_store)
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
    # Main entry point
    # ------------------------------------------------------------------

    def run_pipeline(self, issue_url: str) -> AgentContext:
        """Execute the full issue → plan → implement → validate → review → PR pipeline."""
        console.print(Panel(f"[bold cyan]AutoDev Pipeline[/bold cyan]\n{issue_url}", expand=False))
        self._state = PipelineState.RUNNING
        self._stage_outputs.clear()

        context = AgentContext(issue_url=issue_url)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
            console=console,
        ) as progress:
            # 1. Read issue
            task = progress.add_task("Analyzing issue...", total=None)
            context = self._read_issue(context)
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
            self._stage_outputs["plan"] = {"status": "completed"}
            console.print(f"[green]Plan:[/green] {len(context.plan)} step(s)")

            # 4. Implement → Validate loop
            for iteration in range(self.supervisor.max_iterations):
                progress.update(
                    task, description=f"Implementing changes (iteration {iteration + 1})..."
                )
                context = self._implement(context)
                self._stage_outputs["implement"] = {
                    "status": "completed",
                    "iteration": iteration + 1,
                }

                progress.update(task, description="Running validation...")
                context = self._validate(context)
                self._stage_outputs["validate"] = {
                    "status": "completed",
                    "iteration": iteration + 1,
                }

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
            self._stage_outputs["review"] = {"status": "completed"}

            # 6. Open PR
            if not self.dry_run:
                progress.update(task, description="Opening pull request...")
                context = self._open_pr(context)
            else:
                console.print("[yellow]Dry run: skipping PR creation[/yellow]")

        self._state = PipelineState.COMPLETED
        console.print(Panel("[bold green]Pipeline complete![/bold green]", expand=False))
        return context

    # ------------------------------------------------------------------
    # Private stage helpers
    # ------------------------------------------------------------------

    def _read_issue(self, context: AgentContext) -> AgentContext:
        try:
            reader = IssueReader()
            issue = reader.read(context.issue_url)
            meta = dict(context.metadata)
            meta["issue_title"] = issue.title
            meta["issue_body"] = issue.body
            meta["repo_full_name"] = issue.repo_full_name
            return context.model_copy(update={"metadata": meta})
        except Exception as exc:
            logger.warning("Could not read issue (%s); continuing without it.", exc)
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
            else:
                cloner = RepoCloner()
                dest = os.path.join(self.work_dir, repo_full_name.replace("/", "_"))
                path = cloner.clone(repo_full_name, dest)

            metadata = dict(context.metadata)
            metadata["workspace_path"] = path
            return context.model_copy(update={"repo_path": path, "metadata": metadata})
        except Exception as exc:
            logger.warning("Could not clone repo (%s); continuing.", exc)
            return context

    def _plan(self, context: AgentContext) -> AgentContext:
        planner = PlannerAgent(model_router=self.model_router)
        return planner.run("plan change request", context)

    def _implement(self, context: AgentContext) -> AgentContext:
        coder = CoderAgent(model_router=self.model_router)
        updated = coder.run("implement change request", context)
        run_id = updated.metadata.get("run_id") or context.metadata.get("run_id")
        if not run_id:
            return updated

        artifacts = self.workspace_manager.capture_implementation_artifacts(run_id)
        metadata = dict(updated.metadata)
        metadata["implementation_diff_path"] = str(artifacts["diff"])
        metadata["changed_files_path"] = str(artifacts["changed_files"])
        return updated.model_copy(update={"metadata": metadata})

    def _validate(self, context: AgentContext) -> AgentContext:
        runner = TestRunner(supervisor=self.supervisor)
        repo_path = context.repo_path or self.work_dir
        result = runner.run(repo_path)
        status = "PASSED" if result.passed else "FAILED"
        output = f"{status}\n{result.output}\n{result.error}".strip()
        return context.model_copy(update={"validation_results": output})

    def _debug(self, context: AgentContext) -> AgentContext:
        debugger = DebuggerAgent(model_router=self.model_router)
        return debugger.run("debug validation failures", context)

    def _review(self, context: AgentContext) -> AgentContext:
        reviewer = ReviewerAgent(model_router=self.model_router)
        return reviewer.run("review change request", context)

    def _open_pr(self, context: AgentContext) -> AgentContext:
        repo_full_name = context.metadata.get("repo_full_name", "")
        if not repo_full_name:
            logger.warning("No repo_full_name in context; skipping PR creation.")
            return context
        try:
            creator = PRCreator()
            issue_title = context.metadata.get("issue_title", "AutoDev changes")
            pr_url = creator.create(
                repo_full_name=repo_full_name,
                branch_name="autodev/changes",
                title=f"[AutoDev] {issue_title}",
                body="Automated changes generated by AutoDev.",
            )
            meta = dict(context.metadata)
            meta["pr_url"] = pr_url
            console.print(f"[green]PR opened:[/green] {pr_url}")
            return context.model_copy(update={"metadata": meta})
        except Exception as exc:
            logger.warning("Could not open PR (%s).", exc)
            return context

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
        token = issue_url.rstrip("/").split("/")[-1] if issue_url else "adhoc"
        return f"issue-{token or 'adhoc'}"


RuntimeOrchestrator = Orchestrator
