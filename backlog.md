# AutoDev Implementation Backlog

This backlog captures the major work still remaining to turn the current AutoDev scaffold into the runtime described in [README.md](README.md) and [system_design.md](system_design.md).

It is written so each item could later become one GitHub issue or one small issue cluster.

## Current Baseline

The repository already has:

- a Python package and CLI scaffold
- basic agent, tool, GitHub, and core runtime modules
- placeholder pipeline execution and test coverage for the current stubs

The biggest gaps are:

- no durable backlog/task/run state model yet
- no task materialization from backlog items
- no deterministic scheduler with retries and failure classes
- no isolated workspace manager with snapshots/worktrees
- no targeted validation engine
- no structured review and promotion workflow
- no end-to-end execution record that can be resumed or audited

## Suggested Labels

- `priority:p0`, `priority:p1`, `priority:p2`
- `type:core`, `type:cli`, `type:github`, `type:validation`, `type:review`, `type:docs`
- `milestone:mvp`, `milestone:post-mvp`

## Milestone 0: Align the Existing Scaffold

### AD-001 Unify runtime terminology and phase names

- **Status:** completed on 2026-03-16
- **Priority:** `priority:p0`
- **Type:** `type:core`
- **Problem:** The current code mixes older names such as `code` and `test` with the newer design language of `implement` and `validate`, and it has both a simple `Orchestrator` and a separate `RuntimeOrchestrator`.
- **Scope:** Standardize on one runtime vocabulary and one primary execution entrypoint across CLI, runtime, tests, and docs.
- **Acceptance criteria:**
  - one canonical phase sequence exists: `plan -> implement -> validate -> review`
  - the core runtime path uses one orchestrator model instead of overlapping abstractions
  - tests and docs use the same phase names

### AD-002 Audit the current scaffold against the new runtime design

- **Status:** completed on 2026-03-18
- **Priority:** `priority:p0`
- **Type:** `type:docs`
- **Completion notes:** added [docs/architecture_inventory.md](docs/architecture_inventory.md), which maps every major `autodev/` package to a target subsystem and calls out duplicate and legacy scaffold abstractions.
- **Problem:** The repo contains working stubs, but there is no explicit gap analysis between the current implementation and the target architecture.
- **Scope:** Produce a short architecture inventory that marks modules as keep, refactor, replace, or remove.
- **Acceptance criteria:**
  - every major package under `autodev/` is mapped to a target subsystem
  - duplicate or legacy abstractions are identified
  - the result can guide follow-up refactors without ambiguity

## Milestone 1: Durable Runtime Foundations

### AD-003 Define durable schemas for backlog items, tasks, task results, runs, and review decisions

- **Status:** completed on 2026-03-18
- **Priority:** `priority:p0`
- **Type:** `type:core`
- **Completion notes:** added durable Pydantic runtime schemas in [autodev/core/schemas.py](autodev/core/schemas.py) for backlog items, tasks, task results, run metadata, validation results, failure classifications, and review decisions, with focused round-trip coverage in [tests/test_schemas.py](tests/test_schemas.py).
- **Problem:** The current `AgentContext` is transient and not sufficient for resumable, inspectable execution.
- **Scope:** Introduce stable Pydantic models for backlog, task, run metadata, validation results, failure classifications, and review decisions.
- **Acceptance criteria:**
  - schemas cover the MVP data model from the design doc
  - each schema serializes cleanly to JSON
  - tests verify required fields, defaults, and round-trip serialization

### AD-004 Implement a persistent state store for backlog, tasks, runs, reports, and scheduler history

- **Status:** completed on 2026-03-18
- **Priority:** `priority:p0`
- **Type:** `type:core`
- **Completion notes:** added the file-backed [autodev/core/state_store.py](autodev/core/state_store.py) with predictable paths and atomic JSON writes for backlog items, tasks, runs, reports, reviews, and scheduler state/history, with persistence coverage in [tests/test_state_store.py](tests/test_state_store.py).
- **Problem:** There is no durable execution state, so runs cannot be resumed, inspected, or replayed.
- **Scope:** Add a simple file-backed state store abstraction with predictable paths and atomic writes.
- **Acceptance criteria:**
  - backlog state, task state, run metadata, and review results persist to disk
  - read/update operations are covered by tests
  - interrupted runs can be reloaded without losing prior state

