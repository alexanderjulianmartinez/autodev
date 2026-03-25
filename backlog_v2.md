# AutoDev Runtime v0.2 Backlog

This backlog captures the major work needed to extend the current AutoDev runtime toward the integration-focused system described in [docs/tech_spec_v02.md](docs/tech_spec_v02.md).

It is written so each item could later become one GitHub issue or one small issue cluster.

## Current Baseline

The repository already has:

- a Python package and CLI scaffold
- durable runtime schemas, state storage, scheduling, and workspace isolation
- phase-based execution for `plan -> implement -> validate -> review`
- initial GitHub issue and PR helpers
- baseline tests for the current runtime foundations

The biggest gaps for v0.2 are:

- no general integration interface or plugin registry
- no unified abstraction across Git providers, issue trackers, CI systems, and monitoring tools
- no config-driven integration selection or capability discovery
- no command abstraction layer for workflows like `fix-ci` and `fix-error`
- no execution replay, approval checkpoints, or persistent operator-facing history
- no repository knowledge graph or persistent memory layer
- no metrics and experimentation loop for optimizing runtime behavior

## Suggested Labels

- `priority:p0`, `priority:p1`, `priority:p2`
- `type:core`, `type:cli`, `type:integration`, `type:github`, `type:ci`, `type:monitoring`, `type:knowledge`, `type:data`, `type:docs`
- `milestone:v0.2-foundation`, `milestone:v0.2-integrations`, `milestone:v0.2-operator`, `milestone:v0.2-intelligence`

## Milestone 9: Integration Architecture Foundations

### AD-028 Define base integration interfaces and typed capability contracts

- **Priority:** `priority:p0`
- **Type:** `type:core`
- **Problem:** The repo has provider-specific helpers, but no common interface for fetch, update, execute, or capability discovery across external systems.
- **Scope:** Introduce stable base interfaces and typed request/response models for Git providers, issue trackers, CI systems, monitoring systems, messaging systems, and documentation providers.
- **Acceptance criteria:**
  - each integration type has a small, explicit interface with typed inputs and outputs
  - capability metadata can describe what a provider supports without provider-specific branching in runtime code
  - provider adapters can be swapped without changing orchestration logic

### AD-029 Add a plugin registry and config-driven integration loading

- **Priority:** `priority:p0`
- **Type:** `type:integration`
- **Problem:** The runtime cannot currently enable, disable, or select integrations declaratively.
- **Scope:** Build a plugin registry that loads providers from configuration, validates required settings, and exposes integration instances by capability.
- **Acceptance criteria:**
  - integration configuration can select one provider per capability such as `git`, `issue_tracker`, `ci`, and `monitoring`
  - invalid or incomplete integration config fails early with actionable diagnostics
  - runtime code can resolve integrations through the registry instead of constructing adapters directly

### AD-030 Scaffold the integration package structure and shared mapping models

- **Priority:** `priority:p1`
- **Type:** `type:integration`
- **Problem:** The current package layout does not provide a clear home for the broader integration surface described in the v0.2 spec.
- **Scope:** Add an `autodev/integrations/` package, shared domain models, normalization helpers, and package-level documentation for future adapters.
- **Acceptance criteria:**
  - the repo has a dedicated package structure for integration plugins and shared models
  - normalized models exist for external entities such as issues, pull requests, CI runs, and error events
  - package docs explain how new integrations should be added and tested

## Milestone 10: Tier 1 Workflow Integrations

### AD-031 Build a unified Git platform abstraction with GitHub as the reference implementation

- **Priority:** `priority:p0`
- **Type:** `type:github`
- **Problem:** Git platform logic is currently GitHub-shaped, which will make GitLab and Bitbucket support expensive to add later.
- **Scope:** Define a shared Git platform adapter surface for repository metadata, branches, commits, pull requests, comments, and status links, then adapt the current GitHub helpers to that surface.
- **Acceptance criteria:**
  - GitHub functionality is exposed through a provider-neutral interface
  - pull request creation and issue linking operate through the shared abstraction
  - the design leaves clear extension points for GitLab and Bitbucket providers

### AD-032 Add issue tracker integration contracts and implement Jira ticket intake

- **Priority:** `priority:p0`
- **Type:** `type:integration`
- **Problem:** The runtime can start from GitHub issues, but it cannot yet ingest the broader ticket-based workflows called out in the spec.
- **Scope:** Define issue tracker interfaces and implement Jira support for fetching tickets, normalizing fields, mapping tickets to repositories, and posting progress updates.
- **Acceptance criteria:**
  - `autodev run JIRA-123` can resolve a Jira ticket into a normalized backlog item
  - ticket metadata includes title, description, status, labels, assignee, and acceptance criteria when available
  - the runtime can post progress or PR links back to Jira through the shared interface

### AD-033 Add Linear integration and repository-resolution rules for ticket-driven runs

