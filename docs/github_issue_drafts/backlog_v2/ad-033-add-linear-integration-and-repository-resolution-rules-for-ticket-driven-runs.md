# AD-033 Add Linear integration and repository-resolution rules for ticket-driven runs

## Backlog Metadata

- Source: `backlog_v2.md`
- Backlog item: `AD-033`
- Milestone: Tier 1 Workflow Integrations
- Suggested labels: priority:p1, type:integration

## Problem

Supporting more than one tracker is necessary to validate the integration architecture and improve adoption.

## Scope

Implement Linear on top of the issue tracker abstraction and add configuration for mapping projects, teams, or labels to repositories.

## Acceptance Criteria

- Linear tickets normalize into the same backlog item structure as Jira tickets
- repository mapping rules are configurable and provider-agnostic
- provider-specific fields do not leak into downstream runtime phases
