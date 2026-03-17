"""RuntimeOrchestrator: top-level pipeline coordinator."""

from __future__ import annotations

import logging
import os
import tempfile

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from autodev.agents.base import AgentContext
from autodev.agents.coder import CoderAgent
from autodev.agents.debugger import DebuggerAgent
from autodev.agents.planner import PlannerAgent
from autodev.agents.reviewer import ReviewerAgent
from autodev.core.supervisor import Supervisor
from autodev.core.task_graph import TaskGraph
from autodev.github.issue_reader import IssueReader
from autodev.github.pr_creator import PRCreator
from autodev.github.repo_cloner import RepoCloner
from autodev.models.router import ModelRouter
from autodev.tools.test_runner import TestRunner

logger = logging.getLogger(__name__)
console = Console()


class RuntimeOrchestrator:
    """Coordinates the full autodev pipeline for a GitHub issue."""

    def __init__(
        self,
        max_iterations: int = 3,
        dry_run: bool = False,
        work_dir: str | None = None,
    ) -> None:
        self.supervisor = Supervisor(max_iterations=max_iterations)
        self.task_graph = TaskGraph.default_pipeline()
        self.model_router = ModelRouter()
        self.dry_run = dry_run
        self.work_dir = work_dir or tempfile.mkdtemp(prefix="autodev_")

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run_pipeline(self, issue_url: str) -> AgentContext:
        """Execute the full issue → plan → code → test → PR pipeline."""
        console.print(Panel(f"[bold cyan]AutoDev Pipeline[/bold cyan]\n{issue_url}", expand=False))

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
            progress.update(task, completed=True)

            # 2. Clone repo
            progress.update(task, description="Cloning repository...")
            context = self._clone_repo(context)

            # 3. Plan
            progress.update(task, description="Generating plan...")
            context = self._plan(context)
            console.print(f"[green]Plan:[/green] {len(context.plan)} step(s)")

            # 4. Code → Test loop
            for iteration in range(self.supervisor.max_iterations):
                progress.update(task, description=f"Writing code (iteration {iteration + 1})...")
                context = self._code(context)

                progress.update(task, description="Running tests...")
                context = self._test(context)

                if "PASSED" in context.test_results or context.test_results == "":
                    break

                progress.update(task, description="Debugging failures...")
                context = self._debug(context)
                self.supervisor.increment()
                if self.supervisor.check_iteration_limit():
                    logger.warning("Max iterations reached; proceeding with current state.")
                    break

            # 5. Review
            progress.update(task, description="Reviewing changes...")
            context = self._review(context)

            # 6. Open PR
            if not self.dry_run:
                progress.update(task, description="Opening pull request...")
                context = self._open_pr(context)
            else:
                console.print("[yellow]Dry run: skipping PR creation[/yellow]")

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

    def _clone_repo(self, context: AgentContext) -> AgentContext:
        repo_full_name = context.metadata.get("repo_full_name", "")
        if not repo_full_name:
            return context
        try:
            cloner = RepoCloner()
            dest = os.path.join(self.work_dir, repo_full_name.replace("/", "_"))
            path = cloner.clone(repo_full_name, dest)
            return context.model_copy(update={"repo_path": path})
        except Exception as exc:
            logger.warning("Could not clone repo (%s); continuing.", exc)
            return context

    def _plan(self, context: AgentContext) -> AgentContext:
        planner = PlannerAgent(model_router=self.model_router)
        return planner.run("generate plan", context)

    def _code(self, context: AgentContext) -> AgentContext:
        coder = CoderAgent(model_router=self.model_router)
        return coder.run("implement plan", context)

    def _test(self, context: AgentContext) -> AgentContext:
        runner = TestRunner()
        repo_path = context.repo_path or self.work_dir
        result = runner.run(repo_path)
        status = "PASSED" if result.passed else "FAILED"
        output = f"{status}\n{result.output}\n{result.error}".strip()
        return context.model_copy(update={"test_results": output})

    def _debug(self, context: AgentContext) -> AgentContext:
        debugger = DebuggerAgent(model_router=self.model_router)
        return debugger.run("debug failures", context)

    def _review(self, context: AgentContext) -> AgentContext:
        reviewer = ReviewerAgent(model_router=self.model_router)
        return reviewer.run("review changes", context)

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
