# AutoDev

AutoDev is an open-source, model-agnostic autonomous engineering runtime.

It turns GitHub issues and failed CI runs into bounded, durable execution flows: each run goes through a formal plan → implement → validate → review → promote pipeline with persisted artifacts at every phase.

## Who this is for

- contributors building or extending the runtime itself
- developers exploring autonomous software delivery workflows
- operators who want inspectable runs, structured artifacts, and retry history

## What AutoDev does

AutoDev turns a change request into a bounded execution flow:

```
request → plan → implement → validate → review → promote (PR) → record artifacts
```

Each pipeline run is a durable, resumable unit. Every phase writes structured JSON artifacts. If a run is interrupted, it can be resumed from the last successful phase.

## Quick start

### Requirements

- Python 3.9+
- Git
- Optional: `GITHUB_TOKEN` for issue intake and PR creation

### Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

### Initialize local config

```bash
autodev init
```

This creates `~/.autodev/` with `models.yaml` and `pipeline.yaml` configuration files.

### Run the pipeline for a GitHub issue

```bash
autodev run https://github.com/owner/repo/issues/42
```

### Fix a failed CI run

```bash
autodev fix-ci https://github.com/owner/repo/actions/runs/12345
```

### Useful commands

```bash
make install-dev   # install dev dependencies
make lint          # ruff check
make format        # ruff format
make test          # pytest
make ci            # lint + format-check + test

pytest tests/test_core.py -v              # single file
pytest tests/test_config.py::TestPipelineConfigLoad -v  # single class
```

## Project layout

```
autodev/
  cli/          Typer CLI: init, run, fix-ci, status, backlog, runs
  core/
    config.py           PipelineConfig: YAML-backed runtime configuration
    runtime.py          Orchestrator: pipeline coordinator
    schemas.py          Pydantic models for all durable state
    state_store.py      File-backed persistence with atomic JSON writes
    phase_registry.py   PhaseHandler ABC and concrete handlers
    task_graph.py       DAG, Kahn scheduling, retry/backoff policy
    backlog_service.py  Backlog CRUD and dependency tracking
    task_materializer.py  Expands BacklogItems into phase TaskRecords
    workspace_manager.py  Per-run isolation (snapshot/branch/worktree)
    failure_classifier.py Maps errors to FailureClass for retry decisions
    supervisor.py       Safety guardrails (shell blocklist, path policy)
    run_reporter.py     Writes summary.json/md and global history reports
  agents/       Phase implementations: planner, coder, reviewer, debugger
  tools/        Low-level tools: filesystem, shell, git, test_runner
  github/       Adapters: issue_intake, ci_intake, repo_cloner, pr_creator
  models/       ModelRouter and provider adapters (OpenAI, Anthropic, Google)

configs/        Documented reference pipeline.yaml
tests/          Unit and E2E tests (329 tests)
docs/           Design documents and architecture inventory
```

## Configuration

AutoDev looks for a config file in this order:

1. `./autodev.yaml` (project-level)
2. `~/.autodev/pipeline.yaml` (user-level)
3. Built-in safe defaults

All config values are optional. See `configs/pipeline.yaml` for the full reference with documentation.

Key settings:

```yaml
isolation_mode: snapshot    # snapshot | branch | worktree
max_iterations: 3
dry_run: false
validation:
  breadth: targeted         # targeted | broader-fallback
  stop_on_first_failure: true
  commands: []              # empty = auto-detect
retry:
  max_retries: 0
  backoff_base: 2.0
```

You can also override any setting via CLI flags:

```bash
autodev run https://... --isolation-mode branch --max-iterations 5 --dry-run
autodev run https://... --config ./my-project.yaml
```

## Architecture

The `Orchestrator` (`autodev/core/runtime.py`) drives the pipeline. Each phase is a `PhaseHandler` registered in `PhaseRegistry` (`autodev/core/phase_registry.py`). All phase inputs and outputs use stable Pydantic models (`PhaseExecutionPayload` / `PhaseExecutionResult`), keeping agent implementations decoupled from the coordinator.

State is persisted to `~/.autodev/state/` (or `--work-dir`) after every phase. The directory layout:

```
state/
  backlog/     BacklogItem JSON files
  tasks/       TaskRecord JSON files
  runs/        per-run directories with summary.json + summary.md
  reports/     global validation-history.json and failure-history.json
  scheduler/   guardrail session logs
```

For a deeper dive see:

- [system_design.md](system_design.md) — design goals and subsystem contracts
- [docs/architecture_inventory.md](docs/architecture_inventory.md) — package-level disposition map
- [docs/tech_spec_v02.md](docs/tech_spec_v02.md) — runtime expansion spec

## Documentation

- System design: [system_design.md](system_design.md)
- Architecture inventory: [docs/architecture_inventory.md](docs/architecture_inventory.md)
- Implementation backlog: [backlog.md](backlog.md)
- Runtime tech spec v0.1: [docs/tech_spec_v01.md](docs/tech_spec_v01.md)
- Runtime expansion spec v0.2: [docs/tech_spec_v02.md](docs/tech_spec_v02.md)
- Contributing guide: [CONTRIBUTING.md](CONTRIBUTING.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, testing strategy, and how to write good backlog items.

Before opening a PR:

```bash
make ci
```
