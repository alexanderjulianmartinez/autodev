"""Tests for GitHub integration components."""

import pytest

from autodev.core.backlog_service import BacklogService
from autodev.core.schemas import PriorityLevel
from autodev.core.state_store import FileStateStore
from autodev.github.issue_intake import (
    IssueIntakeService,
    _derive_item_id,
    _extract_acceptance_criteria,
    _map_priority,
)
from autodev.github.issue_reader import IssueData, IssueReader


class TestIssueReader:
    def test_url_parsing_valid(self):
        reader = IssueReader()
        owner, repo, number = reader.parse_url("https://github.com/octocat/Hello-World/issues/42")
        assert owner == "octocat"
        assert repo == "Hello-World"
        assert number == 42

    def test_invalid_url_raises(self):
        reader = IssueReader()
        with pytest.raises(ValueError, match="Invalid GitHub issue URL"):
            reader.parse_url("https://github.com/octocat/Hello-World/pull/42")

    def test_no_token_raises(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        reader = IssueReader()
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            reader.read("https://github.com/octocat/Hello-World/issues/1")

    def test_invalid_url_in_read_raises(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        reader = IssueReader()
        with pytest.raises(ValueError, match="Invalid GitHub issue URL"):
            reader.read("https://notgithub.com/issues/1")


class TestIssueIntakeService:
    _URL = "https://github.com/octocat/Hello-World/issues/42"

    def _make_service(self, tmp_path, stub_issue=None):
        store = FileStateStore(str(tmp_path))
        service = BacklogService(store)
        reader = IssueReader()
        if stub_issue is not None:
            reader.read = lambda _url: stub_issue
        return IssueIntakeService(service, reader)

    def _stub_issue(self, **kwargs) -> IssueData:
        defaults = dict(
            number=42,
            title="Add retry logic",
            body="Improve reliability.\n\n- [ ] handle transient errors\n- [x] add backoff",
            labels=["priority:p1", "type:core"],
            repo_full_name="octocat/Hello-World",
        )
        return IssueData(**{**defaults, **kwargs})

    def test_intake_creates_backlog_item(self, tmp_path):
        svc = self._make_service(tmp_path, self._stub_issue())
        item = svc.intake(self._URL)
        assert item.item_id == "issue-octocat-hello-world-42"
        assert item.title == "Add retry logic"
        assert item.source == "github_issue"

    def test_intake_preserves_labels_and_repo_metadata(self, tmp_path):
        svc = self._make_service(tmp_path, self._stub_issue())
        item = svc.intake(self._URL)
        assert "priority:p1" in item.labels
        assert "type:core" in item.labels
        assert item.metadata["repo_full_name"] == "octocat/Hello-World"
        assert item.metadata["issue_number"] == 42

    def test_intake_extracts_checkbox_acceptance_criteria(self, tmp_path):
        svc = self._make_service(tmp_path, self._stub_issue())
        item = svc.intake(self._URL)
        assert "handle transient errors" in item.acceptance_criteria
        assert "add backoff" in item.acceptance_criteria

    def test_intake_maps_priority_label(self, tmp_path):
        svc = self._make_service(tmp_path, self._stub_issue(labels=["priority:p0"]))
        item = svc.intake(self._URL)
        assert item.priority == PriorityLevel.CRITICAL

    def test_intake_defaults_to_medium_priority_when_no_label(self, tmp_path):
        svc = self._make_service(tmp_path, self._stub_issue(labels=["type:core"]))
        item = svc.intake(self._URL)
        assert item.priority == PriorityLevel.MEDIUM

    def test_intake_is_idempotent(self, tmp_path):
        svc = self._make_service(tmp_path, self._stub_issue())
        item_a = svc.intake(self._URL)
        item_b = svc.intake(self._URL)
        assert item_a.item_id == item_b.item_id

    def test_intake_raises_on_invalid_url(self, tmp_path):
        svc = self._make_service(tmp_path)
        with pytest.raises(ValueError, match="Cannot ingest issue"):
            svc.intake("https://github.com/octocat/Hello-World/pull/42")

    def test_intake_propagates_environment_error_for_missing_token(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        store = FileStateStore(str(tmp_path))
        svc = IssueIntakeService(BacklogService(store))
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            svc.intake(self._URL)

    def test_intake_wraps_fetch_errors_with_actionable_message(self, tmp_path):
        store = FileStateStore(str(tmp_path))
        reader = IssueReader()
        reader.read = lambda _url: (_ for _ in ()).throw(RuntimeError("not found"))
        svc = IssueIntakeService(BacklogService(store), reader)
        with pytest.raises(RuntimeError, match="Could not fetch issue"):
            svc.intake(self._URL)

    def test_derive_item_id_slugifies_repo(self):
        assert _derive_item_id("octocat", "Hello-World", 42) == "issue-octocat-hello-world-42"

    def test_extract_acceptance_criteria_returns_checkbox_text(self):
        body = "Do the thing.\n\n- [ ] step one\n- [x] step two\n- plain bullet"
        assert _extract_acceptance_criteria(body) == ["step one", "step two"]

    def test_map_priority_returns_medium_for_unknown_labels(self):
        assert _map_priority(["bug", "enhancement"]) == PriorityLevel.MEDIUM


class TestPRCreator:
    def test_no_token_raises(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        from autodev.github.pr_creator import PRCreator

        creator = PRCreator()
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            creator.create(
                repo_full_name="owner/repo",
                branch_name="feature/test",
                title="Test PR",
                body="Test body",
            )
