"""AutoDev CLI: init, run, fix-ci, status commands."""

from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    name="autodev",
    help="AutoDev — AI-powered development automation",
    add_completion=True,
)
console = Console()

_CONFIG_DIR = Path.home() / ".autodev"


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
            "      - name: code\n"
            "        agent: coder\n"
            "        depends_on: [plan]\n"
            "      - name: test\n"
            "        agent: tester\n"
            "        depends_on: [code]\n"
            "      - name: review\n"
            "        agent: reviewer\n"
            "        depends_on: [test]\n"
        )

    console.print(
        Panel(
            "[bold green]AutoDev initialized![/bold green]\n"
            f"Config directory: {_CONFIG_DIR}",
            title="autodev init",
        )
    )


@app.command()
def run(
    issue_url: str = typer.Argument(..., help="GitHub issue URL to process"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Skip PR creation"),
    max_iterations: int = typer.Option(3, "--max-iterations", help="Max debug iterations"),
) -> None:
    """Run the full AutoDev pipeline for a GitHub issue."""
    from autodev.core.runtime import RuntimeOrchestrator

    console.print(f"[bold]Processing:[/bold] {issue_url}")
    try:
        orchestrator = RuntimeOrchestrator(
            max_iterations=max_iterations,
            dry_run=dry_run,
        )
        context = orchestrator.run_pipeline(issue_url)
        if context.metadata.get("pr_url"):
            console.print(f"\n[green]PR:[/green] {context.metadata['pr_url']}")
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)


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


@app.command()
def status() -> None:
    """Show current AutoDev configuration and status."""
    table = Table(show_header=False, box=None)
    table.add_column("Key", style="bold")
    table.add_column("Value")

    config_exists = _CONFIG_DIR.exists()
    table.add_row("Config dir", f"{_CONFIG_DIR} ({'exists' if config_exists else 'not found'})")

    for env_var in ("GITHUB_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        value = "[green]set[/green]" if os.environ.get(env_var) else "[red]not set[/red]"
        table.add_row(env_var, value)

    console.print(Panel(table, title="AutoDev Status"))
