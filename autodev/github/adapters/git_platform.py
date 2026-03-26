"""GitHub implementation of the GitProvider interface.

``GitHubGitAdapter`` wraps the existing GitHub helpers (``PRCreator``,
``RepoCloner``) and supplements them with direct PyGithub calls for
repository metadata, branch creation, and diff retrieval.

Extension points for other providers
-------------------------------------
GitLab and Bitbucket adapters follow the same four-step pattern:

1. Create a module (e.g. ``autodev/gitlab/adapters/git_platform.py``).
2. Implement all five ``GitProvider`` methods against the provider's API.
3. Write a ``build_*_adapter(settings)`` factory.
4. Register the factory in ``IntegrationRegistry``:

   .. code-block:: python

       registry.register_factory(
           "gitlab",
           build_gitlab_git_adapter,
           requires={"token", "base_url"},
       )

Issue-linking conventions
--------------------------
GitHub uses ``Closes owner/repo#N`` or ``Closes #N`` keywords in the PR
body.  The private ``_format_pr_body()`` helper appends these lines so
that the issue is automatically closed when the PR is merged.

GitLab uses the same ``Closes`` keyword; Bitbucket uses ``Resolves`` or
``Fixes``.  Override ``_format_pr_body`` in a subclass, or implement a
separate adapter module, to change this behaviour.
"""

from __future__ import annotations

import logging

from autodev.integrations.base import CapabilitySet, ProviderCapability, ProviderInfo
from autodev.integrations.git_provider import (
    BranchInfo,
    CloneRepositoryRequest,
    CloneResult,
    CreateBranchRequest,
    CreatePullRequestRequest,
    DiffResult,
    FetchRepositoryRequest,
    GetDiffRequest,
    PullRequestInfo,
    RepositoryInfo,
)
from autodev.tools.git_tool import GitTool

logger = logging.getLogger(__name__)

# Capabilities exposed by every GitHubGitAdapter instance.
_GITHUB_CAPABILITIES = frozenset(
    {
        ProviderCapability.FETCH_REPOSITORY,
        ProviderCapability.CREATE_BRANCH,
        ProviderCapability.CREATE_PULL_REQUEST,
        ProviderCapability.GET_DIFF,
        ProviderCapability.CLONE_REPOSITORY,
    }
)


def _format_pr_body(body: str, issue_refs: list[str]) -> str:
    """Append GitHub closing-keyword lines for each issue reference.

    GitHub auto-closes the referenced issue when the PR is merged if
    the PR body contains ``Closes <ref>``.

    Args:
        body: The human-written PR description (may be empty).
        issue_refs: References such as ``"#42"``, ``"owner/repo#42"``.

    Returns:
        The body with closing-keyword lines appended (if any refs given).
    """
    if not issue_refs:
        return body
    closing = "\n".join(f"Closes {ref}" for ref in issue_refs)
    return f"{body}\n\n{closing}" if body else closing


