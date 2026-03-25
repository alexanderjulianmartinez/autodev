# AD-035 Extend CI coverage to CircleCI and Jenkins with shared failure normalization

## Backlog Metadata

- Source: `backlog_v2.md`
- Backlog item: `AD-035`
- Milestone: Tier 2 Daily Usage Workflows
- Suggested labels: priority:p1, type:ci

## Problem

A single CI integration will not fully validate the abstraction or cover common real-world workflows.

## Scope

Implement CircleCI and Jenkins adapters on the shared CI interface, focusing on failure metadata, logs, and build URLs.

## Acceptance Criteria

- CircleCI and Jenkins failures normalize into the same internal model as GitHub Actions failures
- provider differences are isolated inside adapters rather than orchestration code
- tests cover baseline normalization behavior across all supported CI adapters
