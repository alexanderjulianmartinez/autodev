# AD-040 Implement execution replay and run audit artifacts

## Backlog Metadata

- Source: `backlog_v2.md`
- Backlog item: `AD-040`
- Milestone: Operator Experience and Control
- Suggested labels: priority:p1, type:cli

## Problem

Operators cannot yet inspect prior runs as a coherent sequence of decisions, prompts, tool actions, and changes.

## Scope

Add a replay-friendly event model and a `replay <run_id>` CLI path that renders key execution artifacts in order.

## Acceptance Criteria

- runs persist enough structured events to reconstruct the execution sequence
- replay output includes decisions, prompts, file changes, failures, and review outcomes
- replay works for both completed and failed runs
