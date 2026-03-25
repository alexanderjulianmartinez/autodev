# AD-043 Add metrics, experiment tracking, and model/provider performance reporting

## Backlog Metadata

- Source: `backlog_v2.md`
- Backlog item: `AD-043`
- Milestone: Intelligence and Data Compounding
- Suggested labels: priority:p1, type:data

## Problem

The v0.2 design depends on measuring success rates and execution quality, but the runtime lacks structured telemetry for these outcomes.

## Scope

Track task success rate, time to PR, retry count, validation pass rate, and model/provider-level execution metrics.

## Acceptance Criteria

- core run metrics are persisted per task and per run
- metrics can be aggregated by command, integration provider, and model route
- the design leaves room for later experimentation and optimization loops