### AD-005 Introduce a backlog service for change requests and dependency tracking

- **Status:** completed on 2026-03-18
- **Priority:** `priority:p0`
- **Type:** `type:core`
- **Completion notes:** added [autodev/core/backlog_service.py](autodev/core/backlog_service.py) on top of the file-backed store to create, update, list, and resolve durable backlog items with dependency validation, covered by [tests/test_backlog_service.py](tests/test_backlog_service.py).
- **Problem:** The runtime currently starts directly from an issue URL instead of a durable backlog item.
- **Scope:** Build a service that creates, updates, lists, and resolves backlog items with status, dependencies, priority, and acceptance criteria.
- **Acceptance criteria:**
  - backlog items can be created independently of execution
  - dependency relationships are stored and validated
  - backlog state supports `planned`, `active`, `blocked`, and `completed`

## Milestone 2: Task Materialization and Scheduling

### AD-006 Build the task materializer that expands eligible backlog items into phase tasks

- **Status:** completed on 2026-03-18
- **Priority:** `priority:p0`
- **Type:** `type:core`
- **Completion notes:** added [autodev/core/task_materializer.py](autodev/core/task_materializer.py) to expand eligible backlog items into deterministic `plan`, `implement`, `validate`, and `review` tasks with dependency gating and duplicate prevention, covered by [tests/test_task_materializer.py](tests/test_task_materializer.py).
- **Problem:** The current runtime does not generate phase tasks from durable requests at runtime.
- **Scope:** Materialize one backlog item or bounded batch into `plan`, `implement`, `validate`, and `review` tasks only when dependencies are satisfied.
- **Acceptance criteria:**
  - task IDs are deterministic and phase-specific
  - materialization respects backlog-level dependencies
  - duplicate task generation is prevented

### AD-007 Replace the simple DAG helper with a deterministic scheduler

- **Status:** completed on 2026-03-18
- **Priority:** `priority:p0`
- **Type:** `type:core`
- **Completion notes:** extended [autodev/core/task_graph.py](autodev/core/task_graph.py) with a deterministic `TaskScheduler` that validates task graphs, derives runnable tasks from completion state, and chooses the next task with a stable tie-break rule, covered by [tests/test_scheduler.py](tests/test_scheduler.py).
- **Problem:** The current `TaskGraph` can sort nodes, but it does not schedule real tasks with priorities, retries, or run history.
- **Scope:** Add scheduler logic that validates task graphs, computes runnable tasks, and picks the next task deterministically.
- **Acceptance criteria:**
  - missing dependencies, duplicate IDs, and cycles are rejected
  - runnable tasks are derived from completion state, not timestamps alone
  - the scheduler has a deterministic tie-break rule and test coverage

### AD-008 Add bounded retry and backoff handling at the scheduler layer

- **Status:** completed on 2026-03-18
- **Priority:** `priority:p0`
- **Type:** `type:core`
- **Completion notes:** extended [autodev/core/task_graph.py](autodev/core/task_graph.py) with bounded retry/backoff handling, blocked-task reset behavior, and persisted scheduler retry state/history backed by [autodev/core/state_store.py](autodev/core/state_store.py), with focused coverage in [tests/test_scheduler.py](tests/test_scheduler.py).
- **Problem:** The current loop retries only as a local debug iteration and does not persist retry policy.
- **Scope:** Track retry counts, next-eligible-at timestamps, and retry history per task or pipeline.
- **Acceptance criteria:**
  - retryable failures can be retried with bounded backoff
  - non-retryable failures remain blocked until a new implementation attempt occurs
  - retry history is stored in scheduler state

## Milestone 3: Workspace Isolation and Safe Execution

### AD-009 Implement a workspace manager with snapshots and run-local metadata

