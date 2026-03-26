# AutoDev Integration Guide

This document explains the architecture of `autodev/integrations/`, the conventions for adding new provider adapters, and how to test them.

## Package layout

```
autodev/integrations/
  __init__.py          — public exports for all types
  base.py              — ProviderCapability, CapabilitySet, IntegrationProvider
  models.py            — shared domain models: EntityRef, ErrorEvent
  normalize.py         — provider-agnostic normalization utilities
  config.py            — IntegrationsConfig, ProviderConfig (YAML-backed)
  registry.py          — IntegrationRegistry (factory registration + resolution)

  git_provider.py      — GitProvider Protocol + request/response models
  issue_tracker.py     — IssueTracker Protocol + request/response models
  ci_system.py         — CISystem Protocol + request/response models
  monitoring.py        — MonitoringSystem Protocol + request/response models
  messaging.py         — MessagingSystem Protocol + request/response models
  docs_provider.py     — DocsProvider Protocol + request/response models
```

## Core concepts

### Protocols, not ABCs

Every integration type is defined as a `typing.Protocol` with `@runtime_checkable`. This means provider adapters implement the interface by structure (duck typing) — they do not inherit from the Protocol class and do not need to import it.

```python
# A GitHub adapter satisfies GitProvider without inheriting from it
class GitHubAdapter:
    def provider_info(self) -> ProviderInfo: ...
    def capabilities(self) -> CapabilitySet: ...
    def fetch_repository(self, request: FetchRepositoryRequest) -> RepositoryInfo: ...
    # ... all other GitProvider methods
```

### Capability-based dispatch

Runtime code resolves providers by `ProviderCapability`, not by adapter type. This keeps orchestration logic decoupled from any specific provider.

```python
# Good: capability-based dispatch
provider = registry.resolve(ProviderCapability.CREATE_PULL_REQUEST)
provider.create_pull_request(request)

# Avoid: provider-type branching
if isinstance(provider, GitHubAdapter):
    provider.create_pull_request_github(...)
```

Use `CapabilitySet.supports()` to guard optional operations:

```python
caps = provider.capabilities()
if caps.supports(ProviderCapability.TRIGGER_RUN):
    ci.trigger_run(TriggerRunRequest(...))
```

Use `CapabilitySet.require()` when the operation is mandatory:

```python
caps.require(ProviderCapability.CREATE_PULL_REQUEST)
pr = git.create_pull_request(request)
```

### Shared domain models

`models.py` contains models that cut across integration types:

- **`EntityRef`** — a cross-system pointer attached to response objects so callers can trace an entity back to its source without importing adapter types.
- **`ErrorEvent`** — a normalized error signal produced from CI failures, monitoring alerts, or runtime errors. Core logic (e.g. `FailureClassifier`) operates on `ErrorEvent` instead of provider-specific payloads.

### Normalization utilities

`normalize.py` provides pure functions that map provider-specific strings to canonical values:

| Function | Maps |
|---|---|
| `normalize_priority(raw)` | `"p0"`, `"CRITICAL"`, `"Major"` → `"critical"` / `"high"` / `"medium"` / `"low"` |
| `normalize_status(raw)` | `"Todo"`, `"IN PROGRESS"`, `"resolved"` → `"open"` / `"in_progress"` / `"closed"` / `"failed"` |
| `normalize_labels(labels)` | strip, lowercase, deduplicate |
| `extract_task_list_items(body)` | parse `- [ ] ...` / `- [x] ...` Markdown |
| `extract_section_items(body, names)` | extract bullet list from a named Markdown section |
| `infer_validation_commands(step_names)` | map CI step names → CLI commands |
| `slugify(text)` | `"My Repo!"` → `"my-repo"` |

Adapters call these before populating their response models to ensure consistent output.

---

## Adding a new adapter

### Step 1 — implement the Protocol

Create a new module (outside this package — e.g. `autodev/github/adapters/github_git.py`) and implement all methods declared by the Protocol for the integration type you are targeting.

