"""Issue tracker interface: fetch, create, update, list issues."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import Field

from autodev.core.schemas import AutoDevModel
from autodev.integrations.base import CapabilitySet, ProviderInfo


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class FetchIssueRequest(AutoDevModel):
    """Fetch a single issue by identifier."""

    project_id: str
    issue_id: str


class CreateIssueRequest(AutoDevModel):
    """Create a new issue."""

    project_id: str
    title: str
    body: str = ""
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)
    priority: str = ""


class UpdateIssueRequest(AutoDevModel):
    """Partial update to an existing issue."""

    project_id: str
    issue_id: str
    title: str = ""
    body: str = ""
    labels: list[str] = Field(default_factory=list)
    status: str = ""
    assignees: list[str] = Field(default_factory=list)


class ListIssuesRequest(AutoDevModel):
    """Query open or filtered issues from a project."""

    project_id: str
    status: str = "open"
    labels: list[str] = Field(default_factory=list)
    assignee: str = ""
    limit: int = 50


# ---------------------------------------------------------------------------
# Response / info models
# ---------------------------------------------------------------------------


class IssueComment(AutoDevModel):
    """A single comment on an issue."""

    comment_id: str
    author: str
    body: str
    created_at: str = ""


class IssueInfo(AutoDevModel):
    """Normalized representation of an issue across trackers."""

    project_id: str
    issue_id: str
    title: str
    body: str = ""
    status: str = "open"
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)
    url: str = ""
    priority: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class IssueTracker(Protocol):
    """Structural interface for issue-tracking systems (GitHub Issues, Linear, Jira…)."""

    def provider_info(self) -> ProviderInfo: ...
    def capabilities(self) -> CapabilitySet: ...

    def fetch_issue(self, request: FetchIssueRequest) -> IssueInfo: ...
    def create_issue(self, request: CreateIssueRequest) -> IssueInfo: ...
    def update_issue(self, request: UpdateIssueRequest) -> IssueInfo: ...
    def list_issues(self, request: ListIssuesRequest) -> list[IssueInfo]: ...
