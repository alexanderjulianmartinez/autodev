"""JiraTicketIntakeService: normalize a Jira ticket into a durable BacklogItem.

The intake service is the bridge between Jira and the AutoDev pipeline.
It fetches a ticket by its key (e.g. ``PROJ-123``), normalises the metadata
into a :class:`~autodev.core.schemas.BacklogItem`, and persists it so the
pipeline has a stable, provider-agnostic record to work from.

Repo mapping
------------
The pipeline needs to know which GitHub repository to clone and target for the
PR.  The intake service infers this from (in priority order):

1. A ``repo:<owner>/<name>`` label on the Jira ticket.
2. A GitHub URL (``github.com/<owner>/<repo>``) embedded in the ticket body.
3. The ``AUTODEV_REPO`` environment variable.

If none of these are found, ``repo_full_name`` is left empty and the pipeline
will fall back to cloning from the run context.

Re-intake is idempotent: calling ``intake`` with the same ticket key returns
the already-persisted item without hitting the Jira API again.
"""

from __future__ import annotations

import logging
import os
import re

from autodev.core.backlog_service import BacklogService
from autodev.core.schemas import BacklogItem, PriorityLevel
from autodev.integrations.issue_tracker import FetchIssueRequest, IssueInfo
from autodev.jira.adapters.issue_tracker import JiraIssueTrackerAdapter

logger = logging.getLogger(__name__)

_SAFE_ID_CHARS = re.compile(r"[^a-z0-9._-]+")
# Matches "repo:owner/name" label
_REPO_LABEL_RE = re.compile(r"^repo:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)$", re.IGNORECASE)
# Matches github.com/owner/repo in body text
_GITHUB_URL_RE = re.compile(
    r"github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)", re.IGNORECASE
)

_PRIORITY_LEVEL_MAP: dict[str, PriorityLevel] = {
    "critical": PriorityLevel.CRITICAL,
    "high": PriorityLevel.HIGH,
    "medium": PriorityLevel.MEDIUM,
    "low": PriorityLevel.LOW,
}


def _derive_item_id(ticket_key: str) -> str:
    slug = _SAFE_ID_CHARS.sub("-", ticket_key.lower()).strip("-._")
    return f"jira-{slug}"


def _map_priority(normalized: str) -> PriorityLevel:
    return _PRIORITY_LEVEL_MAP.get(normalized, PriorityLevel.MEDIUM)


def _extract_repo(info: IssueInfo) -> str:
    """Infer the target GitHub repo from ticket labels, body, or env var."""
    # 1. repo:<owner>/<name> label
    for label in info.labels:
        m = _REPO_LABEL_RE.match(label)
        if m:
            return m.group(1)

    # 2. GitHub URL in body
    m = _GITHUB_URL_RE.search(info.body)
    if m:
        return f"{m.group('owner')}/{m.group('repo')}"

    # 3. Env var fallback
    return os.environ.get("AUTODEV_REPO", "")


class JiraTicketIntakeService:
    """Transform a Jira ticket key into a persisted BacklogItem.

    Re-intaking an already-persisted ticket is idempotent: the existing item
    is returned unchanged.
    """

    def __init__(
        self,
        backlog_service: BacklogService,
        adapter: JiraIssueTrackerAdapter,
    ) -> None:
        self.backlog_service = backlog_service
        self.adapter = adapter

    def intake(self, ticket_key: str) -> BacklogItem:
        """Fetch *ticket_key* from Jira and return a persisted BacklogItem.

        Args:
            ticket_key: Jira issue key, e.g. ``"PROJ-123"``.

        Raises:
            EnvironmentError: If Jira settings (base_url, email, api_token) are
                missing from the adapter.
            httpx.HTTPStatusError: If the Jira API returns a non-2xx response.
            RuntimeError: If the ticket cannot be fetched for any other reason.
        """
        ticket_key = ticket_key.strip().upper()
        item_id = _derive_item_id(ticket_key)

        if self.backlog_service.exists(item_id):
            logger.info(
                "Jira ticket %r already ingested as backlog item %r; returning existing.",
                ticket_key,
                item_id,
            )
            return self.backlog_service.get_item(item_id)

        project_key = ticket_key.split("-")[0]
        try:
            info = self.adapter.fetch_issue(
                FetchIssueRequest(project_id=project_key, issue_id=ticket_key)
            )
        except Exception as exc:
            raise RuntimeError(
                f"Could not fetch Jira ticket {ticket_key!r}: {exc}. "
                "Verify that JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN are set "
                "and that the ticket key is valid."
            ) from exc

        item = self._create_item(item_id, info, ticket_key)
        logger.info("Ingested Jira ticket %r as backlog item %r", ticket_key, item_id)
        return item

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_item(self, item_id: str, info: IssueInfo, ticket_key: str) -> BacklogItem:
        repo_full_name = _extract_repo(info)
        return self.backlog_service.create_item(
            item_id=item_id,
            title=info.title,
            description=info.body,
            priority=_map_priority(info.priority),
            labels=list(info.labels),
            acceptance_criteria=list(info.acceptance_criteria),
            source="jira",
            metadata={
                "jira_key": ticket_key,
                "jira_url": info.url,
                "jira_status": info.metadata.get("jira_status", ""),
                "jira_priority": info.metadata.get("jira_priority", ""),
                "assignee": info.assignees[0] if info.assignees else "",
                "repo_full_name": repo_full_name,
            },
        )
