# Contributing to AutoDev

## Prerequisites

- Python 3.9+
- Git
- Optional: `GITHUB_TOKEN` for tests that hit the GitHub API (most tests do not need it)

## Bootstrap

```bash
git clone https://github.com/alexanderjulianmartinez/autodev.git
cd autodev

python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate

pip install -e .[dev]
autodev init                  # creates ~/.autodev/ config directory
```

Verify everything works:

```bash
make ci
```

This runs `ruff check`, `ruff format --check`, and `pytest` in sequence. All three must pass before opening a PR.

## Running tests

```bash
make test                          # full suite
pytest tests/test_core.py -v       # single file
pytest tests/test_config.py::TestPipelineConfigLoad -v  # single class
pytest -k test_pipeline_reaches_completed_state         # single test by name
pytest -x -q                       # stop on first failure, quiet
```

Pre-commit hooks run `ruff` on staged files automatically. To run them manually on everything:

```bash
make pre-commit
```

## Testing strategy

Tests live in `tests/` and follow a consistent structure:

**Unit tests** (`test_schemas.py`, `test_state_store.py`, `test_config.py`, …) test one subsystem in isolation using `tmp_path` fixtures and no external I/O.

**E2E tests** (`test_orchestrator_e2e.py`) exercise the full `Orchestrator` pipeline — real phase-registry machinery, real state persistence, real `RunReporter` — but stub only the external boundaries:

- `PlannerAgent.run` / `CoderAgent.run` / `ReviewerAgent.run` (LLM calls)
- `TestRunner.run_validation` (shell commands)
- `Orchestrator._read_issue` / `_read_ci_run` (GitHub API)

This pattern gives real coverage of the coordinator, phase registry, and state store without requiring API keys or a live repo.

**Naming conventions:**

- Test files: `tests/test_<subsystem>.py`
- Test classes: `TestSubsystemBehaviour` (e.g. `TestPipelineConfigLoad`)
- Test functions: `test_<what_is_asserted>` (e.g. `test_invalid_yaml_raises_config_error`)

## Adding a new subsystem

1. Put it in the right package (`autodev/core/`, `autodev/agents/`, `autodev/tools/`, `autodev/github/`).
2. Export it from the package `__init__.py`.
3. Write a `tests/test_<subsystem>.py` file with unit tests for the happy path, error paths, and edge cases.
4. If the subsystem touches the pipeline, add or update E2E coverage in `tests/test_orchestrator_e2e.py`.
5. Run `make ci` before pushing.

## Backlog workflow

Work items live in `backlog.md` as `AD-NNN` tickets. The flow is:

1. An item is listed with `**Status:**` not set (or `planned`).
2. It gets picked up in a branch named `u/<user>/<ticket-slug>`.
3. The implementation is committed, tests pass, pre-commit is clean.
4. `backlog.md` is updated with `**Status:** completed on <date>` and a `**Completion notes:**` line.
5. A PR is opened against `main`.

Branch naming: `u/<github-user>/AD-<NNN>_<short-slug>` or `u/<github-user>/M<N>_<milestone-slug>` for multi-ticket milestone branches.

## Writing good backlog items

A well-formed backlog item has:

- **A single clear problem statement.** One sentence on why the current state is wrong or incomplete.
- **A bounded scope.** Prefer items that can be completed in one small PR. If the scope spans multiple files or subsystems, split it.
- **Concrete acceptance criteria.** Each criterion should be falsifiable: "X happens when Y" rather than "the system is improved."
- **The right type label.** `type:core` for runtime subsystems, `type:cli` for CLI changes, `type:github` for GitHub integrations, `type:docs` for documentation, `type:validation` for test/validation work.

Example of a good item:

```
### AD-NNN Short title

- **Priority:** `priority:p1`
- **Type:** `type:core`
- **Problem:** `PhaseRegistry.execute()` swallows handler exceptions and marks the
  phase as failed without preserving the original traceback, making debugging hard.
- **Scope:** Propagate the original exception from handler failures so the
  Orchestrator can log it and RunReporter can record it.
- **Acceptance criteria:**
  - handler exceptions propagate out of `PhaseRegistry.execute()`
  - `RunReporter` records the exception message in the failure history
  - existing tests still pass
```

What makes items hard to implement:

- Scope that touches more than 3–4 unrelated files
- Acceptance criteria that are vague ("things work better")
- No clear definition of the before/after boundary

## Key design constraints

These are non-negotiable; keep them in mind when adding code:

- **Phase contracts are strict.** `PhaseExecutionPayload → PhaseExecutionResult` is the only interface between `PhaseRegistry` and agents. Do not bypass it.
- **Durable state over transient context.** Every phase output must be persisted as structured JSON by the `StateStore`. Do not accumulate pipeline state in memory only.
- **Supervisor guardrails are not optional.** Agents must use `ShellTool` and `FilesystemTool`, never raw `subprocess` calls.
- **Config fails early.** Invalid `pipeline.yaml` content must raise `ConfigError` before any pipeline stage runs.
- **Backward compatibility.** `AgentContext` is a legacy transient layer still used by agents. New phase handler code should use `PhaseExecutionPayload` / `PhaseExecutionResult`. Do not add new fields to `AgentContext`.
