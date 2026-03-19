# AutoDev Runtime Tech Spec v0.1

AutoDev is an open-source autonomous development runtime for turning a change request into a durable, reviewable execution flow.

The core model is:

`request -> plan -> implement -> validate -> review -> approve/merge -> record state`

Instead of treating autonomous coding as an open-ended chat loop, AutoDev treats it as a deterministic pipeline with durable state, isolated workspaces, targeted validation, and explicit review gates.

## What AutoDev Optimizes For

- durable backlog items instead of ephemeral prompts
- deterministic scheduling instead of free-form agent loops
- isolated execution instead of risky in-place mutation
- targeted validation instead of always running the whole repository
- structured review decisions instead of unstructured summaries
- resumable state instead of losing progress between runs

## Core Runtime Shape

The proposed runtime is built from a small set of reusable subsystems:

- backlog service
- task materializer
- deterministic scheduler
- phase registry
- workspace manager
- validation engine
- review engine
- state store
- operator-facing CLI and artifacts

The default coding pipeline is:

1. `intake`: normalize a user request, issue, or PR comment into a backlog item
2. `plan`: inspect repository context and define a bounded implementation plan
3. `implement`: apply the smallest viable code and documentation changes
4. `validate`: run targeted checks inferred from changed files or explicit commands
5. `review`: evaluate acceptance criteria, diff quality, and policy gates
6. `promote`: request approval, merge, or emit a patch bundle when enabled

## MVP Priorities

The smallest useful AutoDev implementation should deliver these pieces in order:

1. durable backlog item schema
2. task graph and deterministic scheduler
3. phase registry for `plan -> implement -> validate -> review`
4. per-run workspace isolation with snapshots
5. targeted validation inference from changed files
6. failure classification with bounded retries
7. structured review decision output
8. basic scheduler state for repeated runs

## Principles

- model-agnostic runtime with pluggable handlers
- local-first execution with optional GitHub and CI integration
- deterministic, inspectable state transitions
- minimal reviewable changes per backlog item
- safe promotion only after validation and review gates pass

## Documents

- Full system design: [system_design.md](system_design.md)

## Current Status

This repository is currently documentation-first. The design doc captures the runtime architecture to implement next and distills the reusable execution model from AlphaDesk into an AutoDev-friendly shape.

## Near-Term Build Plan

- define stable backlog, task, run, and review schemas
- implement the task materializer and deterministic scheduler
- add phase handler contracts for planner, implementer, validator, and reviewer
- add workspace isolation with snapshots and diff capture
- add targeted validation selection and persisted reports
