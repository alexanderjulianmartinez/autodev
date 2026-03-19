# Generalizing AlphaDesk's Development Execution Pipeline for AutoDev

This document extracts the parts of AlphaDesk's development execution pipeline that should transfer cleanly into an open-source autonomous development runtime such as AutoDev. It focuses on reusable runtime architecture for coding workflows, not AlphaDesk-specific product surfaces.

## Executive Summary

The most reusable idea in AlphaDesk is not any one agent, dashboard, or file layout. It is the runtime model:

1. keep work as durable backlog items
2. materialize backlog items into a small, repeatable phase graph
3. run those phases through a shared task scheduler and agent registry
4. validate every code change with targeted checks
5. isolate risky writes with run state, snapshots, and optional git worktrees
6. persist reports, failure classification, approvals, and scheduler history

For AutoDev, the right generalization is a coding-first runtime that turns a change request into a durable execution record:

`request -> plan -> implement -> validate -> review -> approve/merge -> record state`

That pattern is portable across languages, frameworks, and repositories.

## What Can Be Generalized Cleanly

### 1. Backlog-driven execution

AlphaDesk separates long-lived backlog items from short-lived executable tasks. That is a strong pattern for AutoDev.

Generalize this as:

- `BacklogItem`: product or engineering intent, acceptance criteria, dependencies, priority, execution metadata
- `Task`: one executable phase derived from a backlog item
- `TaskResult`: the persisted outcome of a single phase execution

Why this matters:

- the backlog is stable and human-readable
- generated tasks are ephemeral and runtime-friendly
- retries can happen at the task layer without corrupting the original request
- operators can inspect what the runtime intended versus what it actually executed

For coding runtimes, each backlog item should represent one reviewable software change, not a vague initiative.

### 2. A standard phase graph for code changes

AlphaDesk repeatedly uses the same phased execution shape:

- `plan`
- `implement`
- `test`
- `review`
- optional `deploy`

This phase graph is highly reusable. AutoDev should make it the default execution template for development work.

Recommended semantics:

- `plan`: scope the request, inspect repo context, define target files, risks, and validation criteria
- `implement`: apply the smallest viable code/documentation changes
- `validate`: run targeted lint/build/test checks derived from changed files or explicit commands
- `review`: verify acceptance criteria, summarize diff, check policy/safety rules, request approval if needed
- `merge` or `deploy`: optional promotion step once review and approval conditions are satisfied

For AutoDev, rename `test` to `validate` if the phase may include linting, typing, build checks, contract tests, or smoke tests.

### 3. Materialize tasks from backlog items at runtime

A strong AlphaDesk pattern is delayed task generation. The runtime does not store every phase up front forever. It expands eligible backlog items into executable tasks only when dependencies are satisfied and batch budget allows.

AutoDev should keep this behavior because it provides:

- better control over concurrency
- cleaner retry semantics
- easier scheduling and prioritization
- simpler operator visibility into what is active right now

Recommended rule:

- backlog items remain `planned` until all backlog-level dependencies are complete
- once eligible, the runtime generates the phase tasks for exactly one change request or a small bounded batch
- execution updates the backlog item state to `active`, `blocked`, or `completed`

### 4. Shared scheduler + dependency graph

AlphaDesk's scheduler is intentionally simple: validate the task graph, compute runnable tasks from completed dependencies, and choose the highest-priority runnable item.

That design generalizes well.

AutoDev should preserve these core rules:

- reject duplicate task IDs
- reject missing dependencies
- reject dependency cycles
- derive runnable tasks from dependency completion, not timestamps alone
- choose the next task by a deterministic priority order

Keep the scheduler deterministic. That makes autonomous runs easier to reason about, replay, and audit.

### 5. Agent registry with phase contracts

AlphaDesk maps a task's assigned phase to a registered agent implementation. This is a good plug-in boundary.

AutoDev should generalize this into phase contracts rather than hard-coded personalities:

- `Planner`
- `Implementer`
- `Validator`
- `Reviewer`
- `Promoter`

Each phase handler should accept a normalized task payload and return a normalized result payload. The runtime should not need to know whether the handler is backed by an LLM, a scripted toolchain, or a human approval step.

Minimum contract:

```json
{
  "task_id": "feature-123__validate",
  "status": "completed",
  "message": "Targeted validation passed",
  "artifacts": ["reports/feature-123_validation.json"],
  "metrics": {"duration_seconds": 18.2}
}
```

### 6. Durable runtime state

