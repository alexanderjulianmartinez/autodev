# AD-038 Add a command abstraction layer for common autonomous workflows

## Backlog Metadata

- Source: `backlog_v2.md`
- Backlog item: `AD-038`
- Milestone: Operator Experience and Control
- Suggested labels: priority:p0, type:cli

## Problem

High-value workflows such as `fix-ci`, `fix-test`, `fix-error`, and `implement-feature` need deterministic entrypoints instead of ad hoc command handling.

## Scope

Introduce a command registry that maps operator commands to deterministic intake + execution pipelines.

## Acceptance Criteria

- commands resolve to explicit pipeline definitions instead of scattered conditional logic
- command metadata explains required inputs, enabled integrations, and resulting artifacts
- adding a new command does not require editing the core orchestration loop
