# AD-039 Implement human-in-the-loop approval checkpoints

## Backlog Metadata

- Source: `backlog_v2.md`
- Backlog item: `AD-039`
- Milestone: Operator Experience and Control
- Suggested labels: priority:p0, type:core

## Problem

The spec requires approval gates, but the runtime has no reusable approval mechanism for plan, code, or promotion phases.

## Scope

Add approval checkpoint models, CLI prompts or artifact-based approvals, and runtime gating behavior for `--approve` mode.

## Acceptance Criteria

- plan, implementation, and promotion checkpoints can require explicit approval when enabled
- approval state is persisted and resumable
- the scheduler can pause and resume cleanly around approval boundaries