AlphaDesk persists backlog, tasks, reports, scheduler state, review decisions, deployment history, and per-run metadata under predictable directories. That is worth keeping, even if AutoDev chooses different paths.

AutoDev should persist at least:

- backlog state
- task state
- execution reports
- per-run workspace metadata
- validation results
- review decisions
- scheduler state and history
- failure classifications

Durability matters because autonomous coding systems are long-running and frequently interrupted.

### 7. Targeted validation based on changed files

One of the most useful patterns in AlphaDesk is targeted validation. Instead of always running the entire repo, the runtime derives the smallest reasonable validation set from changed files, then falls back to broader checks only when necessary.

This should absolutely carry into AutoDev.

Recommended behavior:

- if the request defines explicit validation commands, use them
- otherwise infer lint/type/test targets from changed files
- stop on first meaningful failure unless configured otherwise
- persist exact commands, exit codes, stdout, and stderr
- classify failure so the scheduler knows whether retry is sensible

This is the difference between a practical coding runtime and an expensive demo loop.

### 8. Review gates before promotion

AlphaDesk treats review as a first-class phase, not a side effect of testing. That is directly transferable.

AutoDev should add automated review gates such as:

- diff exists and is non-empty
- validation passed
- acceptance criteria are present
- changed files do not expose obvious secrets
- optional policy checks passed
- optional human approval recorded

Review should produce a structured decision, not just text. Suggested decisions:

- `approved`
- `changes_requested`
- `blocked`
- `awaiting_human_approval`

### 9. Safe execution isolation

AlphaDesk uses per-run git branches, optional worktrees, snapshots, diff summaries, and rollback helpers. That is one of the most important pieces to generalize.

For AutoDev, safe isolation should be a core runtime feature, not an add-on.

Recommended levels:

- Level 0: direct in-place edits with snapshots
- Level 1: branch-per-run isolation
- Level 2: worktree-per-run isolation
- Level 3: container or sandbox execution for untrusted commands

At minimum, AutoDev should support:

- snapshotting files before edit
- diff generation after edit
- run-local workspace metadata
- optional rollback on failure
- optional promote-on-success behavior

### 10. Failure classification and retry policy

AlphaDesk distinguishes retryable failures from code/test failures and manual-intervention failures. This is very useful and should transfer directly.

AutoDev should classify failures into at least:

- `retryable`: transient model/tool/network failures
- `validation_failure`: lint/build/test/type failure caused by the change
- `policy_failure`: approval/security/compliance stop
- `environment_failure`: missing tools, bad credentials, invalid environment
- `manual_intervention`: ambiguity, merge conflict, unsafe action, or unrecoverable repo state

That classification should drive scheduling behavior:

- retry retryable failures with bounded backoff
- do not auto-retry validation failures without a new implementation attempt
- do not auto-promote after policy or manual-intervention failures

### 11. Scheduler state for recurring autonomous work

AlphaDesk stores last run, next run, retries, and history per pipeline. This is portable even if AutoDev starts as an on-demand tool.

If AutoDev wants a background execution mode, it should preserve:

- pipeline enablement
- per-pipeline interval
- backoff policy
- retry counts
- run history

That enables both one-shot execution and daemon-style operation using `cron`, `launchd`, `systemd`, or a hosted scheduler.

### 12. Operator-facing artifacts

AlphaDesk generates dashboards, backlog editors, review queues, and health reports. The exact HTML surfaces are product-specific, but the concept is portable.

AutoDev does not need to copy the UI, but it should expose operator artifacts such as:

- current backlog view
- active runs
- validation history
- review queue
- failure summary
- scheduler status

In open source, these can start as markdown and JSON before becoming a web UI.

## Recommended Portable Data Model

AutoDev should keep a thin, stable schema layer.

### Backlog item

```json
{
  "item_id": "dev-123",
  "title": "Add retry-safe webhook handler",
  "description": "Implement idempotent webhook processing and tests.",
  "status": "planned",
  "priority": "high",
  "dependencies": ["dev-122"],
  "acceptance_criteria": [
    "duplicate deliveries do not double-apply side effects",
    "handler failures are logged with request IDs",
    "tests cover duplicate and out-of-order events"
  ],
  "change_request": {
    "target_files": [
      "src/webhooks/handler.ts",
      "tests/webhooks/handler.test.ts"
    ]
  },
  "validation": {
    "commands": [],
    "profiles": ["test"]
  },
  "promotion": {
    "approval_required": true,
    "merge_on_success": false
  }
}
```

### Task