- **Status:** completed on 2026-03-19
- **Priority:** `priority:p0`
- **Type:** `type:core`
- **Completion notes:** added [autodev/core/workspace_manager.py](autodev/core/workspace_manager.py) for per-run workspace directories, file snapshots, and persisted implementation diff/changed-file artifacts backed by [autodev/core/state_store.py](autodev/core/state_store.py), with focused coverage in [tests/test_workspace_manager.py](tests/test_workspace_manager.py) and [tests/test_core.py](tests/test_core.py).
- **Problem:** The current runtime clones a repo into a temp dir, but it does not manage snapshots, run metadata, or rollback.
- **Scope:** Add a workspace manager responsible for per-run directories, file snapshots, and diff capture.
- **Acceptance criteria:**
  - each run has a dedicated workspace record
  - files can be snapshotted before edits
  - diffs and changed-file summaries are persisted after implementation

### AD-010 Add optional git branch and worktree isolation modes

- **Status:** completed on 2026-03-19
- **Priority:** `priority:p1`
- **Type:** `type:core`
- **Completion notes:** extended [autodev/core/workspace_manager.py](autodev/core/workspace_manager.py) and [autodev/tools/git_tool.py](autodev/tools/git_tool.py) with configurable snapshot, branch, and worktree isolation plus teardown/quarantine helpers, and threaded configurable run isolation through [autodev/core/runtime.py](autodev/core/runtime.py), covered by [tests/test_workspace_manager.py](tests/test_workspace_manager.py) and [tests/test_core.py](tests/test_core.py).
- **Problem:** Safe execution isolation is a core design goal, but the current runtime has only a basic clone path.
- **Scope:** Support multiple isolation levels such as in-place with snapshots, branch-per-run, and worktree-per-run.
- **Acceptance criteria:**
  - isolation mode is configurable per run
  - branch/worktree setup and teardown are automated
  - failure paths can roll back or quarantine changes safely

### AD-011 Enforce supervisor checks around unsafe shell and file operations

- **Status:** completed on 2026-03-19
- **Priority:** `priority:p1`
- **Type:** `type:core`
- **Completion notes:** extended [autodev/core/supervisor.py](autodev/core/supervisor.py) and [autodev/core/state_store.py](autodev/core/state_store.py) so guardrail decisions are structured and persisted, and wired supervisor enforcement into [autodev/tools/shell_tool.py](autodev/tools/shell_tool.py), [autodev/tools/filesystem_tool.py](autodev/tools/filesystem_tool.py), and [autodev/tools/test_runner.py](autodev/tools/test_runner.py), with focused coverage in [tests/test_tools.py](tests/test_tools.py) and [tests/test_state_store.py](tests/test_state_store.py).
- **Problem:** Safety checks exist, but they are not yet integrated as a first-class execution guardrail across runtime operations.
- **Scope:** Apply supervisor validation consistently before shell commands, file writes, and promotion steps.
- **Acceptance criteria:**
  - unsafe commands are blocked before execution
  - guardrail decisions are logged and persisted
  - tests cover destructive command rejection and allowed command paths

## Milestone 4: Phase Registry and Execution Contracts

### AD-012 Replace ad hoc agent calls with a formal phase registry

- **Status:** completed on 2026-03-20
- **Priority:** `priority:p0`
- **Type:** `type:core`
- **Completion notes:** added [autodev/core/phase_registry.py](autodev/core/phase_registry.py) with normalized phase payload/result contracts and swappable default handlers for `plan`, `implement`, `validate`, `review`, and `promote`, then wired [autodev/core/runtime.py](autodev/core/runtime.py) to dispatch core phases through the registry while preserving orchestration flow, covered by [tests/test_core.py](tests/test_core.py).
- **Problem:** The runtime currently instantiates agents directly instead of dispatching through stable phase contracts.
- **Scope:** Introduce a registry for planner, implementer, validator, reviewer, and promoter handlers with normalized input and output payloads.
- **Acceptance criteria:**
  - each phase receives a normalized task payload
  - each phase returns a structured result with status, message, artifacts, and metrics
  - the runtime can swap handler implementations without changing orchestration logic

