# AutoDev Architecture Inventory

This inventory maps `autodev/` packages to their target runtime subsystems. It was written early in the project (pre-AD-003) as a migration guide and is periodically updated as implementation progresses.

**Implementation status as of AD-027 (2026-03-25):** Milestones 0–8 (AD-001 through AD-027) are complete. The runtime foundation — schemas, state store, phase registry, backlog service, task materializer, scheduler, workspace manager, failure classifier, CI intake, and pipeline config — is fully implemented. The primary remaining work is polishing the CLI, extending validation profiles, and hardening the agent implementations.

## Summary

- **Complete:** durable schemas, file-backed state store, backlog/task/run lifecycle, phase registry, workspace isolation (snapshot/branch/worktree), failure classification, RunReporter, CI intake, PipelineConfig loading.
- **Partial:** agent implementations (planner/coder/reviewer stub LLM calls; debugger is a repair helper only).
- **Future:** approval gates, multi-repo support, additional validation profiles, agent tool-calling improvements.

Original disposition summary (pre-implementation):

- **Keep:** model routing, basic safety guardrails, and the CLI shell as starting points.
- **Refactor:** agents, GitHub helpers, shell/filesystem/git tools, and the unified orchestrator entrypoint.
- **Replace:** the transient context model, the simple DAG helper, the stub implementation loop, and the single-command test runner.
- **Remove later:** compatibility shims and legacy naming once the new runtime subsystems land.

## Package Inventory

| Current package | Current role | Target subsystem | Disposition | Notes |
| --- | --- | --- | --- | --- |
| `autodev.cli` | Thin commands for `init`, `run`, `fix-ci`, and `status` | Operator CLI for backlog intake, run control, and artifact inspection | **Refactor** | Keep Typer-based CLI surface, but expand from issue-driven one-shot commands into durable `backlog` and `run` workflows. |
| `autodev.core` | Unified orchestrator loop, simple DAG, and supervisor | Runtime coordinator, state store integration, backlog service, task materializer, deterministic scheduler, workspace manager, and phase registry | **Refactor / Replace** | Keep `Orchestrator` as the public entrypoint, but replace most internal execution logic with durable runtime subsystems. |
| `autodev.agents` | Planner/coder/reviewer/debugger stubs sharing one transient context object | Phase handlers behind a formal phase registry: planner, implementer, validator, reviewer, promoter | **Refactor** | Keep the package as the handler layer, but rename and harden handlers around normalized task/result contracts. |
| `autodev.tools` | Basic filesystem, shell, git, and test utilities | Workspace operations, supervised command execution, targeted validation engine, and promotion helpers | **Refactor** | Keep low-level operations, but route them through workspace isolation, policy checks, and structured result persistence. |
| `autodev.github` | Issue intake, repo clone, and PR creation helpers | GitHub intake and promotion adapters | **Refactor** | Preserve external integration boundaries, but move from direct runtime calls to backlog-item creation and promotion workflows. |
| `autodev.models` | Provider router and model adapters | Model/provider abstraction used by phase handlers | **Keep / Refactor** | Keep this package and its separation of router vs adapters; refactor config and phase binding only as needed. |
| `autodev.__init__` | Package export surface | Public package API | **Keep** | Minimal package metadata/export surface is fine. Keep it thin. |

## Module-Level Disposition

### `autodev.core`

| Module | Target subsystem | Disposition | Rationale |
| --- | --- | --- | --- |
| `core/runtime.py` | Runtime coordinator | **Refactor** | Keep `Orchestrator` as the canonical entrypoint, but replace the current in-memory issue → plan → implement → validate → review loop with durable backlog/task/run execution. |
| `core/orchestrator.py` | Backward-compatible import shim | **Remove later** | This is only a compatibility re-export. Remove it after all imports use `autodev.core.runtime.Orchestrator` or a new canonical runtime module. |
| `core/task_graph.py` | Scheduler/materializer foundation | **Replace** | The current graph only supports topological ordering of hard-coded stages. Replace with deterministic scheduling, runnable-task selection, retry state, and dependency validation. |
| `core/supervisor.py` | Safety and policy guardrails | **Refactor** | Keep the concept, but expand beyond a static shell blocklist into first-class execution guardrails for shell, file writes, and promotion actions. |

### `autodev.agents`

| Module | Target subsystem | Disposition | Rationale |
| --- | --- | --- | --- |
| `agents/base.py` | Shared runtime schemas / phase contracts | **Replace** | `AgentContext` is transient and too coarse for backlog items, tasks, runs, validation results, and review decisions. Replace it with stable runtime schemas; keep only the abstract handler idea. |
| `agents/planner.py` | Planner phase handler | **Refactor** | Keep the planner role, but expand from prompt-only planning into repository-aware planning with target files, risks, and validation hints. |
| `agents/coder.py` | Implementer phase handler | **Refactor / Rename** | Convert `CoderAgent` into an `Implementer` that performs controlled edits, captures diffs, and supports rollback-aware behavior. |
| `agents/reviewer.py` | Review engine / reviewer phase handler | **Refactor** | Keep the review phase, but replace free-form assessment strings with structured review decisions and gate results. |
| `agents/debugger.py` | Failure handling / repair assistance | **Replace** | The current debugger only increments metadata and suggests a patch attempt. Fold this behavior into failure classification, bounded retries, and future repair handlers. |

