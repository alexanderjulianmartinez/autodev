"""AutoDev CLI: init, run, fix-ci, status, backlog, and runs commands."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    name="autodev",
    help="AutoDev — AI-powered development automation",
    add_completion=True,
)
backlog_app = typer.Typer(help="Manage the durable backlog.")
run_app = typer.Typer(help="Start or resume pipeline runs.")
app.add_typer(backlog_app, name="backlog")
app.add_typer(run_app, name="run")

console = Console()

_CONFIG_DIR = Path.home() / ".autodev"
_DEFAULT_STATE_DIR = _CONFIG_DIR / "state"
_SLUG_RE = re.compile(r"[^a-z0-9._-]+")

_PRIORITY_MAP = {
    "p0": "critical",
    "p1": "high",
    "p2": "medium",
    "p3": "low",
}


def _state_dir(work_dir: Optional[str]) -> str:
    if work_dir:
        return work_dir
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    return str(_DEFAULT_STATE_DIR)


def _make_orchestrator(
    work_dir: Optional[str] = None,
    max_iterations: int = 3,
    dry_run: bool = False,
):
    from autodev.core.runtime import Orchestrator

    return Orchestrator(
        max_iterations=max_iterations,
        dry_run=dry_run,
        work_dir=_state_dir(work_dir),
    )


def _make_backlog_service(work_dir: Optional[str] = None):
    from autodev.core.backlog_service import BacklogService
    from autodev.core.state_store import FileStateStore

    return BacklogService(FileStateStore(_state_dir(work_dir)))


def _slugify(text: str, max_len: int = 50) -> str:
    return _SLUG_RE.sub("-", text.lower().strip())[:max_len].strip("-")


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@app.command()
def init() -> None:
    """Initialize AutoDev configuration directory."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    models_yaml = _CONFIG_DIR / "models.yaml"
    if not models_yaml.exists():
        models_yaml.write_text(
            "models:\n"
            "  planner: claude-sonnet\n"
            "  coder: gpt-4.1\n"
            "  reviewer: claude-opus\n"
            "  debugger: gpt-4.1\n"
            "  default: gpt-4.1\n"
        )

    pipelines_yaml = _CONFIG_DIR / "pipelines.yaml"
    if not pipelines_yaml.exists():
        pipelines_yaml.write_text(
            "pipelines:\n"
            "  default:\n"
            "    name: minimal\n"
            "    max_iterations: 3\n"
            "    stages:\n"
            "      - name: plan\n"
            "        agent: planner\n"
            "      - name: implement\n"
            "        agent: implementer\n"
            "        depends_on: [plan]\n"
            "      - name: validate\n"
            "        agent: validator\n"
            "        depends_on: [implement]\n"
            "      - name: review\n"
            "        agent: reviewer\n"
            "        depends_on: [validate]\n"
        )

    console.print(
        Panel(
            f"[bold green]AutoDev initialized![/bold green]\nConfig directory: {_CONFIG_DIR}",
            title="autodev init",
        )
    )


# ---------------------------------------------------------------------------
# run (top-level shorthand — kept for backwards compatibility)
# ---------------------------------------------------------------------------


