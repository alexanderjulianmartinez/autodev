# AD-037 Add monitoring provider interfaces and implement Sentry or Datadog error intake for `fix-error`

## Backlog Metadata

- Source: `backlog_v2.md`
- Backlog item: `AD-037`
- Milestone: Tier 2 Daily Usage Workflows
- Suggested labels: priority:p1, type:monitoring

## Problem

The runtime has no path from production error signals to actionable repair work.

## Scope

Add monitoring interfaces and implement one initial provider with support for fetching error events, stack traces, tags, and suspect commit metadata.

## Acceptance Criteria

- `autodev fix-error` can create a backlog item from a normalized production error event
- error artifacts include stack trace, environment metadata, and linked release information when available
- monitoring-specific details remain isolated behind the provider interface