### `autodev.tools`

| Module | Target subsystem | Disposition | Rationale |
| --- | --- | --- | --- |
| `tools/base.py` | Tool interface | **Keep** | A thin tool abstraction remains useful if tools become implementation details behind phases. |
| `tools/filesystem_tool.py` | Workspace manager file operations | **Refactor** | Keep as a low-level primitive, but make writes snapshot-aware and tied to a run-local workspace. |
| `tools/shell_tool.py` | Supervised command runner | **Refactor** | Keep command execution, but centralize policy enforcement through the supervisor and persist command results as artifacts. |
| `tools/git_tool.py` | Workspace isolation and promotion helpers | **Refactor** | Keep git operations, but integrate them into branch/worktree isolation and structured promotion flows. |
| `tools/test_runner.py` | Validation engine | **Replace** | Replace single-command `pytest` execution with targeted validation profiles, explicit command support, and persisted structured outputs. |

### `autodev.github`

| Module | Target subsystem | Disposition | Rationale |
| --- | --- | --- | --- |
| `github/issue_reader.py` | Intake adapter | **Refactor** | Keep issue parsing/fetching, but convert output into durable backlog-item creation rather than direct transient runtime context. |
| `github/repo_cloner.py` | Workspace bootstrap adapter | **Refactor / Possibly fold** | This overlaps with `tools/git_tool.py`. Keep one cloning abstraction owned by the workspace manager and remove the duplicate wrapper afterward. |
| `github/pr_creator.py` | Promotion adapter | **Refactor** | Keep PR creation capability, but call it only from approved promotion workflows that persist branch and review metadata. |

### `autodev.models`

| Module group | Target subsystem | Disposition | Rationale |
| --- | --- | --- | --- |
| `models/router.py` | Provider selection for phase handlers | **Keep / Refactor** | The router is a good reusable boundary. Keep it and adjust only as phase contracts, config schemas, and runtime injection evolve. |
| `models/adapters/*` | Provider adapters | **Keep** | These are already aligned with the design goal of a model-agnostic runtime. |

## Duplicate and Legacy Abstractions

These are the main places where the scaffold still carries extra or legacy structure.

1. **Clone logic exists in two layers.** *(still open)*
   - `github/repo_cloner.py` wraps `tools/git_tool.py` for cloning.
   - The durable runtime should keep one workspace-owned cloning path.

2. **Compatibility orchestrator shim.** *(still open)*
   - `core/orchestrator.py` is only a re-export of `core/runtime.Orchestrator`.
   - Remove it after all callers use `autodev.core.runtime.Orchestrator` directly.

3. **Agent names reflect the scaffold, not the target phase model.** *(still open)*
   - `CoderAgent` should become an `ImplementerAgent` once the agent contract is finalized.
   - `DebuggerAgent` is a repair helper; it should not be a first-class runtime phase.

4. **Validation command resolution is split.** *(partially resolved)*
   - `PhaseRegistry` now resolves validation policy from task metadata and `PipelineConfig`.
   - `TestRunner` still runs one command at a time. Broader multi-command profiles are future work.

5. **`AgentContext` is the legacy transient context.** *(partially resolved)*
   - `PhaseExecutionPayload` / `PhaseExecutionResult` are the formal phase contracts.
   - `AgentContext` is still used inside agent implementations and will be retired incrementally.
   - Do not add new fields to `AgentContext`; use payload metadata instead.

## Recommended Refactor Targets

To keep follow-up work incremental, map the next issues onto the current codebase like this:

1. **AD-003 / AD-004 / AD-005**
   - Add new runtime schemas and a state store alongside the current scaffold.
   - Do not overload `AgentContext`; introduce new durable models instead.

2. **AD-006 / AD-007 / AD-008**
   - Replace the internals of `core/task_graph.py` with task materialization and deterministic scheduling.
   - Keep a small compatibility surface only if tests still rely on the current class name.

3. **AD-009 / AD-010 / AD-011**
   - Introduce a workspace manager that becomes the owner of clone/snapshot/diff/isolation behavior.
   - Move low-level filesystem, git, and shell operations behind it.

4. **AD-012 / AD-013 / AD-014**
   - Convert `agents/` from scaffold agents into formal phase handlers with normalized inputs and outputs.
   - Rename `CoderAgent` only when the implementer contract exists.

5. **AD-015 / AD-016 / AD-018**
   - Replace `tools/test_runner.py` and `agents/reviewer.py` with dedicated validation/review engines that emit structured artifacts.

## Bottom Line

The packages that should survive are `models`, `cli`, `tools`, `github`, and `core`, but most need refactoring around durable runtime primitives rather than incremental patching of the current in-memory loop.

The scaffold pieces most likely to be replaced outright are the transient `AgentContext`, the simple `TaskGraph`, the stub `TestRunner`, and the current `DebuggerAgent` behavior.
