# AD-041 Build a repository knowledge graph v1 for planning and validation

## Backlog Metadata

- Source: `backlog_v2.md`
- Backlog item: `AD-041`
- Milestone: Intelligence and Data Compounding
- Suggested labels: priority:p1, type:knowledge

## Problem

Repository understanding is currently shallow and largely prompt-driven, limiting planning accuracy and multi-file reasoning.

## Scope

Build a first-pass repository knowledge graph using AST parsing, dependency extraction, and cross-file reference indexing.

## Acceptance Criteria

- the runtime can persist structured knowledge about files, symbols, imports, and references
- planner and validator phases can query the graph for likely impact and dependency hints
- graph generation is incremental or bounded enough for practical local use
