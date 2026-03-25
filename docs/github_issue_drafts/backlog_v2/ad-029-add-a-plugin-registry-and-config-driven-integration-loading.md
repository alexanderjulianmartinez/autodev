# AD-029 Add a plugin registry and config-driven integration loading

## Backlog Metadata

- Source: `backlog_v2.md`
- Backlog item: `AD-029`
- Milestone: Integration Architecture Foundations
- Suggested labels: priority:p0, type:integration

## Problem

The runtime cannot currently enable, disable, or select integrations declaratively.

## Scope

Build a plugin registry that loads providers from configuration, validates required settings, and exposes integration instances by capability.

## Acceptance Criteria

- integration configuration can select one provider per capability such as `git`, `issue_tracker`, `ci`, and `monitoring`
- invalid or incomplete integration config fails early with actionable diagnostics
- runtime code can resolve integrations through the registry instead of constructing adapters directly
