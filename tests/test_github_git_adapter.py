"""Tests for GitHubGitAdapter: Protocol compliance, operation mapping, and registry wiring."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from autodev.github.adapters.git_platform import (
    GitHubGitAdapter,
    REQUIRED_SETTINGS,
    _format_pr_body,
    build_github_git_adapter,
)
from autodev.integrations import (
    CapabilitySet,
    IntegrationRegistry,
    IntegrationsConfig,
    ProviderCapability,
    ProviderConfig,
)
from autodev.integrations.git_provider import (
    BranchInfo,
    CloneRepositoryRequest,
    CreateBranchRequest,
    CreatePullRequestRequest,
    DiffResult,
    FetchRepositoryRequest,
    GetDiffRequest,
    GitProvider,
    PullRequestInfo,
    RepositoryInfo,
)


# ---------------------------------------------------------------------------
# Helpers — mock PyGithub objects
# ---------------------------------------------------------------------------


def _make_mock_repo(
    *,
    default_branch: str = "main",
    clone_url: str = "https://github.com/owner/repo.git",
    description: str = "A test repo",
    private: bool = False,
) -> MagicMock:
    repo = MagicMock()
    repo.default_branch = default_branch
    repo.clone_url = clone_url
    repo.description = description
    repo.private = private
    return repo


def _make_adapter(token: str = "test-token") -> tuple[GitHubGitAdapter, MagicMock]:
    """Return (adapter, mock_gh_client) with _gh_client pre-patched."""
    adapter = GitHubGitAdapter({"token": token})
    mock_gh = MagicMock()
    adapter._gh_client = lambda: mock_gh  # type: ignore[method-assign]
    return adapter, mock_gh


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    def test_satisfies_git_provider_protocol(self):
        adapter = GitHubGitAdapter({"token": "t"})
        assert isinstance(adapter, GitProvider)

    def test_provider_info_returns_github(self):
        adapter = GitHubGitAdapter({"token": "t"})
        info = adapter.provider_info()
        assert info.provider_id == "github"
        assert info.display_name == "GitHub"

    def test_default_base_url(self):
        adapter = GitHubGitAdapter({"token": "t"})
        assert adapter.provider_info().base_url == "https://api.github.com"

    def test_custom_base_url(self):
        adapter = GitHubGitAdapter(
            {"token": "t", "base_url": "https://github.example.com"}
        )
        assert adapter.provider_info().base_url == "https://github.example.com"

    def test_capabilities_covers_all_git_operations(self):
        adapter = GitHubGitAdapter({"token": "t"})
        caps = adapter.capabilities()
        for op in (
            ProviderCapability.FETCH_REPOSITORY,
            ProviderCapability.CREATE_BRANCH,
            ProviderCapability.CREATE_PULL_REQUEST,
            ProviderCapability.GET_DIFF,
            ProviderCapability.CLONE_REPOSITORY,
        ):
            assert caps.supports(op), f"Expected {op.value} to be supported"

    def test_capabilities_excludes_non_git_operations(self):
        adapter = GitHubGitAdapter({"token": "t"})
        caps = adapter.capabilities()
        assert not caps.supports(ProviderCapability.FETCH_ISSUE)
        assert not caps.supports(ProviderCapability.TRIGGER_RUN)
        assert not caps.supports(ProviderCapability.SEND_MESSAGE)


# ---------------------------------------------------------------------------
# fetch_repository
# ---------------------------------------------------------------------------


class TestFetchRepository:
    def test_returns_repository_info(self):
        adapter, mock_gh = _make_adapter()
        mock_repo = _make_mock_repo(
            default_branch="develop",
            clone_url="https://github.com/owner/repo.git",
            description="My repo",
            private=True,
        )
        mock_gh.get_repo.return_value = mock_repo

        result = adapter.fetch_repository(FetchRepositoryRequest(repo_full_name="owner/repo"))

        assert isinstance(result, RepositoryInfo)
        assert result.repo_full_name == "owner/repo"
        assert result.default_branch == "develop"
        assert result.clone_url == "https://github.com/owner/repo.git"
        assert result.description == "My repo"
        assert result.is_private is True

    def test_calls_get_repo_with_full_name(self):
        adapter, mock_gh = _make_adapter()
        mock_gh.get_repo.return_value = _make_mock_repo()

        adapter.fetch_repository(FetchRepositoryRequest(repo_full_name="acme/widgets"))

        mock_gh.get_repo.assert_called_once_with("acme/widgets")

    def test_none_description_becomes_empty_string(self):
        adapter, mock_gh = _make_adapter()
        mock_repo = _make_mock_repo()
        mock_repo.description = None
        mock_gh.get_repo.return_value = mock_repo

        result = adapter.fetch_repository(FetchRepositoryRequest(repo_full_name="owner/repo"))

        assert result.description == ""


# ---------------------------------------------------------------------------
# create_branch
# ---------------------------------------------------------------------------


class TestCreateBranch:
    def test_returns_branch_info(self):
        adapter, mock_gh = _make_adapter()
        mock_repo = _make_mock_repo()
        mock_repo.get_commit.return_value.sha = "abc123def456"
        mock_gh.get_repo.return_value = mock_repo

        result = adapter.create_branch(
            CreateBranchRequest(repo_full_name="owner/repo", branch_name="feature/x")
        )

        assert isinstance(result, BranchInfo)
        assert result.branch_name == "feature/x"
        assert result.sha == "abc123def456"
        assert result.created is True

    def test_creates_git_ref_with_heads_prefix(self):
        adapter, mock_gh = _make_adapter()
        mock_repo = _make_mock_repo()
        mock_repo.get_commit.return_value.sha = "deadbeef"
        mock_gh.get_repo.return_value = mock_repo

        adapter.create_branch(
            CreateBranchRequest(
                repo_full_name="owner/repo",
                branch_name="feature/my-feature",
                source_ref="main",
            )
        )

        mock_repo.create_git_ref.assert_called_once_with(
            ref="refs/heads/feature/my-feature",
            sha="deadbeef",
        )

    def test_falls_back_to_branch_sha_when_commit_lookup_fails(self):
        adapter, mock_gh = _make_adapter()
        mock_repo = _make_mock_repo()
        mock_repo.get_commit.side_effect = Exception("not a commit")
        mock_repo.get_branch.return_value.commit.sha = "fallback-sha"
        mock_gh.get_repo.return_value = mock_repo

        result = adapter.create_branch(
            CreateBranchRequest(repo_full_name="owner/repo", branch_name="feature/x")
        )

        assert result.sha == "fallback-sha"

    def test_treats_literal_sha_as_last_resort(self):
        adapter, mock_gh = _make_adapter()
        mock_repo = _make_mock_repo()
        mock_repo.get_commit.side_effect = Exception("no")
        mock_repo.get_branch.side_effect = Exception("no")
        mock_gh.get_repo.return_value = mock_repo

        result = adapter.create_branch(
            CreateBranchRequest(
                repo_full_name="owner/repo",
                branch_name="feature/x",
                source_ref="abc123",
            )
        )

        assert result.sha == "abc123"


# ---------------------------------------------------------------------------
# create_pull_request
# ---------------------------------------------------------------------------


class TestCreatePullRequest:
    def _pr_mock(self, number: int = 7, url: str = "https://github.com/o/r/pull/7") -> MagicMock:
        pr = MagicMock()
        pr.number = number
        pr.html_url = url
        pr.title = "My PR"
        return pr

    def test_returns_pull_request_info(self):
        adapter, mock_gh = _make_adapter()
        mock_repo = _make_mock_repo()
        mock_repo.create_pull.return_value = self._pr_mock()
        mock_gh.get_repo.return_value = mock_repo

        result = adapter.create_pull_request(
            CreatePullRequestRequest(
                repo_full_name="owner/repo",
                head_branch="feature/x",
                title="My PR",
            )
        )

        assert isinstance(result, PullRequestInfo)
        assert result.pr_number == 7
        assert result.url == "https://github.com/o/r/pull/7"

    def test_passes_head_base_title_body_to_github(self):
        adapter, mock_gh = _make_adapter()
        mock_repo = _make_mock_repo()
        mock_repo.create_pull.return_value = self._pr_mock()
        mock_gh.get_repo.return_value = mock_repo

        adapter.create_pull_request(
            CreatePullRequestRequest(
                repo_full_name="owner/repo",
                head_branch="feature/x",
                base_branch="develop",
                title="Add feature",
                body="Long description.",
            )
        )

        call_kwargs = mock_repo.create_pull.call_args.kwargs
        assert call_kwargs["head"] == "feature/x"
        assert call_kwargs["base"] == "develop"
        assert call_kwargs["title"] == "Add feature"
        assert "Long description." in call_kwargs["body"]

    def test_issue_refs_appended_as_closing_keywords(self):
        adapter, mock_gh = _make_adapter()
        mock_repo = _make_mock_repo()
        mock_repo.create_pull.return_value = self._pr_mock()
        mock_gh.get_repo.return_value = mock_repo

        adapter.create_pull_request(
            CreatePullRequestRequest(
                repo_full_name="owner/repo",
                head_branch="feature/x",
                title="Fix issue",
                issue_refs=["#42", "owner/other-repo#7"],
            )
        )

        body_sent = mock_repo.create_pull.call_args.kwargs["body"]
        assert "Closes #42" in body_sent
        assert "Closes owner/other-repo#7" in body_sent

    def test_draft_flag_forwarded(self):
        adapter, mock_gh = _make_adapter()
        mock_repo = _make_mock_repo()
        mock_repo.create_pull.return_value = self._pr_mock()
        mock_gh.get_repo.return_value = mock_repo

        adapter.create_pull_request(
            CreatePullRequestRequest(
                repo_full_name="owner/repo",
                head_branch="feature/x",
                title="Draft PR",
                draft=True,
            )
        )

        assert mock_repo.create_pull.call_args.kwargs["draft"] is True

    def test_result_preserves_branch_names(self):
        adapter, mock_gh = _make_adapter()
        mock_repo = _make_mock_repo()
        mock_repo.create_pull.return_value = self._pr_mock()
        mock_gh.get_repo.return_value = mock_repo

        result = adapter.create_pull_request(
            CreatePullRequestRequest(
                repo_full_name="owner/repo",
                head_branch="feature/x",
                base_branch="develop",
                title="My PR",
            )
        )

        assert result.head_branch == "feature/x"
        assert result.base_branch == "develop"


# ---------------------------------------------------------------------------
# get_diff
# ---------------------------------------------------------------------------


class TestGetDiff:
    def _comparison_mock(
        self,
        files: list[str],
        additions: int = 10,
        deletions: int = 3,
    ) -> MagicMock:
        comparison = MagicMock()
        comparison.diff_url = ""  # suppress network call in _fetch_diff_text
        comparison.total_additions = additions
        comparison.total_deletions = deletions
        file_mocks = []
        for fname in files:
            f = MagicMock()
            f.filename = fname
            file_mocks.append(f)
        comparison.files = file_mocks
        return comparison

    def test_returns_diff_result(self):
        adapter, mock_gh = _make_adapter()
        mock_repo = _make_mock_repo()
        mock_repo.compare.return_value = self._comparison_mock(
            ["src/foo.py", "tests/test_foo.py"], additions=20, deletions=5
        )
        mock_gh.get_repo.return_value = mock_repo

        result = adapter.get_diff(
            GetDiffRequest(
                repo_full_name="owner/repo", base_ref="main", head_ref="feature/x"
            )
        )

        assert isinstance(result, DiffResult)
        assert "src/foo.py" in result.changed_files
        assert "tests/test_foo.py" in result.changed_files
        assert result.additions == 20
        assert result.deletions == 5

    def test_calls_compare_with_correct_refs(self):
        adapter, mock_gh = _make_adapter()
        mock_repo = _make_mock_repo()
        mock_repo.compare.return_value = self._comparison_mock([])
        mock_gh.get_repo.return_value = mock_repo

        adapter.get_diff(
            GetDiffRequest(
                repo_full_name="owner/repo", base_ref="v1.0", head_ref="v2.0"
            )
        )

        mock_repo.compare.assert_called_once_with("v1.0", "v2.0")

    def test_path_filter_limits_changed_files(self):
        adapter, mock_gh = _make_adapter()
        mock_repo = _make_mock_repo()
        mock_repo.compare.return_value = self._comparison_mock(
            ["src/foo.py", "tests/test_foo.py", "docs/readme.md"]
        )
        mock_gh.get_repo.return_value = mock_repo

        result = adapter.get_diff(
            GetDiffRequest(
                repo_full_name="owner/repo",
                base_ref="main",
                head_ref="feature/x",
                path_filter="src/",
            )
        )

        assert result.changed_files == ["src/foo.py"]

    def test_empty_diff_url_leaves_diff_text_empty(self):
        adapter, mock_gh = _make_adapter()
        mock_repo = _make_mock_repo()
        comparison = self._comparison_mock([])
        comparison.diff_url = ""
        mock_repo.compare.return_value = comparison
        mock_gh.get_repo.return_value = mock_repo

        result = adapter.get_diff(
            GetDiffRequest(
                repo_full_name="owner/repo", base_ref="main", head_ref="feature/x"
            )
        )

        assert result.diff_text == ""


# ---------------------------------------------------------------------------
# clone_repository
# ---------------------------------------------------------------------------


class TestCloneRepository:
    def test_returns_clone_result(self, monkeypatch):
        adapter, _ = _make_adapter()
        monkeypatch.setattr(adapter._git_tool, "clone", lambda url, dest: dest)

        result = adapter.clone_repository(
            CloneRepositoryRequest(repo_full_name="owner/repo", dest_path="/tmp/repo")
        )

        assert result.repo_full_name == "owner/repo"
        assert result.dest_path == "/tmp/repo"

    def test_includes_token_in_url(self, monkeypatch):
        adapter, _ = _make_adapter(token="ghp_secret")
        urls: list[str] = []
        monkeypatch.setattr(adapter._git_tool, "clone", lambda url, dest: urls.append(url))

        adapter.clone_repository(
            CloneRepositoryRequest(repo_full_name="owner/repo", dest_path="/tmp/repo")
        )

        assert len(urls) == 1
        assert "ghp_secret@github.com" in urls[0]

    def test_no_token_uses_anonymous_url(self, monkeypatch):
        adapter = GitHubGitAdapter({"token": ""})
        urls: list[str] = []
        monkeypatch.setattr(adapter._git_tool, "clone", lambda url, dest: urls.append(url))

        adapter.clone_repository(
            CloneRepositoryRequest(repo_full_name="owner/repo", dest_path="/tmp/repo")
        )

        assert "https://github.com/owner/repo.git" in urls[0]
        assert "@" not in urls[0]

    def test_ref_preserved_in_result(self, monkeypatch):
        adapter, _ = _make_adapter()
        monkeypatch.setattr(adapter._git_tool, "clone", lambda url, dest: dest)

        result = adapter.clone_repository(
            CloneRepositoryRequest(
                repo_full_name="owner/repo", dest_path="/tmp/repo", ref="v1.2.3"
            )
        )

        assert result.ref == "v1.2.3"


# ---------------------------------------------------------------------------
# _format_pr_body
# ---------------------------------------------------------------------------


class TestFormatPrBody:
    def test_no_refs_returns_body_unchanged(self):
        assert _format_pr_body("My description.", []) == "My description."

    def test_empty_body_no_refs_returns_empty(self):
        assert _format_pr_body("", []) == ""

    def test_single_ref_appended(self):
        result = _format_pr_body("Fix the bug.", ["#42"])
        assert "Closes #42" in result
        assert "Fix the bug." in result

    def test_multiple_refs_all_appended(self):
        result = _format_pr_body("", ["#1", "#2", "owner/other#3"])
        assert "Closes #1" in result
        assert "Closes #2" in result
        assert "Closes owner/other#3" in result

    def test_empty_body_with_refs(self):
        result = _format_pr_body("", ["#42"])
        assert result == "Closes #42"

    def test_body_and_refs_separated_by_blank_line(self):
        result = _format_pr_body("Description.", ["#5"])
        assert "\n\nCloses #5" in result

    def test_closing_lines_one_per_ref(self):
        result = _format_pr_body("", ["#1", "#2"])
        lines = result.strip().splitlines()
        assert lines == ["Closes #1", "Closes #2"]


# ---------------------------------------------------------------------------
# Factory and required settings
# ---------------------------------------------------------------------------


class TestFactory:
    def test_build_returns_adapter_instance(self):
        adapter = build_github_git_adapter({"token": "my-token"})
        assert isinstance(adapter, GitHubGitAdapter)

    def test_settings_passed_through(self):
        adapter = build_github_git_adapter(
            {"token": "tok", "base_url": "https://ghe.example.com"}
        )
        assert adapter._token == "tok"
        assert adapter._base_url == "https://ghe.example.com"

    def test_required_settings_declares_token(self):
        assert "token" in REQUIRED_SETTINGS


# ---------------------------------------------------------------------------
# IntegrationRegistry wiring
# ---------------------------------------------------------------------------


class TestRegistryIntegration:
    def test_registry_loads_github_adapter(self):
        registry = IntegrationRegistry()
        registry.register_factory(
            "github", build_github_git_adapter, requires=REQUIRED_SETTINGS
        )
        registry.load(
            IntegrationsConfig(
                git=ProviderConfig(provider="github", settings={"token": "t"})
            )
        )
        provider = registry.resolve(ProviderCapability.CREATE_PULL_REQUEST)
        assert isinstance(provider, GitHubGitAdapter)

    def test_registry_missing_token_raises_config_error(self):
        from autodev.core.config import ConfigError

        registry = IntegrationRegistry()
        registry.register_factory(
            "github", build_github_git_adapter, requires=REQUIRED_SETTINGS
        )
        with pytest.raises(ConfigError, match="token"):
            registry.load(
                IntegrationsConfig(
                    git=ProviderConfig(provider="github", settings={})
                )
            )

    def test_supports_all_git_capabilities_after_load(self):
        registry = IntegrationRegistry()
        registry.register_factory(
            "github", build_github_git_adapter, requires=REQUIRED_SETTINGS
        )
        registry.load(
            IntegrationsConfig(
                git=ProviderConfig(provider="github", settings={"token": "t"})
            )
        )
        for cap in (
            ProviderCapability.FETCH_REPOSITORY,
            ProviderCapability.CREATE_BRANCH,
            ProviderCapability.CREATE_PULL_REQUEST,
            ProviderCapability.GET_DIFF,
            ProviderCapability.CLONE_REPOSITORY,
        ):
            assert registry.supports(cap), f"Expected registry to support {cap.value}"