- **Priority:** `priority:p1`
- **Type:** `type:integration`
- **Problem:** Supporting more than one tracker is necessary to validate the integration architecture and improve adoption.
- **Scope:** Implement Linear on top of the issue tracker abstraction and add configuration for mapping projects, teams, or labels to repositories.
- **Acceptance criteria:**
  - Linear tickets normalize into the same backlog item structure as Jira tickets
  - repository mapping rules are configurable and provider-agnostic
  - provider-specific fields do not leak into downstream runtime phases

## Milestone 11: Tier 2 Daily Usage Workflows

### AD-034 Build a CI provider abstraction and implement GitHub Actions intake for `fix-ci`

- **Priority:** `priority:p0`
- **Type:** `type:ci`
- **Problem:** `fix-ci` is still a stub and there is no normalized way to fetch failed workflow context.
- **Scope:** Introduce CI provider interfaces and implement GitHub Actions log/run ingestion that can create backlog items from failures.
- **Acceptance criteria:**
  - failed workflow runs can be fetched and normalized into a standard CI failure payload
  - `autodev fix-ci` creates a backlog item with logs, failing step details, and candidate validation commands
  - the resulting run follows the normal phase pipeline and persists CI-specific artifacts

### AD-035 Extend CI coverage to CircleCI and Jenkins with shared failure normalization

- **Priority:** `priority:p1`
- **Type:** `type:ci`
- **Problem:** A single CI integration will not fully validate the abstraction or cover common real-world workflows.
- **Scope:** Implement CircleCI and Jenkins adapters on the shared CI interface, focusing on failure metadata, logs, and build URLs.
- **Acceptance criteria:**
  - CircleCI and Jenkins failures normalize into the same internal model as GitHub Actions failures
  - provider differences are isolated inside adapters rather than orchestration code
  - tests cover baseline normalization behavior across all supported CI adapters

### AD-036 Expand code review support into a first-class PR review workflow

- **Priority:** `priority:p1`
- **Type:** `type:github`
- **Problem:** The runtime can review its own implementation artifacts, but it does not yet support the `autodev review <pr>` workflow from the spec.
- **Scope:** Add PR review intake, diff analysis, architecture-rule hooks, and structured suggestion output on top of the existing review engine.
- **Acceptance criteria:**
  - a PR identifier can be resolved into diff, metadata, and validation context
  - review output distinguishes bugs, design concerns, and style suggestions
  - architecture or policy checks can be plugged into PR review without rewriting the core review phase

### AD-037 Add monitoring provider interfaces and implement Sentry or Datadog error intake for `fix-error`

- **Priority:** `priority:p1`
- **Type:** `type:monitoring`
- **Problem:** The runtime has no path from production error signals to actionable repair work.
- **Scope:** Add monitoring interfaces and implement one initial provider with support for fetching error events, stack traces, tags, and suspect commit metadata.
- **Acceptance criteria:**
  - `autodev fix-error` can create a backlog item from a normalized production error event
  - error artifacts include stack trace, environment metadata, and linked release information when available
  - monitoring-specific details remain isolated behind the provider interface

## Milestone 12: Operator Experience and Control

### AD-038 Add a command abstraction layer for common autonomous workflows

- **Priority:** `priority:p0`
- **Type:** `type:cli`
- **Problem:** High-value workflows such as `fix-ci`, `fix-test`, `fix-error`, and `implement-feature` need deterministic entrypoints instead of ad hoc command handling.
- **Scope:** Introduce a command registry that maps operator commands to deterministic intake + execution pipelines.
- **Acceptance criteria:**
  - commands resolve to explicit pipeline definitions instead of scattered conditional logic
  - command metadata explains required inputs, enabled integrations, and resulting artifacts
  - adding a new command does not require editing the core orchestration loop

### AD-039 Implement human-in-the-loop approval checkpoints

- **Priority:** `priority:p0`
- **Type:** `type:core`
- **Problem:** The spec requires approval gates, but the runtime has no reusable approval mechanism for plan, code, or promotion phases.
- **Scope:** Add approval checkpoint models, CLI prompts or artifact-based approvals, and runtime gating behavior for `--approve` mode.
- **Acceptance criteria:**
  - plan, implementation, and promotion checkpoints can require explicit approval when enabled
  - approval state is persisted and resumable
  - the scheduler can pause and resume cleanly around approval boundaries

### AD-040 Implement execution replay and run audit artifacts

- **Priority:** `priority:p1`
- **Type:** `type:cli`
- **Problem:** Operators cannot yet inspect prior runs as a coherent sequence of decisions, prompts, tool actions, and changes.
- **Scope:** Add a replay-friendly event model and a `replay <run_id>` CLI path that renders key execution artifacts in order.
- **Acceptance criteria:**
  - runs persist enough structured events to reconstruct the execution sequence
  - replay output includes decisions, prompts, file changes, failures, and review outcomes
  - replay works for both completed and failed runs

## Milestone 13: Intelligence and Data Compounding

### AD-041 Build a repository knowledge graph v1 for planning and validation