### AD-013 Expand planner execution beyond prompt generation into repository-aware planning

- **Status:** completed on 2026-03-24
- **Priority:** `priority:p1`
- **Type:** `type:core`
- **Completion notes:** extended [autodev/agents/planner.py](autodev/agents/planner.py) with repository-aware target-file discovery, acceptance-criteria extraction, and validation hints while preserving fallback planning, then persisted planning summaries via [autodev/core/workspace_manager.py](autodev/core/workspace_manager.py) and [autodev/core/runtime.py](autodev/core/runtime.py), covered by [tests/test_agents.py](tests/test_agents.py) and [tests/test_core.py](tests/test_core.py).
- **Problem:** The current planner produces a generic numbered list but does not inspect the repo or capture risk and validation intent.
- **Scope:** Add repo inspection, target file identification, acceptance criteria extraction, and validation hints.
- **Acceptance criteria:**
  - planner output includes likely target files and validation criteria
  - planner output is persisted as a planning artifact
  - tests cover both fallback and repository-aware planning modes

### AD-014 Replace the coder stub with an implementer that can produce controlled file edits

- **Status:** completed on 2026-03-24
- **Priority:** `priority:p0`
- **Type:** `type:core`
- **Completion notes:** refactored [autodev/agents/coder.py](autodev/agents/coder.py) into a controlled workspace editor with per-file snapshots and rollback-aware write handling, then updated [autodev/core/phase_registry.py](autodev/core/phase_registry.py) and [autodev/core/runtime.py](autodev/core/runtime.py) so implement-stage file tracking comes from captured git diff/status artifacts instead of heuristics alone, covered by [tests/test_agents.py](tests/test_agents.py) and [tests/test_core.py](tests/test_core.py).
- **Problem:** The current coder mostly records file paths and does not produce a real implementation artifact.
- **Scope:** Introduce controlled edit application, file change summaries, and rollback-aware write behavior.
- **Acceptance criteria:**
  - implementer produces actual file modifications in the run workspace
  - changed files are tracked from diff output rather than heuristics alone
  - failed writes can be rolled back or marked partial safely

## Milestone 5: Validation and Failure Handling

### AD-015 Build a targeted validation engine based on changed files and explicit commands

- **Status:** completed on 2026-03-25
- **Priority:** `priority:p0`
- **Type:** `type:validation`
- **Completion notes:** expanded [autodev/tools/test_runner.py](autodev/tools/test_runner.py) into a structured validation engine with explicit command overrides, changed-file-aware pytest targeting, and per-command result capture, then updated [autodev/core/phase_registry.py](autodev/core/phase_registry.py) and [autodev/core/runtime.py](autodev/core/runtime.py) to resolve backlog-driven validation commands, persist [autodev/core/schemas.py](autodev/core/schemas.py) `ValidationResult` artifacts via the state store, and surface validation metadata/artifacts in phase output, covered by [tests/test_tools.py](tests/test_tools.py) and [tests/test_core.py](tests/test_core.py).
- **Problem:** The current test runner only executes one command and cannot infer the smallest useful validation set.
- **Scope:** Add validation profiles, changed-file inference, explicit command override support, and structured result persistence.
- **Acceptance criteria:**
  - validation can use explicit commands from the backlog item when present
  - otherwise validation derives commands from changed files or language/project defaults
  - command, exit code, stdout, and stderr are persisted per validation step

### AD-016 Add failure classification for retryable, validation, policy, environment, and manual-intervention failures

