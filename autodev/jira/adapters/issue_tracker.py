"""Jira implementation of the IssueTracker interface.

``JiraIssueTrackerAdapter`` connects to a Jira Cloud or Server instance via the
REST API v3 and exposes the four operations defined by the ``IssueTracker``
Protocol: fetch, create, update (fields + comment + transition), and list.

Authentication
--------------
Jira Cloud uses HTTP Basic auth with an Atlassian account email and an API
token generated from https://id.atlassian.com/manage-profile/security/api-tokens.

Settings
--------
base_url (required)
    Your Jira instance root, e.g. ``https://myorg.atlassian.net``.
email (required)
    The Atlassian account email for authentication.
api_token (required)
    API token tied to the account above.

Extension points
----------------
GitLab, Linear, and other trackers follow the same four-step pattern used here:

1. Create a module under the relevant adapter package.
2. Implement ``provider_info``, ``capabilities``, and all four ``IssueTracker``
   methods against the provider's API.
3. Write a ``build_*_adapter(settings)`` factory.
4. Register the factory in ``IntegrationRegistry``::

       registry.register_factory("linear", build_linear_adapter, requires={"api_key"})

Update semantics
----------------
``update_issue`` applies field changes, optional status transition, and an
optional comment in a single call:

- ``title`` → updates the Jira *summary* field.
- ``labels`` → replaces the *labels* field.
- ``status`` → finds the matching Jira transition and executes it.
- ``body`` → posts a new comment (does not overwrite the description).

This makes it straightforward to post a PR link back to a ticket::

    tracker.update_issue(UpdateIssueRequest(
        project_id="PROJ", issue_id="PROJ-123",
        body=f"PR opened: {pr_url}",
    ))
"""

from __future__ import annotations

import logging
from typing import Any

from autodev.integrations.base import CapabilitySet, ProviderCapability, ProviderInfo
from autodev.integrations.issue_tracker import (
    CreateIssueRequest,
    FetchIssueRequest,
    IssueInfo,
    ListIssuesRequest,
    UpdateIssueRequest,
)
from autodev.integrations.normalize import (
    extract_section_items,
    extract_task_list_items,
    normalize_labels,
    normalize_priority,
    normalize_status,
)

logger = logging.getLogger(__name__)

_JIRA_CAPABILITIES = frozenset(
    {
        ProviderCapability.FETCH_ISSUE,
        ProviderCapability.CREATE_ISSUE,
        ProviderCapability.UPDATE_ISSUE,
        ProviderCapability.LIST_ISSUES,
    }
)

# Map canonical priority → Jira priority name
_CANONICAL_TO_JIRA_PRIORITY: dict[str, str] = {
    "critical": "Highest",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}

# Acceptance-criteria section names to search for
_AC_SECTION_NAMES: set[str] = {
    "acceptance criteria",
    "acceptance criterion",
    "done criteria",
    "definition of done",
}


# ---------------------------------------------------------------------------
# ADF helpers
# ---------------------------------------------------------------------------


def _adf_to_text(node: dict[str, Any] | None) -> str:
    """Recursively extract plain text from an Atlassian Document Format node.

    Paragraph and list-item boundaries become newlines; inline nodes are
    concatenated directly.

    Returns an empty string when *node* is ``None`` or empty.
    """
    if not node:
        return ""
    node_type = node.get("type", "")
    if node_type == "text":
        return node.get("text", "")

    child_texts = [_adf_to_text(child) for child in node.get("content", [])]
    separator = "\n" if node_type in ("paragraph", "heading", "listItem") else ""
    joined = separator.join(t for t in child_texts if t)
    return joined


