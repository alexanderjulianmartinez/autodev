"""CI/CD system interface: fetch runs, trigger runs, list runs."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import Field

from autodev.core.schemas import AutoDevModel
from autodev.integrations.base import CapabilitySet, ProviderInfo


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class FetchRunRequest(AutoDevModel):
    """Fetch a specific CI run by identifier."""

    project_id: str
    run_id: str
    include_logs: bool = False


class TriggerRunRequest(AutoDevModel):
    """Trigger a new CI run."""

    project_id: str
    workflow_id: str
    ref: str = "main"
    inputs: dict[str, str] = Field(default_factory=dict)


class ListRunsRequest(AutoDevModel):
    """List recent CI runs, optionally filtered."""

    project_id: str
    branch: str = ""
    status: str = ""
    limit: int = 20


# ---------------------------------------------------------------------------
# Response / info models
# ---------------------------------------------------------------------------


class CIStepInfo(AutoDevModel):
    """One step within a CI job."""

    name: str
    status: str
    conclusion: str = ""
    duration_seconds: float = 0.0
    log_url: str = ""


class CIJobInfo(AutoDevModel):
    """One job within a CI run."""

    job_id: str
    name: str
    status: str
    conclusion: str = ""
    steps: list[CIStepInfo] = Field(default_factory=list)
    runner: str = ""
    duration_seconds: float = 0.0


class CIRunInfo(AutoDevModel):
    """Normalized representation of a CI run."""

    project_id: str
    run_id: str
    workflow_name: str
    branch: str
    status: str
    conclusion: str = ""
    url: str = ""
    jobs: list[CIJobInfo] = Field(default_factory=list)
    inferred_validation_commands: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class CISystem(Protocol):
    """Structural interface for CI/CD systems (GitHub Actions, CircleCI, Jenkins…)."""

    def provider_info(self) -> ProviderInfo: ...
    def capabilities(self) -> CapabilitySet: ...

    def fetch_run(self, request: FetchRunRequest) -> CIRunInfo: ...
    def trigger_run(self, request: TriggerRunRequest) -> CIRunInfo: ...
    def list_runs(self, request: ListRunsRequest) -> list[CIRunInfo]: ...