- **Status:** completed on 2026-03-25
- **Priority:** `priority:p0`
- **Type:** `type:validation`
- **Completion notes:** added [autodev/core/failure_classifier.py](autodev/core/failure_classifier.py) to classify failed phase outcomes into retryable, validation, policy, environment, and manual-intervention buckets, then updated [autodev/core/phase_registry.py](autodev/core/phase_registry.py) and [autodev/core/runtime.py](autodev/core/runtime.py) so failed phases persist classified [autodev/core/schemas.py](autodev/core/schemas.py) task results and drive durable scheduler state for matching backlog tasks, covered by [tests/test_failure_classifier.py](tests/test_failure_classifier.py), [tests/test_core.py](tests/test_core.py), and [tests/test_scheduler.py](tests/test_scheduler.py).
- **Problem:** The current runtime only distinguishes pass/fail in a coarse way and cannot drive scheduler policy from failure type.
- **Scope:** Classify failures at phase boundaries and attach classification to task results.
- **Acceptance criteria:**
  - every failed phase receives a failure class
  - scheduler behavior changes based on classification
  - tests cover all baseline classifications from the design doc

### AD-017 Add stop-on-first-failure and configurable validation breadth

- **Status:** completed on 2026-03-25
- **Priority:** `priority:p1`
- **Type:** `type:validation`
- **Completion notes:** extended [autodev/tools/test_runner.py](autodev/tools/test_runner.py) with configurable validation breadth (`targeted` vs `broader-fallback`), continue-on-error/stop-on-first-failure handling, and persisted selection rationale, then updated [autodev/core/phase_registry.py](autodev/core/phase_registry.py) and [autodev/core/schemas.py](autodev/core/schemas.py) so backlog/runtime policy metadata flows into validation artifacts and human-readable output, covered by [tests/test_tools.py](tests/test_tools.py), [tests/test_core.py](tests/test_core.py), and [tests/test_schemas.py](tests/test_schemas.py).
- **Problem:** The validation strategy needs clear runtime policy knobs for cost and speed.
- **Scope:** Support strict targeted validation, broader fallback validation, and optional continue-on-error behavior.
- **Acceptance criteria:**
  - validation policy is configurable
  - failure handling is deterministic and documented
  - artifacts clearly show what ran and why

## Milestone 6: Review and Promotion

### AD-018 Implement a structured review engine with explicit decisions

- **Status:** completed on 2026-03-25
- **Priority:** `priority:p0`
- **Type:** `type:review`
- **Completion notes:** refactored [autodev/agents/reviewer.py](autodev/agents/reviewer.py) into a deterministic review engine that evaluates diff presence, validation status, acceptance criteria, and optional approval/policy gates to emit explicit review decisions, then updated [autodev/core/phase_registry.py](autodev/core/phase_registry.py) and [autodev/core/runtime.py](autodev/core/runtime.py) to persist structured [autodev/core/schemas.py](autodev/core/schemas.py) `ReviewResult` artifacts and automatically block promotion unless review is approved, covered by [tests/test_agents.py](tests/test_agents.py), [tests/test_core.py](tests/test_core.py), [tests/test_schemas.py](tests/test_schemas.py), and [tests/test_state_store.py](tests/test_state_store.py).
- **Problem:** The current reviewer writes an assessment string but does not emit a structured decision.
- **Scope:** Produce review outputs such as `approved`, `changes_requested`, `blocked`, and `awaiting_human_approval`.
- **Acceptance criteria:**
  - review checks diff existence, validation status, and acceptance criteria presence
  - decision output is persisted as structured data
  - review failures stop promotion automatically

### AD-019 Add policy and secret-exposure gates before promotion

- **Status:** completed on 2026-03-25
- **Priority:** `priority:p1`
- **Type:** `type:review`
- **Completion notes:** extended [autodev/agents/reviewer.py](autodev/agents/reviewer.py) with deterministic policy-gate failures, redacted secret-exposure heuristics over changed files and diff fallbacks, and explicit review metadata for blocked gates, then updated [autodev/core/phase_registry.py](autodev/core/phase_registry.py) to persist those review details in structured artifacts, covered by [tests/test_agents.py](tests/test_agents.py) and [tests/test_core.py](tests/test_core.py).
- **Problem:** Promotion should be blocked when changes fail policy or reveal obvious secrets.
- **Scope:** Add basic policy checks and file-content heuristics that run during review.
- **Acceptance criteria:**
  - policy failures are classified separately from validation failures
  - secret-like content triggers a blocked or changes-requested decision
  - review artifacts explain which gate failed

