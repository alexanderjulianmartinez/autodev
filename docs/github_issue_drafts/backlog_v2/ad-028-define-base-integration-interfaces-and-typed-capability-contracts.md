# AD-028 Define base integration interfaces and typed capability contracts

## Backlog Metadata

- Source: `backlog_v2.md`
- Backlog item: `AD-028`
- Milestone: Integration Architecture Foundations
- Suggested labels: priority:p0, type:core

## Problem

The repo has provider-specific helpers, but no common interface for fetch, update, execute, or capability discovery across external systems.

## Scope

Introduce stable base interfaces and typed request/response models for Git providers, issue trackers, CI systems, monitoring systems, messaging systems, and documentation providers.

## Acceptance Criteria

- each integration type has a small, explicit interface with typed inputs and outputs
- capability metadata can describe what a provider supports without provider-specific branching in runtime code
- provider adapters can be swapped without changing orchestration logic