```json
{
  "task_id": "dev-123__implement",
  "phase": "implement",
  "status": "queued",
  "dependencies": ["dev-123__plan"],
  "assigned_handler": "implementer",
  "metadata": {
    "backlog_item_id": "dev-123",
    "run_id": "dev-123-20260316T120000Z",
    "workspace_root": ".autodev/runs/dev-123/worktree"
  }
}
```

### Pipeline config

```json
{
  "pipeline_id": "development",
  "task_batch_size": 1,
  "phase_sequence": ["plan", "implement", "validate", "review"],
  "scheduler": {
    "enabled": false,
    "interval_minutes": 30,
    "max_retries": 2,
    "backoff_minutes": 15
  }
}
```

## Recommended Execution Algorithm

AutoDev's coding runtime can be built around the following loop:

1. load pipeline config, backlog, task state, and scheduler state
2. select backlog items whose backlog-level dependencies are complete
3. materialize phase tasks for the next eligible item or bounded batch
4. create or attach run workspace metadata
5. execute tasks in dependency order using the phase registry
6. after implementation, snapshot changed files and persist diff summary
7. run targeted validation
8. run review gates and decide whether promotion is allowed
9. update backlog item status to `completed`, `blocked`, `planned`, or `active`
10. persist reports, failure classification, artifacts, and scheduler history

Pseudocode:

```text
while runtime_has_budget:
  sync_backlog_and_tasks()
  eligible_items = backlog.items_ready_for_materialization()
  materialize_next_items(eligible_items, batch_size)

  task = scheduler.next_runnable(tasks)
  if not task:
    break

  result = phase_registry.execute(task)
  persist(result)
  update_task_status(task, result)
  update_backlog_status(task.backlog_item_id)

  if result.failed:
    classification = classify_failure(result)
    apply_retry_or_block_policy(task, classification)
```

## What Is AlphaDesk-Specific and Should Not Be Copied Blindly

These parts are useful examples but should not become AutoDev defaults:

- local operator HTML pages as the primary UX
- AlphaDesk's development/research dual-pipeline split
- builder-specific artifact generation for dashboard/report products
- AlphaDesk directory names such as `reports/`, `state/`, and `tasks/` as hard requirements
- fixed agent names tied to one repo's prompt design
- local-only secrets/config conventions as the only supported environment model

AutoDev should keep the runtime pattern and replace the product-specific surfaces with interfaces that fit a broader contributor base.

## Recommended AutoDev Runtime Shape

If the goal is an open-source autonomous coding runtime, the best distilled version is:

### Core subsystems

- `backlog service`: stores change requests and dependencies
- `task materializer`: expands backlog items into phase tasks
- `scheduler`: selects the next runnable task deterministically
- `phase registry`: planner, implementer, validator, reviewer, promoter
- `workspace manager`: snapshots, branches, worktrees, sandboxing
- `validation engine`: infers and runs targeted checks
- `review engine`: applies approval and policy gates
- `state store`: backlog, tasks, runs, reports, decisions, retries, history
- `operator surface`: CLI first, JSON/markdown artifacts, optional web UI later

### Default coding pipeline

- `intake`: normalize user issue, prompt, or PR comment into a backlog item
- `plan`: inspect repo and produce a bounded implementation plan
- `implement`: edit code and docs in an isolated workspace
- `validate`: run targeted repo checks
- `review`: summarize diff and check acceptance criteria
- `promote`: request approval, merge, or emit a patch bundle

### Optional extensions

- multi-agent planning and debate
- language-specific validators
- repository memory and architecture context refresh
- CI handoff after local validation
- deploy/publish phases for repos that need release automation

## Suggested MVP for AutoDev

If AutoDev wants the smallest useful adaptation of this model, implement these in order:

1. durable backlog item schema
2. task graph + deterministic scheduler
3. phase registry for `plan -> implement -> validate -> review`
4. per-run workspace isolation with snapshots
5. targeted validation inference from changed files
6. failure classification + bounded retries
7. structured review decision output
8. simple scheduler state for repeated runs

That gets most of the value without requiring AlphaDesk's UI or product-specific artifact builders.

## Bottom Line

The reusable contribution from AlphaDesk is a durable execution model for autonomous coding:

- backlog items represent intent
- runtime-generated phase tasks represent execution
- deterministic scheduling controls flow
- isolated workspaces control risk
- targeted validation controls cost
- review gates control quality
- persisted state makes the system inspectable and resumable

That model should generalize well to AutoDev and is likely more valuable to share than any specific prompt, agent wording, or dashboard implementation.
