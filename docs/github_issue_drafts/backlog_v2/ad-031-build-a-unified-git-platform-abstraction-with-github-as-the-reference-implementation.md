# AD-031 Build a unified Git platform abstraction with GitHub as the reference implementation

## Backlog Metadata

- Source: `backlog_v2.md`
- Backlog item: `AD-031`
- Milestone: Tier 1 Workflow Integrations
- Suggested labels: priority:p0, type:github

## Problem

Git platform logic is currently GitHub-shaped, which will make GitLab and Bitbucket support expensive to add later.

## Scope

Define a shared Git platform adapter surface for repository metadata, branches, commits, pull requests, comments, and status links, then adapt the current GitHub helpers to that surface.

## Acceptance Criteria

- GitHub functionality is exposed through a provider-neutral interface
- pull request creation and issue linking operate through the shared abstraction
- the design leaves clear extension points for GitLab and Bitbucket providers
