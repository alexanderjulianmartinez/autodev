# Copilot instructions for AutoDev

## Big picture
- AutoDev is a durable, phase-based runtime that turns a GitHub issue or failed CI run into `plan -> implement -> validate -> review -> promote`.
- The real coordinator is `autodev/core/runtime.py` (`Orchestrator`). Prefer this over the legacy compatibility surface in `autodev/core/orchestrator.py`.
- Runtime phases are formal contracts in `autodev/core/phase_registry.py`: phase handlers take `PhaseExecutionPayload` and return `PhaseExecutionResult`.
- `autodev/agents/` contains phase implementations, but the durable boundary lives in `autodev/core/schemas.py` and `phase_registry.py`.
- `autodev/agents/base.py` still defines `AgentContext` and is used throughout the runtime, but new orchestration behavior should preserve the `PhaseExecutionPayload`/`PhaseExecutionResult` boundary instead of inventing new ad hoc context passing.

## Durable state and artifacts
- Persistent state is a core design choice, not an implementation detail. `autodev/core/state_store.py` writes atomic JSON files for backlog items, tasks, runs, validation results, review results, and reports.
- A run gets its own directory under `state/runs/<run_id>/` with `metadata.json`, `task_results/`, `validation/`, `reviews/`, `workspace/`, `artifacts/`, and optional `quarantine/`.
- If you change runtime schemas in `autodev/core/schemas.py`, also inspect `state_store.py`, `runtime.py`, and tests that assert persisted payload shapes.
- Follow existing strict-model patterns: runtime models inherit from `AutoDevModel` with `extra="forbid"`, and updates usually use `model_copy(update={...})`.

## Validation, safety, and execution flow
- Validation behavior is repo-specific in `autodev/tools/test_runner.py`. It prefers explicit commands, otherwise infers targeted pytest files like `tests/test_<module>.py`, then falls back to `pytest -q`.
- `broader-fallback` means: run targeted validation first, then append broader default validation commands.
- Validation policy is injected from config into `AgentContext.metadata` via `PipelineConfig.as_context_metadata()` and resolved again in `ValidatePhaseHandler`; keep those keys aligned.
- Guardrails are enforced by `autodev/core/supervisor.py`. For agent/runtime flows, do not bypass supervisor-validated shell/file operations with new raw destructive subprocess or filesystem code.
- Workspace isolation is handled in `autodev/core/workspace_manager.py` using `snapshot`, `branch`, or `worktree`; this is also where diffs, changed-file summaries, quarantine, and rollback are managed.

## CLI, config, and developer workflow
- CLI entry points live in `autodev/cli/main.py` using Typer. Main user commands are `init`, `run`, `fix-ci`, `status`, `backlog`, and `runs`.
- Config discovery order matters: `./autodev.yaml`, `./autodev.yml`, then `~/.autodev/pipeline.yaml` / `pipeline.yml`. CLI flags override config values.
- `autodev init` seeds `~/.autodev/models.yaml` and `~/.autodev/pipeline.yaml`; model routing reads those files before falling back to `configs/models.yaml`.
- Common commands:
  - `make install-dev`
  - `make lint`
  - `make format`
  - `make test`
  - `make ci`
  - `pytest tests/test_core.py -v`
  - `pytest tests/test_config.py::TestPipelineConfigLoad -v`
- This repo uses Ruff for both linting and formatting, pytest for tests, and Typer's `CliRunner` for CLI tests.

## Integration points
- `autodev/models/router.py` selects adapters by model name prefix (`gpt-`, `claude-`, `gemini-`) and only uses remote providers when the matching API key env var is present; otherwise it falls back to the local adapter.
- GitHub integration lives in `autodev/github/`. `RepoCloner` uses `GITHUB_TOKEN` when present for authenticated clone URLs, and `PRCreator` requires `GITHUB_TOKEN` to open PRs.
- `autodev run <issue-url>` and `autodev fix-ci <run-url>` are the two top-level pipeline entry paths; keep issue-intake and CI-intake behavior distinct.

## Codebase-specific testing conventions
- Tests are broad and behavior-focused; when changing a subsystem, update the nearest focused file in `tests/` instead of adding a new testing style.
- Many tests assert exact durable metadata/artifact behavior, not just return values. Preserve artifact names and metadata keys unless the change intentionally updates the contract.
- For orchestrator CLI tests, note that `--work-dir` is treated as the parent directory and the orchestrator persists under `<work_dir>/state` (see `tests/test_cli.py`).
