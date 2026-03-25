# AD-032 Add issue tracker integration contracts and implement Jira ticket intake

## Backlog Metadata

- Source: `backlog_v2.md`
- Backlog item: `AD-032`
- Milestone: Tier 1 Workflow Integrations
- Suggested labels: priority:p0, type:integration

## Problem

The runtime can start from GitHub issues, but it cannot yet ingest the broader ticket-based workflows called out in the spec.

## Scope

Define issue tracker interfaces and implement Jira support for fetching tickets, normalizing fields, mapping tickets to repositories, and posting progress updates.

## Acceptance Criteria

- `autodev run JIRA-123` can resolve a Jira ticket into a normalized backlog item
- ticket metadata includes title, description, status, labels, assignee, and acceptance criteria when available
- the runtime can post progress or PR links back to Jira through the shared interface
