# AD-034 Build a CI provider abstraction and implement GitHub Actions intake for `fix-ci`

## Backlog Metadata

- Source: `backlog_v2.md`
- Backlog item: `AD-034`
- Milestone: Tier 2 Daily Usage Workflows
- Suggested labels: priority:p0, type:ci

## Problem

fix-ci` is still a stub and there is no normalized way to fetch failed workflow context.

## Scope

Introduce CI provider interfaces and implement GitHub Actions log/run ingestion that can create backlog items from failures.

## Acceptance Criteria

- failed workflow runs can be fetched and normalized into a standard CI failure payload
- `autodev fix-ci` creates a backlog item with logs, failing step details, and candidate validation commands
- the resulting run follows the normal phase pipeline and persists CI-specific artifacts
