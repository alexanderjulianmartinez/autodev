# AD-030 Scaffold the integration package structure and shared mapping models

## Backlog Metadata

- Source: `backlog_v2.md`
- Backlog item: `AD-030`
- Milestone: Integration Architecture Foundations
- Suggested labels: priority:p1, type:integration

## Problem

The current package layout does not provide a clear home for the broader integration surface described in the v0.2 spec.

## Scope

Add an `autodev/integrations/` package, shared domain models, normalization helpers, and package-level documentation for future adapters.

## Acceptance Criteria

- the repo has a dedicated package structure for integration plugins and shared models
- normalized models exist for external entities such as issues, pull requests, CI runs, and error events
- package docs explain how new integrations should be added and tested