### AD-020 Implement promotion workflows: patch bundle, branch push, and PR creation

- **Status:** completed on 2026-03-25
- **Priority:** `priority:p1`
- **Type:** `type:github`
- **Completion notes:** refactored [autodev/core/runtime.py](autodev/core/runtime.py) to support promotion modes for patch bundles, branch pushes, and pull requests behind approved review gates, including generated PR title/body content from run artifacts plus persisted promotion metadata such as branch names, commit details, patch paths, and PR URLs, covered by [tests/test_core.py](tests/test_core.py).
- **Problem:** PR creation exists only as a thin final step and is not integrated with approval state or run artifacts.
- **Scope:** Support multiple promotion outcomes, including emit patch, push branch, and open PR when review allows it.
- **Acceptance criteria:**
  - promotion requires an approved review outcome
  - PR title/body can be generated from run artifacts
  - branch naming and promotion metadata are persisted

## Milestone 7: GitHub and CLI Productization

### AD-021 Expand issue intake into backlog-item creation

- **Status:** completed on 2026-03-25
- **Priority:** `priority:p1`
- **Type:** `type:github`
- **Completion notes:** added [autodev/github/issue_intake.py](autodev/github/issue_intake.py) with `IssueIntakeService` that normalizes a GitHub issue into a durable `BacklogItem` — parsing checkbox acceptance criteria, mapping priority labels (`priority:p0`–`p3`), preserving labels and repo metadata, and making re-intake idempotent; updated [autodev/core/runtime.py](autodev/core/runtime.py) so `_read_issue()` persists via `IssueIntakeService` and threads `backlog_item_id` into context, covered by [tests/test_github.py](tests/test_github.py).
- **Problem:** GitHub issues are currently read directly into transient runtime context.
- **Scope:** Convert issue intake into backlog item creation with normalized title, description, labels, and acceptance criteria.
- **Acceptance criteria:**
  - issue URLs can be transformed into durable backlog items
  - labels and metadata are preserved where useful
  - invalid or inaccessible issues fail with actionable diagnostics

### AD-022 Add CLI commands for backlog and run management

- **Status:** completed on 2026-03-25
- **Priority:** `priority:p1`
- **Type:** `type:cli`
- **Completion notes:** added `backlog add` and `backlog list` sub-commands (title slug as item ID, priority/label/criterion flags, status filter) and `run start`, `run resume`, and `runs show` commands to [autodev/cli/main.py](autodev/cli/main.py), with `resume_pipeline(run_id)` added to [autodev/core/runtime.py](autodev/core/runtime.py) to load persisted run metadata and re-execute the pipeline; all commands share a stable default state dir (`~/.autodev/state`) and accept `--work-dir` for override; covered by [tests/test_cli.py](tests/test_cli.py).
- **Problem:** The CLI exposes `init`, `run`, `fix-ci`, and `status`, but not the durable runtime concepts from the design.
- **Scope:** Add commands such as `backlog add`, `backlog list`, `run start`, `run resume`, and `runs show`.
- **Acceptance criteria:**
  - users can create and inspect backlog items without editing files directly
  - users can resume interrupted runs
  - CLI output links runtime actions to persisted artifacts clearly

### AD-023 Add operator-facing JSON and Markdown artifacts for active runs, failures, and validation history

- **Priority:** `priority:p1`
- **Type:** `type:cli`
- **Problem:** The design calls for inspectable operator artifacts, but the current runtime only prints console output.
- **Scope:** Persist human-readable and machine-readable reports for runs, validation, review, and scheduler history.
- **Acceptance criteria:**
  - each run produces a summary artifact
  - failure history and validation history are discoverable from disk
  - artifact paths are stable enough for future UI work