- **Priority:** `priority:p1`
- **Type:** `type:knowledge`
- **Problem:** Repository understanding is currently shallow and largely prompt-driven, limiting planning accuracy and multi-file reasoning.
- **Scope:** Build a first-pass repository knowledge graph using AST parsing, dependency extraction, and cross-file reference indexing.
- **Acceptance criteria:**
  - the runtime can persist structured knowledge about files, symbols, imports, and references
  - planner and validator phases can query the graph for likely impact and dependency hints
  - graph generation is incremental or bounded enough for practical local use

### AD-042 Add persistent memory for prior runs, failure patterns, and repository heuristics

- **Priority:** `priority:p1`
- **Type:** `type:data`
- **Problem:** The runtime does not yet learn from prior executions, repeated failures, or successful fix patterns.
- **Scope:** Store reusable summaries from previous runs, validation outcomes, and repair strategies in a provider-neutral memory layer.
- **Acceptance criteria:**
  - past runs can contribute lightweight suggestions to planning and validation
  - memory records are scoped so they do not contaminate unrelated repositories
  - operators can inspect or clear stored memory explicitly

### AD-043 Add metrics, experiment tracking, and model/provider performance reporting

- **Priority:** `priority:p1`
- **Type:** `type:data`
- **Problem:** The v0.2 design depends on measuring success rates and execution quality, but the runtime lacks structured telemetry for these outcomes.
- **Scope:** Track task success rate, time to PR, retry count, validation pass rate, and model/provider-level execution metrics.
- **Acceptance criteria:**
  - core run metrics are persisted per task and per run
  - metrics can be aggregated by command, integration provider, and model route
  - the design leaves room for later experimentation and optimization loops

## Milestone 14: Advanced Automation Readiness

### AD-044 Design containerized execution support for reproducible and sandboxed runs

- **Priority:** `priority:p2`
- **Type:** `type:core`
- **Problem:** The spec calls for sandboxed execution, but current isolation focuses on local filesystem and git boundaries only.
- **Scope:** Add a container execution abstraction and baseline Docker-oriented design for running phases in reproducible environments.
- **Acceptance criteria:**
  - runtime execution can target either local or containerized isolation through a shared interface
  - environment requirements and bind mounts are explicit and testable
  - failure modes for missing images, build errors, and command timeouts are classified clearly

### AD-045 Add messaging integration interfaces for Slack and Discord task intake

- **Priority:** `priority:p2`
- **Type:** `type:integration`
- **Problem:** Chat-driven task creation is a likely adoption lever, but no messaging integration surface exists yet.
- **Scope:** Define messaging interfaces and support slash-command or webhook-driven intake that creates backlog items from authorized requests.
- **Acceptance criteria:**
  - messaging requests normalize into the same intake model as CLI and ticket-driven runs
  - authorization and audit metadata are persisted with the created backlog item
  - provider-specific transport details remain outside core runtime logic

### AD-046 Design the deployment and cloud-provider abstraction for guarded `deploy` workflows

- **Priority:** `priority:p2`
- **Type:** `type:integration`
- **Problem:** Deployment automation is in the long-term roadmap, but there is no clear abstraction for cloud targets, health checks, or rollback contracts.
- **Scope:** Define the deployment provider interface, rollout lifecycle, health-check contracts, and rollback triggers for later AWS, GCP, and Azure support.
- **Acceptance criteria:**
  - deployment steps are modeled as a deterministic pipeline with preflight, deploy, verify, and rollback stages
  - provider-neutral rollout and health-check models exist before any cloud-specific adapter is implemented
  - the design clearly separates deployment planning from execution credentials and secrets handling

## Milestone 15: Documentation and Adoption Support

### AD-047 Document the integration architecture, plugin authoring model, and operator workflows

- **Priority:** `priority:p1`
- **Type:** `type:docs`
- **Problem:** The v0.2 architecture adds several new extension surfaces that will be difficult to adopt without contributor and operator documentation.
- **Scope:** Document integration interfaces, plugin registration, provider configuration, command workflows, and approval/replay behavior.
- **Acceptance criteria:**
  - contributors have a clear guide for adding a new integration provider
  - operators can configure supported providers and run the main workflows locally
  - the docs reflect the actual code structure and execution model

## First Recommended Issue Slice

If the goal is to deliver the highest-leverage v0.2 path first, implement these first:

1. AD-028 Define base integration interfaces and typed capability contracts
2. AD-029 Add a plugin registry and config-driven integration loading
3. AD-031 Build a unified Git platform abstraction with GitHub as the reference implementation
4. AD-032 Add issue tracker integration contracts and implement Jira ticket intake
5. AD-034 Build a CI provider abstraction and implement GitHub Actions intake for `fix-ci`
6. AD-038 Add a command abstraction layer for common autonomous workflows
7. AD-039 Implement human-in-the-loop approval checkpoints
8. AD-040 Implement execution replay and run audit artifacts
9. AD-041 Build a repository knowledge graph v1 for planning and validation
10. AD-043 Add metrics, experiment tracking, and model/provider performance reporting

That sequence keeps the current runtime foundations intact while opening the strongest adoption paths from tickets, CI failures, and operator-facing workflows.
