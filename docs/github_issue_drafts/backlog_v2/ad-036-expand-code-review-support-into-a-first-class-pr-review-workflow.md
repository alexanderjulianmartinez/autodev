# AD-036 Expand code review support into a first-class PR review workflow

## Backlog Metadata

- Source: `backlog_v2.md`
- Backlog item: `AD-036`
- Milestone: Tier 2 Daily Usage Workflows
- Suggested labels: priority:p1, type:github

## Problem

The runtime can review its own implementation artifacts, but it does not yet support the `autodev review <pr>` workflow from the spec.

## Scope

Add PR review intake, diff analysis, architecture-rule hooks, and structured suggestion output on top of the existing review engine.

## Acceptance Criteria

- a PR identifier can be resolved into diff, metadata, and validation context
- review output distinguishes bugs, design concerns, and style suggestions
- architecture or policy checks can be plugged into PR review without rewriting the core review phase
