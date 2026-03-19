# AutoDev

AutoDev is an open-source, model-agnostic autonomous engineering runtime.

It is designed for people who want a coding agent runtime that is structured, inspectable, and safe by default rather than a loose chat loop. The project is currently focused on building the durable local runtime foundations: backlog items, task materialization, deterministic scheduling, retry handling, and persistent execution state.

## Who this is for

- contributors building the runtime itself
- developers exploring autonomous software delivery workflows
- operators who want inspectable runs, artifacts, and retry history

## What AutoDev does

AutoDev turns a change request into a bounded execution flow:

`request -> plan -> implement -> validate -> review -> approve/merge -> record state`

The runtime is being built around a few core ideas:

- durable backlog items instead of one-off prompts
- deterministic task scheduling instead of free-form loops
- explicit validation and review phases
- persisted run/task state for resume and auditability
- safe execution primitives that can later support snapshots and isolated workspaces

## Current status

This repository is still early and documentation-first, but the runtime foundation work is underway.

Implemented so far:

- durable Pydantic schemas for backlog, tasks, runs, validation, review, and retry history
- file-backed state storage with atomic JSON writes
- backlog service with dependency validation
- task materialization for `plan -> implement -> validate -> review`
- deterministic scheduler with bounded retry/backoff handling
- local developer automation via `Makefile`, `pre-commit`, Ruff, and GitHub Actions

Still in progress:

- workspace isolation and snapshots
- formal phase registry and execution contracts
- targeted validation engine
- structured review and promotion workflows

## Quick start

### Requirements

- Python 3.10+
- Git

### Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

### Initialize local config

```bash
autodev init
```

### Useful commands

```bash
make lint
make test
make pre-commit
```

Or directly:

```bash
python -m pytest
python -m ruff check .
python -m pre_commit run --all-files
```

## Project layout

- `autodev/core`: runtime foundations such as schemas, state store, backlog service, materializer, and scheduler
- `autodev/agents`: current planner/coder/reviewer/debugger scaffolding
- `autodev/tools`: filesystem, shell, git, and validation helpers
- `autodev/github`: issue intake, repo clone, and PR helpers
- `tests`: focused unit tests for the runtime foundation layers
- `docs`: design documents, backlog tracking, and technical specs

## Documentation

- System design: [system_design.md](system_design.md)
- Architecture inventory: [docs/architecture_inventory.md](docs/architecture_inventory.md)
- Implementation backlog: [backlog.md](backlog.md)
- Runtime tech spec v0.1: [docs/tech_spec_v01.md](docs/tech_spec_v01.md)
- Runtime expansion spec v0.2: [docs/tech_spec_v02.md](docs/tech_spec_v02.md)

## Contributing

Contributions are welcome, especially in the current MVP path:

- workspace isolation and snapshotting
- validation engine improvements
- phase registry and handler contracts
- review/promotion workflows
- CLI productization

Before opening a PR:

```bash
make ci
```

If you are picking up runtime work, the best place to start is the backlog and architecture docs, then the tests around the relevant subsystem.
