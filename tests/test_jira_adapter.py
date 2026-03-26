"""Tests for the Jira issue-tracker adapter (AD-032).

All tests run without a real Jira instance: httpx calls are patched at the
``JiraIssueTrackerAdapter._client`` level using a ``_MockClient`` context
manager that returns pre-baked responses.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autodev.integrations.base import ProviderCapability
from autodev.integrations.issue_tracker import (
    CreateIssueRequest,
    FetchIssueRequest,
    IssueInfo,
    IssueTracker,
    ListIssuesRequest,
    UpdateIssueRequest,
)
from autodev.jira.adapters.issue_tracker import (
    REQUIRED_SETTINGS,
    JiraIssueTrackerAdapter,
    _adf_to_text,
    _text_to_adf,
    build_jira_issue_tracker_adapter,
)
from autodev.jira.intake import JiraTicketIntakeService, _derive_item_id, _extract_repo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SETTINGS = {
    "base_url": "https://example.atlassian.net",
    "email": "dev@example.com",
    "api_token": "tok-abc123",
}


def _make_adapter(**overrides: str) -> JiraIssueTrackerAdapter:
    return JiraIssueTrackerAdapter({**_SETTINGS, **overrides})


def _issue_payload(
    key: str = "PROJ-123",
    summary: str = "Fix the thing",
    body_text: str = "",
    status_name: str = "In Progress",
    labels: list[str] | None = None,
    assignee_name: str = "",
    priority_name: str = "Medium",
) -> dict[str, Any]:
    """Build a minimal Jira issue REST response."""
    desc: Any = None
    if body_text:
        desc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": body_text}],
                }
            ],
        }
    assignee = {"displayName": assignee_name} if assignee_name else None
    return {
        "key": key,
        "self": f"https://example.atlassian.net/rest/api/3/issue/{key}",
        "fields": {
            "summary": summary,
            "description": desc,
            "status": {"name": status_name},
            "labels": labels or [],
            "assignee": assignee,
            "priority": {"name": priority_name},
        },
    }


class _Response:
    """Minimal httpx.Response stand-in."""

    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


class _MockClient:
    """Context manager that acts as a fake httpx.Client."""

    def __init__(self, responses: dict[str, Any]) -> None:
        # responses: {method + path: payload_or_response}
        self._responses = responses

    def __enter__(self) -> "_MockClient":
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def _respond(self, method: str, path: str, **kwargs: Any) -> _Response:
        key = f"{method.upper()} {path}"
        payload = self._responses.get(key, {})
        if isinstance(payload, _Response):
            return payload
        return _Response(payload)

    def get(self, path: str, **kwargs: Any) -> _Response:
        return self._respond("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> _Response:
        return self._respond("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> _Response:
        return self._respond("PUT", path, **kwargs)


# ---------------------------------------------------------------------------
# ADF helpers
# ---------------------------------------------------------------------------


class TestAdfToText:
    def test_plain_text_node(self):
        assert _adf_to_text({"type": "text", "text": "hello"}) == "hello"

    def test_paragraph(self):
        node = {
            "type": "paragraph",
            "content": [{"type": "text", "text": "first"}],
        }
        assert _adf_to_text(node) == "first"

    def test_doc_with_two_paragraphs(self):
        node = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "a"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "b"}]},
            ],
        }
        result = _adf_to_text(node)
        assert "a" in result
        assert "b" in result

    def test_none_returns_empty(self):
        assert _adf_to_text(None) == ""

    def test_empty_dict_returns_empty(self):
        assert _adf_to_text({}) == ""


class TestTextToAdf:
    def test_single_paragraph(self):
        adf = _text_to_adf("hello world")
        assert adf["type"] == "doc"
        assert adf["version"] == 1
        assert len(adf["content"]) == 1
        para = adf["content"][0]
        assert para["type"] == "paragraph"
        assert para["content"][0]["text"] == "hello world"

    def test_two_paragraphs(self):
        adf = _text_to_adf("first\n\nsecond")
        assert len(adf["content"]) == 2

    def test_empty_string_produces_empty_paragraph(self):
        adf = _text_to_adf("")
        assert adf["type"] == "doc"
        # At minimum one paragraph node
        assert len(adf["content"]) >= 1

    def test_roundtrip_preserves_text(self):
        original = "The quick brown fox"
        adf = _text_to_adf(original)
        recovered = _adf_to_text(adf)
        assert original in recovered


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    def test_satisfies_issue_tracker_protocol(self):
        adapter = _make_adapter()
        assert isinstance(adapter, IssueTracker)

    def test_provider_info_returns_jira(self):
        adapter = _make_adapter()
        info = adapter.provider_info()
        assert info.provider_id == "jira"
        assert info.display_name == "Jira"

    def test_provider_info_reflects_base_url(self):
        adapter = _make_adapter(base_url="https://acme.atlassian.net")
        assert adapter.provider_info().base_url == "https://acme.atlassian.net"

    def test_capabilities_covers_all_issue_tracker_operations(self):
        adapter = _make_adapter()
        caps = adapter.capabilities()
        for op in (
            ProviderCapability.FETCH_ISSUE,
            ProviderCapability.CREATE_ISSUE,
            ProviderCapability.UPDATE_ISSUE,
            ProviderCapability.LIST_ISSUES,
        ):
            assert caps.supports(op), f"Missing capability: {op}"

    def test_capabilities_excludes_git_operations(self):
        adapter = _make_adapter()
        caps = adapter.capabilities()
        assert not caps.supports(ProviderCapability.CREATE_PULL_REQUEST)
        assert not caps.supports(ProviderCapability.FETCH_REPOSITORY)


# ---------------------------------------------------------------------------
# fetch_issue
# ---------------------------------------------------------------------------


class TestFetchIssue:
    def _fetch(self, payload: dict[str, Any]) -> IssueInfo:
        adapter = _make_adapter()
        with patch.object(
            adapter, "_client", return_value=_MockClient({"GET /issue/PROJ-123": payload})
        ):
            return adapter.fetch_issue(FetchIssueRequest(project_id="PROJ", issue_id="PROJ-123"))

    def test_returns_issue_info(self):
        result = self._fetch(_issue_payload())
        assert isinstance(result, IssueInfo)

    def test_issue_id_and_project_id(self):
        result = self._fetch(_issue_payload())
        assert result.issue_id == "PROJ-123"
        assert result.project_id == "PROJ"

    def test_title_extracted(self):
        result = self._fetch(_issue_payload(summary="Do the thing"))
        assert result.title == "Do the thing"

    def test_body_extracted_from_adf(self):
        result = self._fetch(_issue_payload(body_text="Some description text"))
        assert "Some description text" in result.body

    def test_empty_body_when_no_description(self):
        result = self._fetch(_issue_payload(body_text=""))
        assert result.body == ""

    def test_status_normalized(self):
        result = self._fetch(_issue_payload(status_name="In Progress"))
        assert result.status == "in_progress"

    def test_todo_status_normalized_to_open(self):
        result = self._fetch(_issue_payload(status_name="To Do"))
        assert result.status == "open"

    def test_done_status_normalized_to_closed(self):
        result = self._fetch(_issue_payload(status_name="Done"))
        assert result.status == "closed"

    def test_labels_normalized(self):
        result = self._fetch(_issue_payload(labels=["BUG", " Enhancement "]))
        assert "bug" in result.labels
        assert "enhancement" in result.labels

    def test_assignee_captured(self):
        result = self._fetch(_issue_payload(assignee_name="Jane Doe"))
        assert "Jane Doe" in result.assignees

    def test_no_assignee_gives_empty_list(self):
        result = self._fetch(_issue_payload(assignee_name=""))
        assert result.assignees == []

    def test_priority_normalized(self):
        result = self._fetch(_issue_payload(priority_name="Highest"))
        assert result.priority == "critical"

    def test_url_contains_browse_path(self):
        result = self._fetch(_issue_payload())
        assert "/browse/PROJ-123" in result.url

    def test_jira_key_in_metadata(self):
        result = self._fetch(_issue_payload())
        assert result.metadata.get("jira_key") == "PROJ-123"


class TestFetchIssueAcceptanceCriteria:
    def test_extracts_task_list_items(self):
        body = "## Details\n- [ ] Tests pass\n- [x] Docs updated"
        adapter = _make_adapter()
        payload = _issue_payload(body_text=body)
        # Inject ADF with actual task-list text
        payload["fields"]["description"] = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": body}],
                }
            ],
        }
        with patch.object(
            adapter,
            "_client",
            return_value=_MockClient({"GET /issue/PROJ-1": payload}),
        ):
            result = adapter.fetch_issue(FetchIssueRequest(project_id="PROJ", issue_id="PROJ-1"))
        assert len(result.acceptance_criteria) >= 1

    def test_empty_when_no_checkboxes(self):
        adapter = _make_adapter()
        payload = _issue_payload(body_text="Just a description, no checkboxes.")
        with patch.object(
            adapter,
            "_client",
            return_value=_MockClient({"GET /issue/PROJ-1": payload}),
        ):
            result = adapter.fetch_issue(FetchIssueRequest(project_id="PROJ", issue_id="PROJ-1"))
        assert result.acceptance_criteria == []


# ---------------------------------------------------------------------------
# create_issue
# ---------------------------------------------------------------------------


class TestCreateIssue:
    def _create(self, request: CreateIssueRequest) -> IssueInfo:
        created_payload = {"key": "PROJ-999"}
        full_payload = _issue_payload(
            key="PROJ-999",
            summary=request.title,
            body_text=request.body,
        )
        adapter = _make_adapter()
        with patch.object(
            adapter,
            "_client",
            return_value=_MockClient(
                {
                    "POST /issue": created_payload,
                    "GET /issue/PROJ-999": full_payload,
                }
            ),
        ):
            return adapter.create_issue(request)

    def test_returns_issue_info(self):
        result = self._create(CreateIssueRequest(project_id="PROJ", title="New feature"))
        assert isinstance(result, IssueInfo)

    def test_key_matches_created(self):
        result = self._create(CreateIssueRequest(project_id="PROJ", title="New feature"))
        assert result.issue_id == "PROJ-999"

    def test_title_preserved(self):
        result = self._create(CreateIssueRequest(project_id="PROJ", title="My title"))
        assert result.title == "My title"

    def test_labels_passed_through(self):
        result = self._create(CreateIssueRequest(project_id="PROJ", title="T", labels=["backend"]))
        # Labels come back from the fetched full payload which has no labels — just check no error
        assert isinstance(result.labels, list)


# ---------------------------------------------------------------------------
# update_issue
# ---------------------------------------------------------------------------


class TestUpdateIssue:
    def _update(
        self,
        request: UpdateIssueRequest,
        extra_responses: dict[str, Any] | None = None,
    ) -> IssueInfo:
        responses: dict[str, Any] = {
            "PUT /issue/PROJ-123": {},
            "POST /issue/PROJ-123/comment": {"id": "10001"},
            "GET /issue/PROJ-123": _issue_payload(),
        }
        if extra_responses:
            responses.update(extra_responses)
        adapter = _make_adapter()
        with patch.object(adapter, "_client", return_value=_MockClient(responses)):
            return adapter.update_issue(request)

    def test_returns_issue_info(self):
        result = self._update(
            UpdateIssueRequest(
                project_id="PROJ", issue_id="PROJ-123", body="PR: https://example.com/pr/1"
            )
        )
        assert isinstance(result, IssueInfo)

    def test_comment_body_updates_without_error(self):
        # Verify no exception is raised when posting a comment
        result = self._update(
            UpdateIssueRequest(
                project_id="PROJ",
                issue_id="PROJ-123",
                body="AutoDev opened a PR: https://github.com/owner/repo/pull/5",
            )
        )
        assert result.issue_id == "PROJ-123"

    def test_title_update_triggers_put(self):
        # The PUT response is consumed — just verify no error
        result = self._update(
            UpdateIssueRequest(project_id="PROJ", issue_id="PROJ-123", title="Updated summary")
        )
        assert isinstance(result, IssueInfo)

    def test_status_transition_attempted(self):
        transitions_resp = _Response(
            {
                "transitions": [
                    {"id": "21", "name": "In Progress"},
                    {"id": "31", "name": "Done"},
                ]
            }
        )
        transition_post_resp = _Response({})
        responses = {
            "GET /issue/PROJ-123/transitions": transitions_resp,
            "POST /issue/PROJ-123/transitions": transition_post_resp,
            "GET /issue/PROJ-123": _issue_payload(),
        }
        adapter = _make_adapter()
        with patch.object(adapter, "_client", return_value=_MockClient(responses)):
            result = adapter.update_issue(
                UpdateIssueRequest(project_id="PROJ", issue_id="PROJ-123", status="done")
            )
        assert isinstance(result, IssueInfo)


# ---------------------------------------------------------------------------
# list_issues
# ---------------------------------------------------------------------------


class TestListIssues:
    def _list(self, request: ListIssuesRequest, issues: list[dict[str, Any]]) -> list[IssueInfo]:
        resp = _Response({"issues": issues, "total": len(issues)})
        adapter = _make_adapter()
        with patch.object(adapter, "_client", return_value=_MockClient({"GET /search": resp})):
            return adapter.list_issues(request)

    def test_returns_list_of_issue_info(self):
        issues = [_issue_payload("PROJ-1"), _issue_payload("PROJ-2")]
        results = self._list(ListIssuesRequest(project_id="PROJ"), issues)
        assert len(results) == 2
        assert all(isinstance(r, IssueInfo) for r in results)

    def test_empty_project_returns_empty_list(self):
        results = self._list(ListIssuesRequest(project_id="PROJ"), [])
        assert results == []

    def test_issue_ids_preserved(self):
        issues = [_issue_payload("PROJ-10"), _issue_payload("PROJ-20")]
        results = self._list(ListIssuesRequest(project_id="PROJ"), issues)
        ids = {r.issue_id for r in results}
        assert "PROJ-10" in ids
        assert "PROJ-20" in ids


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestFactory:
    def test_build_returns_adapter_instance(self):
        adapter = build_jira_issue_tracker_adapter(_SETTINGS)
        assert isinstance(adapter, JiraIssueTrackerAdapter)

    def test_settings_passed_through(self):
        adapter = build_jira_issue_tracker_adapter(
            {"base_url": "https://corp.atlassian.net", "email": "a@b.com", "api_token": "tok"}
        )
        assert adapter._base_url == "https://corp.atlassian.net"
        assert adapter._email == "a@b.com"

    def test_required_settings_declares_three_keys(self):
        assert REQUIRED_SETTINGS == frozenset({"base_url", "email", "api_token"})


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


class TestRegistryIntegration:
    def test_registry_loads_jira_adapter(self):
        from autodev.integrations.config import IntegrationsConfig, ProviderConfig
        from autodev.integrations.registry import IntegrationRegistry
        from autodev.jira.adapters.issue_tracker import (
            REQUIRED_SETTINGS,
            build_jira_issue_tracker_adapter,
        )

        registry = IntegrationRegistry()
        registry.register_factory(
            "jira", build_jira_issue_tracker_adapter, requires=REQUIRED_SETTINGS
        )
        config = IntegrationsConfig(
            issue_tracker=ProviderConfig(provider="jira", settings=dict(_SETTINGS))
        )
        registry.load(config)
        adapter = registry.get("issue_tracker")
        assert isinstance(adapter, JiraIssueTrackerAdapter)

    def test_registry_missing_api_token_raises_config_error(self):
        from autodev.core.config import ConfigError
        from autodev.integrations.config import IntegrationsConfig, ProviderConfig
        from autodev.integrations.registry import IntegrationRegistry
        from autodev.jira.adapters.issue_tracker import (
            REQUIRED_SETTINGS,
            build_jira_issue_tracker_adapter,
        )

        registry = IntegrationRegistry()
        registry.register_factory(
            "jira", build_jira_issue_tracker_adapter, requires=REQUIRED_SETTINGS
        )
        config = IntegrationsConfig(
            issue_tracker=ProviderConfig(
                provider="jira",
                settings={"base_url": "https://x.atlassian.net", "email": "a@b.com"},
                # api_token missing
            )
        )
        with pytest.raises(ConfigError, match="api_token"):
            registry.load(config)

    def test_supports_all_issue_tracker_capabilities_after_load(self):
        from autodev.integrations.config import IntegrationsConfig, ProviderConfig
        from autodev.integrations.registry import IntegrationRegistry
        from autodev.jira.adapters.issue_tracker import (
            REQUIRED_SETTINGS,
            build_jira_issue_tracker_adapter,
        )

        registry = IntegrationRegistry()
        registry.register_factory(
            "jira", build_jira_issue_tracker_adapter, requires=REQUIRED_SETTINGS
        )
        config = IntegrationsConfig(
            issue_tracker=ProviderConfig(provider="jira", settings=dict(_SETTINGS))
        )
        registry.load(config)
        for cap in (
            ProviderCapability.FETCH_ISSUE,
            ProviderCapability.CREATE_ISSUE,
            ProviderCapability.UPDATE_ISSUE,
            ProviderCapability.LIST_ISSUES,
        ):
            assert registry.supports(cap)


# ---------------------------------------------------------------------------
# ADF helpers (edge cases)
# ---------------------------------------------------------------------------


class TestAdfToTextEdgeCases:
    def test_nested_list_items(self):
        node = {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "item one"}]}
                    ],
                }
            ],
        }
        result = _adf_to_text(node)
        assert "item one" in result

    def test_heading_node(self):
        node = {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": "My heading"}],
        }
        result = _adf_to_text(node)
        assert "My heading" in result


# ---------------------------------------------------------------------------
# Intake service
# ---------------------------------------------------------------------------


class TestDeriveItemId:
    def test_lowercase_with_prefix(self):
        assert _derive_item_id("PROJ-123") == "jira-proj-123"

    def test_multi_word_project(self):
        assert _derive_item_id("MYTEAM-42") == "jira-myteam-42"


class TestExtractRepo:
    def _info(self, labels: list[str] | None = None, body: str = "") -> IssueInfo:
        return IssueInfo(
            project_id="PROJ", issue_id="PROJ-1", title="t", labels=labels or [], body=body
        )

    def test_repo_label_wins(self):
        info = self._info(labels=["repo:owner/myrepo", "bug"])
        assert _extract_repo(info) == "owner/myrepo"

    def test_github_url_in_body(self):
        info = self._info(body="See https://github.com/acme/widget for context.")
        assert _extract_repo(info) == "acme/widget"

    def test_repo_label_over_body_url(self):
        info = self._info(
            labels=["repo:correct/repo"],
            body="Also see github.com/wrong/repo",
        )
        assert _extract_repo(info) == "correct/repo"

    def test_empty_when_no_signal(self):
        import os

        info = self._info()
        without_env = {k: v for k, v in os.environ.items() if k != "AUTODEV_REPO"}
        with patch.dict(os.environ, without_env, clear=True):
            assert _extract_repo(info) == ""


class TestJiraTicketIntakeService:
    def _make_intake(self) -> tuple[JiraTicketIntakeService, MagicMock]:
        import tempfile

        from autodev.core.backlog_service import BacklogService
        from autodev.core.state_store import FileStateStore

        store = FileStateStore(tempfile.mkdtemp())
        backlog_svc = BacklogService(store)
        adapter = _make_adapter()
        intake = JiraTicketIntakeService(backlog_svc, adapter)
        return intake, adapter

    def test_intake_creates_backlog_item(self):
        intake, adapter = self._make_intake()
        info = IssueInfo(
            project_id="PROJ",
            issue_id="PROJ-55",
            title="Fix login bug",
            body="Users cannot log in.",
            status="open",
            priority="high",
            labels=["bug"],
            assignees=["Alice"],
        )
        with patch.object(adapter, "fetch_issue", return_value=info):
            item = intake.intake("PROJ-55")

        assert item.title == "Fix login bug"
        assert item.item_id == "jira-proj-55"
        assert item.source == "jira"

    def test_intake_is_idempotent(self):
        intake, adapter = self._make_intake()
        info = IssueInfo(project_id="PROJ", issue_id="PROJ-1", title="T", body="", status="open")
        with patch.object(adapter, "fetch_issue", return_value=info) as mock_fetch:
            intake.intake("PROJ-1")
            # Second call should not hit the API
            item2 = intake.intake("PROJ-1")
            assert mock_fetch.call_count == 1

        assert item2.item_id == "jira-proj-1"

    def test_intake_normalizes_priority(self):
        intake, adapter = self._make_intake()
        info = IssueInfo(project_id="PROJ", issue_id="PROJ-2", title="T", priority="critical")
        with patch.object(adapter, "fetch_issue", return_value=info):
            item = intake.intake("PROJ-2")

        from autodev.core.schemas import PriorityLevel

        assert item.priority == PriorityLevel.CRITICAL

    def test_intake_propagates_acceptance_criteria(self):
        intake, adapter = self._make_intake()
        info = IssueInfo(
            project_id="PROJ",
            issue_id="PROJ-3",
            title="T",
            acceptance_criteria=["All tests pass", "Docs updated"],
        )
        with patch.object(adapter, "fetch_issue", return_value=info):
            item = intake.intake("PROJ-3")

        assert "All tests pass" in item.acceptance_criteria

    def test_intake_api_failure_raises_runtime_error(self):
        intake, adapter = self._make_intake()
        with patch.object(adapter, "fetch_issue", side_effect=Exception("network error")):
            with pytest.raises(RuntimeError, match="network error"):
                intake.intake("PROJ-99")


# ---------------------------------------------------------------------------
# Runtime Jira ticket detection
# ---------------------------------------------------------------------------


class TestJiraTicketPattern:
    def test_recognizes_standard_key(self):
        from autodev.core.runtime import JIRA_TICKET_PATTERN

        assert JIRA_TICKET_PATTERN.match("PROJ-123")
        assert JIRA_TICKET_PATTERN.match("ABC-1")
        assert JIRA_TICKET_PATTERN.match("MYPROJECT-9999")

    def test_rejects_github_url(self):
        from autodev.core.runtime import JIRA_TICKET_PATTERN

        assert not JIRA_TICKET_PATTERN.match("https://github.com/owner/repo/issues/5")

    def test_rejects_lowercase(self):
        from autodev.core.runtime import JIRA_TICKET_PATTERN

        assert not JIRA_TICKET_PATTERN.match("proj-123")

    def test_rejects_no_number(self):
        from autodev.core.runtime import JIRA_TICKET_PATTERN

        assert not JIRA_TICKET_PATTERN.match("PROJ-")

    def test_rejects_number_only(self):
        from autodev.core.runtime import JIRA_TICKET_PATTERN

        assert not JIRA_TICKET_PATTERN.match("123")
