"""Git provider interface: fetch, branch, diff, clone, pull request."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import Field

from autodev.core.schemas import AutoDevModel
from autodev.integrations.base import CapabilitySet, ProviderInfo

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class FetchRepositoryRequest(AutoDevModel):
    """Identify a repository to fetch metadata about."""

    repo_full_name: str
    ref: str = "HEAD"


class CreateBranchRequest(AutoDevModel):
    """Create a new branch from a given source ref."""

    repo_full_name: str
    branch_name: str
    source_ref: str = "HEAD"


class CreatePullRequestRequest(AutoDevModel):
    """Open a pull request on a Git provider."""

    repo_full_name: str
    head_branch: str
    base_branch: str = "main"
    title: str
    body: str = ""
    draft: bool = False
    issue_refs: list[str] = Field(
        default_factory=list,
        description=(
            "Issue references to link (e.g. 'owner/repo#42', '#42', 'PROJ-123'). "
            "Adapters format these using provider-native closing-keyword syntax."
        ),
    )


class GetDiffRequest(AutoDevModel):
    """Request the diff between two refs."""

    repo_full_name: str
    base_ref: str
    head_ref: str
    path_filter: str = ""


class CloneRepositoryRequest(AutoDevModel):
    """Clone a repository to a local path."""

    repo_full_name: str
    dest_path: str
    ref: str = ""


# ---------------------------------------------------------------------------
# Response / info models
# ---------------------------------------------------------------------------


class RepositoryInfo(AutoDevModel):
    """Minimal metadata about a remote repository."""

    repo_full_name: str
    default_branch: str = "main"
    clone_url: str = ""
    description: str = ""
    is_private: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)


class BranchInfo(AutoDevModel):
    """Branch creation or lookup result."""

    repo_full_name: str
    branch_name: str
    sha: str = ""
    created: bool = True


class PullRequestInfo(AutoDevModel):
    """Result of opening a pull request."""

    repo_full_name: str
    pr_number: int
    title: str
    url: str
    head_branch: str
    base_branch: str
    draft: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)


class DiffResult(AutoDevModel):
    """Diff between two refs."""

    repo_full_name: str
    base_ref: str
    head_ref: str
    diff_text: str = ""
    changed_files: list[str] = Field(default_factory=list)
    additions: int = 0
    deletions: int = 0


class CloneResult(AutoDevModel):
    """Result of cloning a repository."""

    repo_full_name: str
    dest_path: str
    ref: str = ""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class GitProvider(Protocol):
    """Structural interface for Git-hosting providers (GitHub, GitLab, Gitea…)."""

    def provider_info(self) -> ProviderInfo: ...
    def capabilities(self) -> CapabilitySet: ...

    def fetch_repository(self, request: FetchRepositoryRequest) -> RepositoryInfo: ...
    def create_branch(self, request: CreateBranchRequest) -> BranchInfo: ...
    def create_pull_request(self, request: CreatePullRequestRequest) -> PullRequestInfo: ...
    def get_diff(self, request: GetDiffRequest) -> DiffResult: ...
    def clone_repository(self, request: CloneRepositoryRequest) -> CloneResult: ...