```python
# autodev/github/adapters/github_git.py
from autodev.integrations import (
    CapabilitySet, GitProvider, ProviderCapability, ProviderInfo,
    FetchRepositoryRequest, RepositoryInfo,
    CreatePullRequestRequest, PullRequestInfo,
    # ...
)
from autodev.integrations.normalize import normalize_labels, normalize_status

class GitHubGitAdapter:
    def __init__(self, settings: dict[str, str]) -> None:
        self._token = settings["token"]

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            provider_id="github",
            display_name="GitHub",
            capabilities=self.capabilities(),
        )

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            operations=frozenset({
                ProviderCapability.FETCH_REPOSITORY,
                ProviderCapability.CREATE_BRANCH,
                ProviderCapability.CREATE_PULL_REQUEST,
                ProviderCapability.GET_DIFF,
                ProviderCapability.CLONE_REPOSITORY,
            })
        )

    def fetch_repository(self, request: FetchRepositoryRequest) -> RepositoryInfo:
        # ... call GitHub API ...
        return RepositoryInfo(
            repo_full_name=request.repo_full_name,
            default_branch=repo.default_branch,
            clone_url=repo.clone_url,
        )

    # implement remaining methods ...
```

### Step 2 — write a factory function

```python
def build_github_git_adapter(settings: dict[str, str]) -> GitHubGitAdapter:
    return GitHubGitAdapter(settings)
```

### Step 3 — register the factory

At application startup, register the factory with `requires` declaring all mandatory settings:

```python
registry.register_factory(
    "github",
    build_github_git_adapter,
    requires={"token"},
)
```

### Step 4 — add a configuration entry

In `integrations.yaml` (or `autodev.yaml` under `integrations:`):

```yaml
git:
  provider: github
  settings:
    token: "${GITHUB_TOKEN}"
```

---

## Testing conventions

### Unit test: stub adapter

Test the integration Protocol contract in isolation with an in-memory stub.

```python
class _StubGitAdapter:
    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(provider_id="stub", display_name="Stub")

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(operations=frozenset({
            ProviderCapability.CREATE_PULL_REQUEST,
            # ...
        }))

    def create_pull_request(self, request: CreatePullRequestRequest) -> PullRequestInfo:
        return PullRequestInfo(
            repo_full_name=request.repo_full_name,
            pr_number=1,
            title=request.title,
            url="https://example.com/pull/1",
            head_branch=request.head_branch,
            base_branch=request.base_branch,
        )
    # ...

def test_stub_satisfies_protocol():
    assert isinstance(_StubGitAdapter(), GitProvider)
```

### Unit test: registry + factory

Test that the registry correctly wires config to your factory:

```python
def test_registry_loads_my_adapter(tmp_path):
    registry = IntegrationRegistry()
    registry.register_factory("myprovider", MyProviderFactory, requires={"api_key"})

    cfg = IntegrationsConfig(
        git=ProviderConfig(provider="myprovider", settings={"api_key": "test"})
    )
    registry.load(cfg)

    provider = registry.resolve(ProviderCapability.FETCH_REPOSITORY)
    assert isinstance(provider, MyProvider)
```

### Integration test (optional)

For live API tests, gate them behind an environment-variable check and mark them so they are skipped in CI:

```python
@pytest.mark.skipif(
    not os.getenv("GITHUB_TOKEN"), reason="GITHUB_TOKEN not set"
)
def test_github_adapter_live():
    adapter = GitHubGitAdapter({"token": os.environ["GITHUB_TOKEN"]})
    result = adapter.fetch_repository(FetchRepositoryRequest(repo_full_name="octocat/Hello-World"))
    assert result.default_branch
```

---

## Capability ownership

Each integration type owns a fixed set of `ProviderCapability` values.  Runtime code uses `registry.resolve(capability)` to get the right provider without knowing which type it belongs to.

| Integration type | Owned capabilities |
|---|---|
| `git` | `FETCH_REPOSITORY`, `CREATE_BRANCH`, `CREATE_PULL_REQUEST`, `GET_DIFF`, `CLONE_REPOSITORY` |
| `issue_tracker` | `FETCH_ISSUE`, `CREATE_ISSUE`, `UPDATE_ISSUE`, `LIST_ISSUES` |
| `ci` | `FETCH_RUN`, `TRIGGER_RUN`, `LIST_RUNS` |
| `monitoring` | `FETCH_ALERTS`, `QUERY_METRICS` |
| `messaging` | `SEND_MESSAGE`, `FETCH_MESSAGES` |
| `docs` | `FETCH_DOCUMENT`, `UPDATE_DOCUMENT`, `SEARCH_DOCUMENTS` |
