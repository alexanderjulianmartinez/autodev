# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
make install-dev   # Install dev dependencies
make lint          # Run ruff check
make format        # Format code with ruff
make test          # Run pytest
make ci            # Full CI chain: lint + format-check + test
```

Run a single test file:
```bash
pytest tests/test_core.py -v
```

Run a single test by name:
```bash
pytest tests/test_core.py::test_function_name -v
```

Pre-commit runs ruff (check + format) automatically on staged files. To run manually:
```bash
make pre-commit
```

## Architecture

AutoDev is a **model-agnostic autonomous engineering runtime** that turns code change requests (GitHub issues) into bounded, durable execution flows.

### Execution Flow

```
GitHub Issue → Plan → Implement → Validate → Review → Promote (PR)
```

The `Orchestrator` (`autodev/core/runtime.py`) coordinates the full pipeline. Each stage is a formal **phase** executed by a `PhaseHandler` registered in `PhaseRegistry` (`autodev/core/phase_registry.py`).

### Core Subsystems

**`autodev/core/`** — the runtime foundation:
- `schemas.py` — Pydantic models for all durable state: `BacklogItem`, `TaskRecord`, `RunMetadata`, `ValidationResult`, `ReviewResult`, `FailureDetail`
- `state_store.py` — file-backed persistence with atomic JSON writes; directory layout: `backlog/`, `tasks/`, `runs/`, `reports/`, `scheduler/`
- `phase_registry.py` — `PhaseHandler` ABC with concrete handlers for plan/implement/validate/review phases; all phases receive a normalized `PhaseExecutionPayload` and return a `PhaseExecutionResult`
- `task_graph.py` — DAG representation with Kahn's topological ordering; `TaskScheduler` handles deterministic selection, retry policy, and backoff
- `workspace_manager.py` — per-run isolation with snapshot/restore for rollback; isolation modes: SNAPSHOT, BRANCH, WORKTREE
- `failure_classifier.py` — maps errors to `FailureClass`: retryable, validation_failure, policy_failure, environment_failure, manual_intervention
- `supervisor.py` — safety guardrails blocking destructive shell commands and writes to sensitive paths
- `backlog_service.py` — backlog CRUD and dependency tracking
- `task_materializer.py` — expands `BacklogItem` records into phase `TaskRecord`s

**`autodev/agents/`** — phase implementations called by the registry handlers:
- `planner.py` — analyzes repo, extracts target files, generates structured plan
- `coder.py` — applies code changes and captures diffs
- `reviewer.py` — checks acceptance criteria, scans for secrets, applies policy gates
- `debugger.py` — failure analysis and repair attempts

**`autodev/tools/`** — low-level utilities used by agents:
- `filesystem_tool.py`, `shell_tool.py`, `git_tool.py`, `test_runner.py`

**`autodev/github/`** — integration adapters for reading issues, cloning repos, and creating PRs.

**`autodev/models/`** — provider routing (`ModelRouter`) with adapters for OpenAI, Anthropic, and Google.

**`autodev/cli/`** — Typer CLI entry point with commands: `init`, `run`, `fix-ci`, `status`.

### Key Design Constraints

- **Durable state over transient context**: all phase outputs are persisted as structured files; this enables resumability and auditability.
- **Phase contracts are strict**: `PhaseExecutionPayload → PhaseExecutionResult` is the only interface between the registry and agents — don't bypass it.
- **Supervisor guardrails are not optional**: the `Supervisor` blocks destructive operations; agents must go through `ShellTool` and `FilesystemTool`, not raw subprocess calls.
- **`AgentContext`** (in `agents/base.py`) is the legacy transient context being replaced by the durable schema layer — new work should use `PhaseExecutionPayload`/`PhaseExecutionResult`.
- **`autodev/core/orchestrator.py`** is a compatibility shim for the legacy `Orchestrator` name — new work targets `autodev/core/runtime.py`.