def _text_to_adf(text: str) -> dict[str, Any]:
    """Convert plain text to a minimal Atlassian Document Format document.

    Each double-newline-separated block becomes a paragraph node.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    content: list[dict[str, Any]] = [
        {"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paragraphs
    ]
    return {
        "version": 1,
        "type": "doc",
        "content": content or [{"type": "paragraph", "content": []}],
    }


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class JiraIssueTrackerAdapter:
    """Jira implementation of the ``IssueTracker`` Protocol.

    Constructed by ``build_jira_issue_tracker_adapter()`` from a settings dict,
    compatible with ``IntegrationRegistry.register_factory()``.
    """

    def __init__(self, settings: dict[str, str]) -> None:
        self._base_url = settings.get("base_url", "").rstrip("/")
        self._email = settings.get("email", "")
        self._api_token = settings.get("api_token", "")

    # ------------------------------------------------------------------
    # IntegrationProvider contract
    # ------------------------------------------------------------------

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            provider_id="jira",
            display_name="Jira",
            base_url=self._base_url,
            capabilities=self.capabilities(),
        )

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(operations=_JIRA_CAPABILITIES)

    # ------------------------------------------------------------------
    # IssueTracker contract
    # ------------------------------------------------------------------

    def fetch_issue(self, request: FetchIssueRequest) -> IssueInfo:
        """Fetch a single Jira issue by its key (e.g. ``PROJ-123``)."""
        with self._client() as client:
            resp = client.get(f"/issue/{request.issue_id}")
            resp.raise_for_status()
            return self._normalize_issue(resp.json())

    def create_issue(self, request: CreateIssueRequest) -> IssueInfo:
        """Create a new Jira issue and return normalized metadata."""
        fields: dict[str, Any] = {
            "project": {"key": request.project_id},
            "summary": request.title,
            "issuetype": {"name": "Story"},
        }
        if request.body:
            fields["description"] = _text_to_adf(request.body)
        if request.labels:
            fields["labels"] = list(request.labels)
        if request.priority:
            jira_priority = _CANONICAL_TO_JIRA_PRIORITY.get(request.priority, "Medium")
            fields["priority"] = {"name": jira_priority}

        with self._client() as client:
            resp = client.post("/issue", json={"fields": fields})
            resp.raise_for_status()
            key = resp.json()["key"]
            resp2 = client.get(f"/issue/{key}")
            resp2.raise_for_status()
            return self._normalize_issue(resp2.json())

    def update_issue(self, request: UpdateIssueRequest) -> IssueInfo:
        """Apply field updates, status transition, and/or a comment.

        - ``title`` updates the Jira summary.
        - ``labels`` replaces the Jira labels field.
        - ``status`` transitions the issue to the matching workflow state.
        - ``body`` posts a new comment (does not overwrite the description).
        """
        fields: dict[str, Any] = {}
        if request.title:
            fields["summary"] = request.title
        if request.labels:
            fields["labels"] = list(request.labels)

        with self._client() as client:
            if fields:
                resp = client.put(f"/issue/{request.issue_id}", json={"fields": fields})
                resp.raise_for_status()

            if request.status:
                self._transition_issue(client, request.issue_id, request.status)

            if request.body:
                resp = client.post(
                    f"/issue/{request.issue_id}/comment",
                    json={"body": _text_to_adf(request.body)},
                )
                resp.raise_for_status()

            resp = client.get(f"/issue/{request.issue_id}")
            resp.raise_for_status()
            return self._normalize_issue(resp.json())

    def list_issues(self, request: ListIssuesRequest) -> list[IssueInfo]:
        """Search issues in a project using JQL."""
        jql_parts = [f"project = {request.project_id}"]
        if request.status:
            normalized = normalize_status(request.status)
            if normalized == "open":
                jql_parts.append("statusCategory != Done")
            elif normalized == "in_progress":
                jql_parts.append("statusCategory = 'In Progress'")
            elif normalized == "closed":
                jql_parts.append("statusCategory = Done")
        if request.assignee:
            jql_parts.append(f"assignee = '{request.assignee}'")
        for label in request.labels:
            jql_parts.append(f"labels = '{label}'")

        jql = " AND ".join(jql_parts)
        params = {
            "jql": jql,
            "maxResults": str(request.limit),
            "fields": "summary,description,status,labels,assignee,priority,issuetype",
        }
        with self._client() as client:
            resp = client.get("/search", params=params)
            resp.raise_for_status()
            data = resp.json()

        return [self._normalize_issue(issue) for issue in data.get("issues", [])]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _client(self):  # type: ignore[return]
        """Return a configured ``httpx.Client`` for the Jira REST API v3."""
        import httpx  # httpx is a core autodev dependency — imported lazily

        return httpx.Client(
            base_url=f"{self._base_url}/rest/api/3",
            auth=(self._email, self._api_token),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=30.0,
        )

    def _normalize_issue(self, data: dict[str, Any]) -> IssueInfo:
        """Map a raw Jira issue payload to a normalized :class:`IssueInfo`."""
        key = data.get("key", "")
        fields = data.get("fields", {})
        project_key = key.split("-")[0] if "-" in key else ""

        # Description (ADF in API v3)
        raw_desc = fields.get("description")
        body = _adf_to_text(raw_desc) if isinstance(raw_desc, dict) else (raw_desc or "")

        # Status
        status_raw = (fields.get("status") or {}).get("name", "")

        # Labels
        labels = normalize_labels(fields.get("labels") or [])

        # Assignee
        assignee_obj = fields.get("assignee") or {}
        assignee_name = assignee_obj.get("displayName") or assignee_obj.get("emailAddress") or ""

        # Priority
        priority_raw = (fields.get("priority") or {}).get("name", "")

        # Acceptance criteria — task-list items first, then named section
        ac = extract_task_list_items(body)
        if not ac:
            ac = extract_section_items(body, _AC_SECTION_NAMES)

        return IssueInfo(
            project_id=project_key,
            issue_id=key,
            title=fields.get("summary", ""),
            body=body,
            status=normalize_status(status_raw),
            labels=labels,
            assignees=[assignee_name] if assignee_name else [],
            url=f"{self._base_url}/browse/{key}",
            priority=normalize_priority(priority_raw),
            acceptance_criteria=ac,
            metadata={
                "jira_key": key,
                "jira_status": status_raw,
                "jira_priority": priority_raw,
            },
        )

    def _transition_issue(self, client: Any, issue_id: str, target_status: str) -> None:
        """Execute the Jira workflow transition whose name best matches *target_status*."""
        resp = client.get(f"/issue/{issue_id}/transitions")
        resp.raise_for_status()
        transitions = resp.json().get("transitions", [])

        normalized_target = normalize_status(target_status)
        for transition in transitions:
            if normalize_status(transition.get("name", "")) == normalized_target:
                client.post(
                    f"/issue/{issue_id}/transitions",
                    json={"transition": {"id": transition["id"]}},
                ).raise_for_status()
                logger.info(
                    "Transitioned %s via %r (id=%s)",
                    issue_id,
                    transition["name"],
                    transition["id"],
                )
                return

        logger.warning(
            "No transition found matching %r for %s; available: %s",
            target_status,
            issue_id,
            [t.get("name") for t in transitions],
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

#: Settings keys required by this factory.
REQUIRED_SETTINGS: frozenset[str] = frozenset({"base_url", "email", "api_token"})


def build_jira_issue_tracker_adapter(settings: dict[str, str]) -> JiraIssueTrackerAdapter:
    """Construct a :class:`JiraIssueTrackerAdapter` from a settings dict.

    Intended for use with :meth:`IntegrationRegistry.register_factory`::

        registry.register_factory(
            "jira",
            build_jira_issue_tracker_adapter,
            requires=REQUIRED_SETTINGS,
        )
    """
    return JiraIssueTrackerAdapter(settings)