- **Status:** `completed`
- **Completion notes:** Implemented `RunReporter` in `autodev/core/run_reporter.py`. Each run writes `runs/{run_id}/summary.json` and `runs/{run_id}/summary.md`. Validation results are appended to `reports/validation-history.json` after every run; failure stage outputs are appended to `reports/failure-history.json` on failed runs. `RunReporter` is wired into the `Orchestrator.run_pipeline()` finally block. 14 tests added in `tests/test_run_reporter.py`.

### AD-024 Implement `fix-ci` as a real intake and repair workflow

- **Priority:** `priority:p2`
- **Type:** `type:github`
- **Problem:** `fix-ci` is currently a stub, but it is a likely high-value user workflow.
- **Scope:** Read CI failure context, normalize it into a backlog item, and route it through the same runtime.
- **Acceptance criteria:**
  - CI logs can be ingested into a backlog item
  - the resulting run follows the standard phase pipeline
  - artifacts clearly distinguish issue-driven and CI-driven runs
- **Status:** `completed`
- **Completion notes:** Implemented `CIRunReader` (`autodev/github/ci_runner.py`) and `CIIntakeService` (`autodev/github/ci_intake.py`) following the IssueReader/IssueIntakeService pattern exactly. GitHub Actions run URLs (`https://github.com/<owner>/<repo>/actions/runs/<run_id>`) are parsed, failing jobs/steps fetched via PyGithub, and validation commands inferred from step names. `BacklogItem.source = "github_actions"` distinguishes CI-driven runs. `Orchestrator.run_ci_pipeline()` added; `run_pipeline()` refactored to share a `_run_pipeline_impl(entry_url, intake_fn)` body. Fixed latent bug: `self.backlog_service` was never initialized in `Orchestrator.__init__`. CLI `fix-ci` stub replaced with real implementation. 40 tests added in `tests/test_ci_intake.py` (257 total).

## Milestone 8: Quality, Testing, and Documentation

### AD-025 Replace stub-oriented tests with durable runtime and end-to-end tests

- **Priority:** `priority:p0`
- **Type:** `type:core`
- **Problem:** Existing tests mostly validate scaffolding behavior and will not protect the durable runtime as it grows.
- **Scope:** Add tests for schemas, state store, scheduler behavior, workspace isolation, review decisions, and local end-to-end runs.
- **Acceptance criteria:**
  - the new runtime subsystems have targeted unit coverage
  - at least one end-to-end local run is exercised in tests with mocks or fixtures
  - old tests are updated or retired when they no longer match the architecture

### AD-026 Add configuration support for pipelines, validation profiles, isolation mode, and retry policy

- **Priority:** `priority:p1`
- **Type:** `type:core`
- **Problem:** Current config is minimal and does not represent the runtime controls described in the design.
- **Scope:** Extend config loading and validation for scheduler settings, phase sequence, validation policy, approval requirements, and isolation levels.
- **Acceptance criteria:**
  - config files map cleanly to runtime models
  - invalid config fails early with clear errors
  - defaults are safe and documented

### AD-027 Document local development, architecture, and contribution workflows

- **Priority:** `priority:p2`
- **Type:** `type:docs`
- **Problem:** The repo now has a good high-level design, but it still needs implementation-oriented contributor documentation.
- **Scope:** Add docs for local setup, runtime concepts, testing strategy, and how backlog items map to code.
- **Acceptance criteria:**
  - contributors can bootstrap the project and run tests locally
  - the architecture docs reflect the actual implementation structure
  - issue authors have guidance for writing good backlog items

## First Recommended Issue Slice

If the goal is to start with the highest-leverage MVP path, implement these first:

1. AD-001 Unify runtime terminology and phase names
2. AD-003 Define durable schemas
3. AD-004 Implement persistent state store
4. AD-005 Introduce backlog service
5. AD-006 Build task materializer
6. AD-007 Replace the simple DAG helper with a deterministic scheduler
7. AD-009 Implement a workspace manager with snapshots
8. AD-012 Replace ad hoc agent calls with a formal phase registry
9. AD-015 Build a targeted validation engine
10. AD-018 Implement a structured review engine

That sequence gets AutoDev from a documentation-first scaffold to a durable local runtime with real execution records.
