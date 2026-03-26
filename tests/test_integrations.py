"""Tests for autodev.integrations: base types, request/response models, and Protocol contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autodev.integrations import (
    AlertInfo,
    BranchInfo,
    CapabilitySet,
    CIJobInfo,
    CIRunInfo,
    CIStepInfo,
    CloneRepositoryRequest,
    CloneResult,
    CreateBranchRequest,
    CreateIssueRequest,
    CreatePullRequestRequest,
    DiffResult,
    DocumentInfo,
    DocumentSearchResult,
    FetchAlertsRequest,
    FetchDocumentRequest,
    FetchIssueRequest,
    FetchMessagesRequest,
    FetchRepositoryRequest,
    FetchRunRequest,
    GetDiffRequest,
    GitProvider,
    IntegrationProvider,
    IssueInfo,
    IssueTracker,
    ListIssuesRequest,
    ListRunsRequest,
    MessageInfo,
    MessageResult,
    MetricSeries,
    MetricsResult,
    ProviderCapability,
    ProviderInfo,
    PullRequestInfo,
    QueryMetricsRequest,
    RepositoryInfo,
    SearchDocumentsRequest,
    SendMessageRequest,
    TriggerRunRequest,
    UpdateDocumentRequest,
    UpdateIssueRequest,
)

# ---------------------------------------------------------------------------
# CapabilitySet
# ---------------------------------------------------------------------------


class TestCapabilitySet:
    def test_empty_supports_nothing(self):
        cs = CapabilitySet()
        assert not cs.supports(ProviderCapability.CREATE_PULL_REQUEST)

    def test_supports_operation_in_set(self):
        cs = CapabilitySet(
            operations=frozenset(
                {ProviderCapability.CREATE_PULL_REQUEST, ProviderCapability.FETCH_REPOSITORY}
            )
        )
        assert cs.supports(ProviderCapability.CREATE_PULL_REQUEST)
        assert cs.supports(ProviderCapability.FETCH_REPOSITORY)
        assert not cs.supports(ProviderCapability.TRIGGER_RUN)

    def test_require_raises_when_not_supported(self):
        cs = CapabilitySet()
        with pytest.raises(NotImplementedError, match="fetch_repository"):
            cs.require(ProviderCapability.FETCH_REPOSITORY)

    def test_require_passes_when_supported(self):
        cs = CapabilitySet(operations=frozenset({ProviderCapability.FETCH_REPOSITORY}))
        cs.require(ProviderCapability.FETCH_REPOSITORY)  # must not raise

    def test_require_error_message_names_operation(self):
        cs = CapabilitySet()
        with pytest.raises(NotImplementedError, match="create_pull_request"):
            cs.require(ProviderCapability.CREATE_PULL_REQUEST)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            CapabilitySet(operations=frozenset(), unknown_field="x")

    def test_metadata_is_optional(self):
        cs = CapabilitySet(metadata={"region": "us-east-1"})
        assert cs.metadata["region"] == "us-east-1"

    def test_all_capability_values_are_strings(self):
        for cap in ProviderCapability:
            assert isinstance(cap.value, str)


# ---------------------------------------------------------------------------
# ProviderInfo
# ---------------------------------------------------------------------------


class TestProviderInfo:
    def test_minimal(self):
        info = ProviderInfo(provider_id="github", display_name="GitHub")
        assert info.provider_id == "github"
        assert info.version == ""
        assert info.base_url == ""

    def test_with_capabilities(self):
        caps = CapabilitySet(operations=frozenset({ProviderCapability.FETCH_REPOSITORY}))
        info = ProviderInfo(provider_id="github", display_name="GitHub", capabilities=caps)
        assert info.capabilities.supports(ProviderCapability.FETCH_REPOSITORY)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ProviderInfo(provider_id="x", display_name="X", unknown="y")


# ---------------------------------------------------------------------------
# GitProvider models
# ---------------------------------------------------------------------------


class TestGitProviderModels:
    def test_fetch_repository_request_defaults(self):
        req = FetchRepositoryRequest(repo_full_name="owner/repo")
        assert req.ref == "HEAD"

    def test_create_branch_request(self):
        req = CreateBranchRequest(repo_full_name="owner/repo", branch_name="feature/x")
        assert req.source_ref == "HEAD"

    def test_create_pr_request_defaults(self):
        req = CreatePullRequestRequest(
            repo_full_name="owner/repo",
            head_branch="feature/x",
            title="Add feature X",
        )
        assert req.base_branch == "main"
        assert req.draft is False
        assert req.body == ""

    def test_get_diff_request(self):
        req = GetDiffRequest(repo_full_name="owner/repo", base_ref="main", head_ref="feature/x")
        assert req.path_filter == ""

    def test_clone_repository_request(self):
        req = CloneRepositoryRequest(repo_full_name="owner/repo", dest_path="/tmp/repo")
        assert req.ref == ""

    def test_repository_info_defaults(self):
        info = RepositoryInfo(repo_full_name="owner/repo")
        assert info.default_branch == "main"
        assert info.is_private is False

    def test_branch_info(self):
        info = BranchInfo(repo_full_name="owner/repo", branch_name="feature/x")
        assert info.created is True
        assert info.sha == ""

    def test_pull_request_info(self):
        pr = PullRequestInfo(
            repo_full_name="owner/repo",
            pr_number=42,
            title="Add feature X",
            url="https://github.com/owner/repo/pull/42",
            head_branch="feature/x",
            base_branch="main",
        )
        assert pr.pr_number == 42
        assert pr.draft is False

    def test_diff_result_defaults(self):
        diff = DiffResult(repo_full_name="owner/repo", base_ref="main", head_ref="feature/x")
        assert diff.changed_files == []
        assert diff.additions == 0
        assert diff.deletions == 0

    def test_clone_result(self):
        result = CloneResult(repo_full_name="owner/repo", dest_path="/tmp/repo")
        assert result.ref == ""


# ---------------------------------------------------------------------------
# IssueTracker models
# ---------------------------------------------------------------------------


class TestIssueTrackerModels:
    def test_fetch_issue_request(self):
        req = FetchIssueRequest(project_id="owner/repo", issue_id="123")
        assert req.issue_id == "123"

    def test_create_issue_request_defaults(self):
        req = CreateIssueRequest(project_id="owner/repo", title="Fix the bug")
        assert req.body == ""
        assert req.labels == []
        assert req.assignees == []
        assert req.priority == ""

    def test_update_issue_request_defaults(self):
        req = UpdateIssueRequest(project_id="owner/repo", issue_id="123")
        assert req.title == ""
        assert req.status == ""

    def test_list_issues_request_defaults(self):
        req = ListIssuesRequest(project_id="owner/repo")
        assert req.status == "open"
        assert req.limit == 50

    def test_issue_info_defaults(self):
        issue = IssueInfo(project_id="owner/repo", issue_id="123", title="Fix the bug")
        assert issue.status == "open"
        assert issue.labels == []
        assert issue.acceptance_criteria == []
        assert issue.url == ""

    def test_issue_info_with_criteria(self):
        issue = IssueInfo(
            project_id="owner/repo",
            issue_id="123",
            title="Fix the bug",
            acceptance_criteria=["All tests pass", "No regressions"],
        )
        assert len(issue.acceptance_criteria) == 2


# ---------------------------------------------------------------------------
# CISystem models
# ---------------------------------------------------------------------------


class TestCISystemModels:
    def test_fetch_run_request_defaults(self):
        req = FetchRunRequest(project_id="owner/repo", run_id="12345")
        assert not req.include_logs

    def test_trigger_run_request_defaults(self):
        req = TriggerRunRequest(project_id="owner/repo", workflow_id="ci.yml")
        assert req.ref == "main"
        assert req.inputs == {}

    def test_list_runs_request_defaults(self):
        req = ListRunsRequest(project_id="owner/repo")
        assert req.limit == 20
        assert req.branch == ""

    def test_ci_step_info(self):
        step = CIStepInfo(name="Run tests", status="completed", conclusion="success")
        assert step.duration_seconds == 0.0

    def test_ci_job_info_with_steps(self):
        job = CIJobInfo(
            job_id="j1",
            name="test",
            status="completed",
            conclusion="failure",
            steps=[CIStepInfo(name="pytest", status="completed", conclusion="failure")],
        )
        assert len(job.steps) == 1
        assert job.steps[0].conclusion == "failure"

    def test_ci_run_info_defaults(self):
        run = CIRunInfo(
            project_id="owner/repo",
            run_id="12345",
            workflow_name="CI",
            branch="main",
            status="completed",
        )
        assert run.conclusion == ""
        assert run.jobs == []
        assert run.inferred_validation_commands == []

    def test_ci_run_info_with_jobs(self):
        run = CIRunInfo(
            project_id="owner/repo",
            run_id="12345",
            workflow_name="CI",
            branch="main",
            status="completed",
            conclusion="failure",
            jobs=[CIJobInfo(job_id="j1", name="test", status="completed", conclusion="failure")],
        )
        assert len(run.jobs) == 1


# ---------------------------------------------------------------------------
# MonitoringSystem models
# ---------------------------------------------------------------------------


class TestMonitoringSystemModels:
    def test_fetch_alerts_request_defaults(self):
        req = FetchAlertsRequest()
        assert req.limit == 50
        assert req.severity == ""
        assert req.namespace == ""

    def test_query_metrics_request(self):
        req = QueryMetricsRequest(query="up{job='api'}")
        assert req.namespace == ""
        assert req.step == ""

    def test_alert_info(self):
        alert = AlertInfo(
            alert_id="a1",
            name="HighErrorRate",
            severity="critical",
            status="firing",
            summary="Error rate exceeded 5%",
        )
        assert alert.severity == "critical"
        assert alert.labels == {}

    def test_metric_series_defaults(self):
        series = MetricSeries()
        assert series.values == []
        assert series.labels == {}

    def test_metrics_result(self):
        result = MetricsResult(query="up")
        assert result.series == []
        assert result.metadata == {}


# ---------------------------------------------------------------------------
# MessagingSystem models
# ---------------------------------------------------------------------------


class TestMessagingSystemModels:
    def test_send_message_request(self):
        req = SendMessageRequest(destination="#engineering", body="Deployment complete.")
        assert req.subject == ""
        assert req.attachments == []

    def test_fetch_messages_request(self):
        req = FetchMessagesRequest(source="#engineering")
        assert req.limit == 50
        assert req.before == ""

    def test_message_info(self):
        msg = MessageInfo(
            message_id="m1",
            author="autodev",
            body="PR #42 opened.",
            destination="#engineering",
        )
        assert msg.sent_at == ""
        assert msg.metadata == {}

    def test_message_result(self):
        result = MessageResult(message_id="m1", destination="#engineering", delivered=True)
        assert result.delivered is True


# ---------------------------------------------------------------------------
# DocsProvider models
# ---------------------------------------------------------------------------


class TestDocsProviderModels:
    def test_fetch_document_request_defaults(self):
        req = FetchDocumentRequest(document_id="doc-001")
        assert req.space_id == ""

    def test_update_document_request_defaults(self):
        req = UpdateDocumentRequest(document_id="doc-001", body="# Hello")
        assert req.content_type == "markdown"
        assert req.title == ""

    def test_search_documents_request_defaults(self):
        req = SearchDocumentsRequest(query="architecture")
        assert req.limit == 20
        assert req.space_id == ""

    def test_document_info_defaults(self):
        doc = DocumentInfo(document_id="doc-001", title="Architecture")
        assert doc.content_type == "markdown"
        assert doc.body == ""
        assert doc.url == ""

    def test_document_search_result(self):
        result = DocumentSearchResult(document_id="doc-001", title="Architecture")
        assert result.score == 0.0
        assert result.excerpt == ""


# ---------------------------------------------------------------------------
# Stub adapters for Protocol isinstance checks
# ---------------------------------------------------------------------------


class _StubGitProvider:
    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(provider_id="stub-git", display_name="Stub Git")

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            operations=frozenset(
                {
                    ProviderCapability.FETCH_REPOSITORY,
                    ProviderCapability.CREATE_BRANCH,
                    ProviderCapability.CREATE_PULL_REQUEST,
                    ProviderCapability.GET_DIFF,
                    ProviderCapability.CLONE_REPOSITORY,
                }
            )
        )

    def fetch_repository(self, request: FetchRepositoryRequest) -> RepositoryInfo:
        return RepositoryInfo(repo_full_name=request.repo_full_name)

    def create_branch(self, request: CreateBranchRequest) -> BranchInfo:
        return BranchInfo(repo_full_name=request.repo_full_name, branch_name=request.branch_name)

    def create_pull_request(self, request: CreatePullRequestRequest) -> PullRequestInfo:
        return PullRequestInfo(
            repo_full_name=request.repo_full_name,
            pr_number=1,
            title=request.title,
            url="https://example.com/pull/1",
            head_branch=request.head_branch,
            base_branch=request.base_branch,
        )

    def get_diff(self, request: GetDiffRequest) -> DiffResult:
        return DiffResult(
            repo_full_name=request.repo_full_name,
            base_ref=request.base_ref,
            head_ref=request.head_ref,
        )

    def clone_repository(self, request: CloneRepositoryRequest) -> CloneResult:
        return CloneResult(repo_full_name=request.repo_full_name, dest_path=request.dest_path)


class _StubIssueTracker:
    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(provider_id="stub-issues", display_name="Stub Issues")

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            operations=frozenset(
                {
                    ProviderCapability.FETCH_ISSUE,
                    ProviderCapability.CREATE_ISSUE,
                    ProviderCapability.UPDATE_ISSUE,
                    ProviderCapability.LIST_ISSUES,
                }
            )
        )

    def fetch_issue(self, request: FetchIssueRequest) -> IssueInfo:
        return IssueInfo(
            project_id=request.project_id, issue_id=request.issue_id, title="Stub issue"
        )

    def create_issue(self, request: CreateIssueRequest) -> IssueInfo:
        return IssueInfo(project_id=request.project_id, issue_id="new-1", title=request.title)

    def update_issue(self, request: UpdateIssueRequest) -> IssueInfo:
        return IssueInfo(project_id=request.project_id, issue_id=request.issue_id, title="Updated")

    def list_issues(self, request: ListIssuesRequest) -> list[IssueInfo]:
        return []


# ---------------------------------------------------------------------------
# Protocol isinstance checks
# ---------------------------------------------------------------------------


class TestProtocolChecks:
    def test_stub_git_provider_satisfies_git_provider_protocol(self):
        provider = _StubGitProvider()
        assert isinstance(provider, GitProvider)

    def test_stub_git_provider_satisfies_integration_provider_protocol(self):
        provider = _StubGitProvider()
        assert isinstance(provider, IntegrationProvider)

    def test_stub_issue_tracker_satisfies_issue_tracker_protocol(self):
        tracker = _StubIssueTracker()
        assert isinstance(tracker, IssueTracker)

    def test_stub_issue_tracker_satisfies_integration_provider_protocol(self):
        tracker = _StubIssueTracker()
        assert isinstance(tracker, IntegrationProvider)

    def test_arbitrary_object_does_not_satisfy_git_provider(self):
        assert not isinstance(object(), GitProvider)

    def test_arbitrary_object_does_not_satisfy_integration_provider(self):
        assert not isinstance(object(), IntegrationProvider)

    def test_partial_implementation_does_not_satisfy_git_provider(self):
        class Partial:
            def provider_info(self) -> ProviderInfo:
                return ProviderInfo(provider_id="p", display_name="P")

            # Missing: capabilities, fetch_repository, create_branch, …

        assert not isinstance(Partial(), GitProvider)


# ---------------------------------------------------------------------------
# Capability-based dispatch pattern (the no-branching guarantee)
# ---------------------------------------------------------------------------


class TestCapabilityDispatchPattern:
    def test_supports_guards_operation_without_provider_branching(self):
        provider = _StubGitProvider()
        caps = provider.capabilities()

        assert caps.supports(ProviderCapability.CREATE_PULL_REQUEST)
        assert not caps.supports(ProviderCapability.TRIGGER_RUN)

    def test_require_gates_operation_before_call(self):
        provider = _StubGitProvider()
        caps = provider.capabilities()

        caps.require(ProviderCapability.FETCH_REPOSITORY)
        result = provider.fetch_repository(FetchRepositoryRequest(repo_full_name="owner/repo"))
        assert result.repo_full_name == "owner/repo"

    def test_require_raises_for_unsupported_operation(self):
        provider = _StubGitProvider()
        caps = provider.capabilities()

        with pytest.raises(NotImplementedError):
            caps.require(ProviderCapability.SEND_MESSAGE)

    def test_two_providers_same_protocol_are_swappable(self):
        """Runtime logic works with any GitProvider; no isinstance branching required."""

        class AnotherGitProvider:
            def provider_info(self) -> ProviderInfo:
                return ProviderInfo(provider_id="another-git", display_name="Another Git")

            def capabilities(self) -> CapabilitySet:
                return CapabilitySet(
                    operations=frozenset(
                        {
                            ProviderCapability.FETCH_REPOSITORY,
                            ProviderCapability.CREATE_BRANCH,
                            ProviderCapability.CREATE_PULL_REQUEST,
                            ProviderCapability.GET_DIFF,
                            ProviderCapability.CLONE_REPOSITORY,
                        }
                    )
                )

            def fetch_repository(self, request: FetchRepositoryRequest) -> RepositoryInfo:
                return RepositoryInfo(
                    repo_full_name=request.repo_full_name, default_branch="master"
                )

            def create_branch(self, request: CreateBranchRequest) -> BranchInfo:
                return BranchInfo(
                    repo_full_name=request.repo_full_name,
                    branch_name=request.branch_name,
                )

            def create_pull_request(self, request: CreatePullRequestRequest) -> PullRequestInfo:
                return PullRequestInfo(
                    repo_full_name=request.repo_full_name,
                    pr_number=99,
                    title=request.title,
                    url="https://another-git.example.com/pr/99",
                    head_branch=request.head_branch,
                    base_branch=request.base_branch,
                )

            def get_diff(self, request: GetDiffRequest) -> DiffResult:
                return DiffResult(
                    repo_full_name=request.repo_full_name,
                    base_ref=request.base_ref,
                    head_ref=request.head_ref,
                )

            def clone_repository(self, request: CloneRepositoryRequest) -> CloneResult:
                return CloneResult(
                    repo_full_name=request.repo_full_name, dest_path=request.dest_path
                )

        def open_pull_request(
            provider: GitProvider, repo: str, head: str, title: str
        ) -> PullRequestInfo:
            """Runtime function that accepts any GitProvider without type-checking."""
            caps = provider.capabilities()
            caps.require(ProviderCapability.CREATE_PULL_REQUEST)
            return provider.create_pull_request(
                CreatePullRequestRequest(repo_full_name=repo, head_branch=head, title=title)
            )

        stub = _StubGitProvider()
        another = AnotherGitProvider()

        pr1 = open_pull_request(stub, "owner/repo", "feature/x", "My feature")
        pr2 = open_pull_request(another, "owner/repo", "feature/x", "My feature")

        assert pr1.pr_number == 1
        assert pr2.pr_number == 99
        assert pr1.title == pr2.title == "My feature"