class GitHubGitAdapter:
    """GitHub implementation of the ``GitProvider`` Protocol.

    Constructed from a settings dict by ``build_github_git_adapter()``,
    which is compatible with ``IntegrationRegistry.register_factory()``.

    Settings
    --------
    token (required)
        A GitHub personal access token or fine-grained token with
        ``repo`` and ``pull_request`` scopes.
    base_url (optional)
        GitHub Enterprise base URL (e.g. ``https://github.example.com``).
        Defaults to ``"https://api.github.com"``.
    """

    def __init__(self, settings: dict[str, str]) -> None:
        self._token = settings.get("token", "")
        self._base_url = settings.get("base_url", "https://api.github.com")
        self._git_tool = GitTool()

    # ------------------------------------------------------------------
    # IntegrationProvider contract
    # ------------------------------------------------------------------

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            provider_id="github",
            display_name="GitHub",
            base_url=self._base_url,
            capabilities=self.capabilities(),
        )

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(operations=_GITHUB_CAPABILITIES)

    # ------------------------------------------------------------------
    # GitProvider contract
    # ------------------------------------------------------------------

    def fetch_repository(self, request: FetchRepositoryRequest) -> RepositoryInfo:
        """Return metadata for a GitHub repository.

        Uses the GitHub API; requires a valid token and repository access.
        """
        gh = self._gh_client()
        repo = gh.get_repo(request.repo_full_name)
        return RepositoryInfo(
            repo_full_name=request.repo_full_name,
            default_branch=repo.default_branch or "main",
            clone_url=repo.clone_url or "",
            description=repo.description or "",
            is_private=bool(repo.private),
        )

    def create_branch(self, request: CreateBranchRequest) -> BranchInfo:
        """Create a remote branch via the GitHub API.

        Resolves ``source_ref`` to a commit SHA and creates a new ref
        at that SHA, so no local clone is required.
        """
        gh = self._gh_client()
        repo = gh.get_repo(request.repo_full_name)
        source_sha = self._resolve_sha(repo, request.source_ref)
        repo.create_git_ref(
            ref=f"refs/heads/{request.branch_name}",
            sha=source_sha,
        )
        logger.info(
            "Created branch %r in %s at %s",
            request.branch_name,
            request.repo_full_name,
            source_sha[:7],
        )
        return BranchInfo(
            repo_full_name=request.repo_full_name,
            branch_name=request.branch_name,
            sha=source_sha,
            created=True,
        )

    def create_pull_request(
        self, request: CreatePullRequestRequest
    ) -> PullRequestInfo:
        """Open a pull request on GitHub, optionally linking issues.

        Issue references in ``request.issue_refs`` are appended to the PR
        body as ``Closes <ref>`` lines so GitHub auto-closes them on merge.
        """
        body = _format_pr_body(request.body, request.issue_refs)
        gh = self._gh_client()
        repo = gh.get_repo(request.repo_full_name)
        pr = repo.create_pull(
            title=request.title,
            body=body,
            head=request.head_branch,
            base=request.base_branch,
            draft=request.draft,
        )
        logger.info("Opened PR #%d: %s", pr.number, pr.html_url)
        return PullRequestInfo(
            repo_full_name=request.repo_full_name,
            pr_number=pr.number,
            title=pr.title,
            url=pr.html_url,
            head_branch=request.head_branch,
            base_branch=request.base_branch,
            draft=request.draft,
        )

    def get_diff(self, request: GetDiffRequest) -> DiffResult:
        """Compare two refs via the GitHub API.

        Returns the list of changed files and addition/deletion counts.
        ``diff_text`` is populated only when the comparison is small enough
        for GitHub to return it in a single response.
        """
        gh = self._gh_client()
        repo = gh.get_repo(request.repo_full_name)
        comparison = repo.compare(request.base_ref, request.head_ref)
        files = list(comparison.files)
        if request.path_filter:
            files = [f for f in files if request.path_filter in f.filename]
        changed_files = [f.filename for f in files]
        # Attempt to retrieve the actual diff text via the GitHub API URL.
        diff_text = self._fetch_diff_text(comparison)
        return DiffResult(
            repo_full_name=request.repo_full_name,
            base_ref=request.base_ref,
            head_ref=request.head_ref,
            diff_text=diff_text,
            changed_files=changed_files,
            additions=comparison.total_additions,
            deletions=comparison.total_deletions,
        )

    def clone_repository(self, request: CloneRepositoryRequest) -> CloneResult:
        """Clone a GitHub repository using token authentication when available."""
        if self._token:
            url = f"https://{self._token}@github.com/{request.repo_full_name}.git"
        else:
            url = f"https://github.com/{request.repo_full_name}.git"
        self._git_tool.clone(url, request.dest_path)
        logger.info("Cloned %s → %s", request.repo_full_name, request.dest_path)
        return CloneResult(
            repo_full_name=request.repo_full_name,
            dest_path=request.dest_path,
            ref=request.ref,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _gh_client(self):  # type: ignore[return]
        """Return a PyGithub ``Github`` instance."""
        from github import Github  # PyGithub — imported lazily to allow testing

        if self._base_url and self._base_url != "https://api.github.com":
            # GitHub Enterprise: PyGithub accepts base_url as a kwarg
            return Github(self._token, base_url=self._base_url)
        return Github(self._token)

    @staticmethod
    def _resolve_sha(repo: object, ref: str) -> str:  # type: ignore[return]
        """Resolve a branch name, tag, or commit SHA to a bare SHA string."""
        try:
            return repo.get_commit(ref).sha  # type: ignore[union-attr]
        except Exception:
            pass
        try:
            return repo.get_branch(ref).commit.sha  # type: ignore[union-attr]
        except Exception:
            pass
        # Treat as a literal SHA
        return ref

    @staticmethod
    def _fetch_diff_text(comparison: object) -> str:
        """Attempt to retrieve the raw unified diff text from GitHub.

        Returns an empty string if the diff URL is unavailable or the
        request fails (e.g. comparison too large or network error).
        """
        import urllib.error
        import urllib.request

        diff_url = getattr(comparison, "diff_url", "")
        if not diff_url:
            return ""
        try:
            req = urllib.request.Request(diff_url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError):
            return ""


# ---------------------------------------------------------------------------
# Factory — compatible with IntegrationRegistry.register_factory()
# ---------------------------------------------------------------------------

#: Settings keys required by this factory.
REQUIRED_SETTINGS: frozenset[str] = frozenset({"token"})


def build_github_git_adapter(settings: dict[str, str]) -> GitHubGitAdapter:
    """Construct a :class:`GitHubGitAdapter` from a settings dict.

    Intended for use with :meth:`IntegrationRegistry.register_factory`::

        registry.register_factory(
            "github",
            build_github_git_adapter,
            requires=REQUIRED_SETTINGS,
        )
    """
    return GitHubGitAdapter(settings)