@app.command()
def run(
    issue_url: str = typer.Argument(..., help="GitHub issue URL to process"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Skip PR creation"),
    max_iterations: int = typer.Option(3, "--max-iterations", help="Max debug iterations"),
    work_dir: Optional[str] = typer.Option(None, "--work-dir", help="State directory"),
) -> None:
    """Run the full AutoDev pipeline for a GitHub issue."""
    _run_issue(issue_url, dry_run=dry_run, max_iterations=max_iterations, work_dir=work_dir)


# ---------------------------------------------------------------------------
# fix-ci
# ---------------------------------------------------------------------------


@app.command(name="fix-ci")
def fix_ci(
    run_url: str = typer.Argument(..., help="GitHub Actions run URL to fix"),
) -> None:
    """Read CI logs and attempt to patch code (stub)."""
    console.print(
        Panel(
            f"[yellow]fix-ci is not yet implemented.[/yellow]\n\n"
            f"Run URL: {run_url}\n\n"
            "This command will:\n"
            "  1. Read CI failure logs\n"
            "  2. Identify the failing code\n"
            "  3. Generate a patch\n"
            "  4. Open a pull request",
            title="autodev fix-ci",
        )
    )


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status() -> None:
    """Show current AutoDev configuration and status."""
    table = Table(show_header=False, box=None)
    table.add_column("Key", style="bold")
    table.add_column("Value")

    config_exists = _CONFIG_DIR.exists()
    table.add_row("Config dir", f"{_CONFIG_DIR} ({'exists' if config_exists else 'not found'})")
    table.add_row("State dir", str(_DEFAULT_STATE_DIR))

    for env_var in ("GITHUB_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        value = "[green]set[/green]" if os.environ.get(env_var) else "[red]not set[/red]"
        table.add_row(env_var, value)

    console.print(Panel(table, title="AutoDev Status"))


# ---------------------------------------------------------------------------
# runs show
# ---------------------------------------------------------------------------


@app.command(name="runs")
def runs_show(
    run_id: Optional[str] = typer.Argument(None, help="Run ID to inspect (omit to list all)"),
    work_dir: Optional[str] = typer.Option(None, "--work-dir", help="State directory"),
) -> None:
    """List all runs or show details for a specific run."""
    from autodev.core.state_store import FileStateStore

    store = FileStateStore(_state_dir(work_dir))

    if run_id:
        try:
            run_meta = store.load_run(run_id)
        except FileNotFoundError:
            console.print(f"[red]Run not found:[/red] {run_id}")
            raise typer.Exit(code=1) from None

        table = Table(show_header=False, box=None)
        table.add_column("Field", style="bold")
        table.add_column("Value")
        table.add_row("Run ID", run_meta.run_id)
        table.add_row("Backlog item", run_meta.backlog_item_id)
        table.add_row("Status", run_meta.status.value)
        table.add_row("Isolation", run_meta.isolation_mode.value)
        table.add_row("Workspace", run_meta.workspace_path or "—")
        table.add_row("Created", run_meta.created_at.isoformat())
        if run_meta.started_at:
            table.add_row("Started", run_meta.started_at.isoformat())
        if run_meta.completed_at:
            table.add_row("Completed", run_meta.completed_at.isoformat())
        issue_url = run_meta.metadata.get("issue_url", "")
        if issue_url:
            table.add_row("Issue", issue_url)
        pr_url = run_meta.metadata.get("pr_url", "")
        if pr_url:
            table.add_row("PR", pr_url)
        console.print(Panel(table, title=f"Run {run_meta.run_id}"))
    else:
        run_list = store.list_runs()
        if not run_list:
            console.print("[dim]No runs found.[/dim]")
            return

        table = Table(title="Runs", show_lines=False)
        table.add_column("Run ID", style="cyan")
        table.add_column("Backlog item")
        table.add_column("Status")
        table.add_column("Created")
        table.add_column("Issue / PR")
        for r in sorted(run_list, key=lambda x: x.created_at, reverse=True):
            link = r.metadata.get("pr_url") or r.metadata.get("issue_url") or "—"
            status_color = {
                "completed": "green",
                "failed": "red",
                "running": "yellow",
            }.get(r.status.value, "dim")
            table.add_row(
                r.run_id,
                r.backlog_item_id,
                f"[{status_color}]{r.status.value}[/{status_color}]",
                r.created_at.strftime("%Y-%m-%d %H:%M"),
                link,
            )
        console.print(table)


# ---------------------------------------------------------------------------
# backlog sub-commands
# ---------------------------------------------------------------------------


@backlog_app.command(name="add")
def backlog_add(
    title: str = typer.Argument(..., help="Short title for the backlog item"),
    description: str = typer.Option("", "--description", "-d", help="Longer description"),
    priority: str = typer.Option(
        "p2",
        "--priority",
        "-p",
        help="Priority: p0 (critical), p1 (high), p2 (medium), p3 (low)",
    ),
    label: Optional[list[str]] = typer.Option(  # noqa: B008
        None, "--label", "-l", help="Label (repeatable)"
    ),
    criterion: Optional[list[str]] = typer.Option(  # noqa: B008
        None, "--criterion", "-c", help="Acceptance criterion (repeatable)"
    ),
    work_dir: Optional[str] = typer.Option(None, "--work-dir", help="State directory"),
) -> None:
    """Create a new backlog item."""
    from autodev.core.schemas import PriorityLevel

    priority_key = priority.lower().strip()
    priority_map: dict[str, PriorityLevel] = {
        "p0": PriorityLevel.CRITICAL,
        "p1": PriorityLevel.HIGH,
        "p2": PriorityLevel.MEDIUM,
        "p3": PriorityLevel.LOW,
        "critical": PriorityLevel.CRITICAL,
        "high": PriorityLevel.HIGH,
        "medium": PriorityLevel.MEDIUM,
        "low": PriorityLevel.LOW,
    }
    if priority_key not in priority_map:
        console.print(
            f"[red]Unknown priority:[/red] {priority!r}. "
            "Use p0/p1/p2/p3 or critical/high/medium/low."
        )
        raise typer.Exit(code=1)

    item_id = f"item-{_slugify(title)}"
    svc = _make_backlog_service(work_dir)

    if svc.exists(item_id):
        console.print(f"[yellow]Item already exists:[/yellow] {item_id}")
        raise typer.Exit(code=1)

    try:
        item = svc.create_item(
            item_id=item_id,
            title=title,
            description=description,
            priority=priority_map[priority_key],
            labels=list(label or []),
            acceptance_criteria=list(criterion or []),
        )
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    table = Table(show_header=False, box=None)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("ID", item.item_id)
    table.add_row("Title", item.title)
    table.add_row("Priority", item.priority.value)
    table.add_row("Status", item.status.value)
    if item.labels:
        table.add_row("Labels", ", ".join(item.labels))
    if item.acceptance_criteria:
        table.add_row("Criteria", "\n".join(f"• {c}" for c in item.acceptance_criteria))
    console.print(Panel(table, title="[green]Backlog item created[/green]"))


@backlog_app.command(name="list")
def backlog_list(
    status: Optional[str] = typer.Option(
        None,
        "--status",
        "-s",
        help="Filter by status: planned, active, blocked, completed",
    ),
    work_dir: Optional[str] = typer.Option(None, "--work-dir", help="State directory"),
) -> None:
    """List backlog items."""
    from autodev.core.schemas import BacklogStatus

    svc = _make_backlog_service(work_dir)

    status_filter = None
    if status:
        try:
            status_filter = BacklogStatus(status.lower())
        except ValueError:
            console.print(
                f"[red]Unknown status:[/red] {status!r}. Use: planned, active, blocked, completed."
            )
            raise typer.Exit(code=1) from None

    items = svc.list_items(status=status_filter)
    if not items:
        console.print("[dim]No backlog items found.[/dim]")
        return

    table = Table(title="Backlog", show_lines=False)
    table.add_column("ID", style="cyan")
    table.add_column("Title")
    table.add_column("Priority")
    table.add_column("Status")
    table.add_column("Labels")
    for item in sorted(items, key=lambda x: (x.priority.value, x.created_at)):
        status_color = {
            "completed": "green",
            "active": "yellow",
            "blocked": "red",
            "planned": "dim",
        }.get(item.status.value, "dim")
        table.add_row(
            item.item_id,
            item.title,
            item.priority.value,
            f"[{status_color}]{item.status.value}[/{status_color}]",
            ", ".join(item.labels) or "—",
        )
    console.print(table)


# ---------------------------------------------------------------------------
# run sub-commands
# ---------------------------------------------------------------------------


@run_app.command(name="start")
def run_start(
    issue_url: str = typer.Argument(..., help="GitHub issue URL to process"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Skip PR creation"),
    max_iterations: int = typer.Option(3, "--max-iterations", help="Max debug iterations"),
    work_dir: Optional[str] = typer.Option(None, "--work-dir", help="State directory"),
) -> None:
    """Start a new pipeline run for a GitHub issue."""
    _run_issue(issue_url, dry_run=dry_run, max_iterations=max_iterations, work_dir=work_dir)


@run_app.command(name="resume")
def run_resume(
    run_id: str = typer.Argument(..., help="Run ID to resume"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Skip PR creation"),
    max_iterations: int = typer.Option(3, "--max-iterations", help="Max debug iterations"),
    work_dir: Optional[str] = typer.Option(None, "--work-dir", help="State directory"),
) -> None:
    """Resume an interrupted pipeline run."""
    console.print(f"[bold]Resuming run:[/bold] {run_id}")
    orchestrator = _make_orchestrator(work_dir, max_iterations=max_iterations, dry_run=dry_run)
    try:
        context = orchestrator.resume_pipeline(run_id)
        if context.metadata.get("pr_url"):
            console.print(f"\n[green]PR:[/green] {context.metadata['pr_url']}")
    except FileNotFoundError:
        console.print(f"[red]Run not found:[/red] {run_id}")
        raise typer.Exit(code=1) from None
    except ValueError as exc:
        console.print(f"[red]Cannot resume:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _run_issue(
    issue_url: str,
    *,
    dry_run: bool,
    max_iterations: int,
    work_dir: Optional[str],
) -> None:
    console.print(f"[bold]Processing:[/bold] {issue_url}")
    orchestrator = _make_orchestrator(work_dir, max_iterations=max_iterations, dry_run=dry_run)
    try:
        context = orchestrator.run_pipeline(issue_url)
        if context.metadata.get("pr_url"):
            console.print(f"\n[green]PR:[/green] {context.metadata['pr_url']}")
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
