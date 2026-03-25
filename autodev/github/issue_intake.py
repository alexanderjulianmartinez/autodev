"""IssueIntakeService: normalize a GitHub issue into a durable BacklogItem."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from autodev.core.backlog_service import BacklogService
from autodev.core.schemas import BacklogItem, PriorityLevel
from autodev.github.issue_reader import IssueData, IssueReader

logger = logging.getLogger(__name__)

# Matches GitHub task-list items: "- [ ] ..." and "- [x] ..."
_CHECKBOX_RE = re.compile(r"^\s*-\s*\[[xX ]\]\s*(.+)", re.MULTILINE)
_SAFE_ID_CHARS = re.compile(r"[^a-z0-9._-]+")

_LABEL_PRIORITY_MAP: dict[str, PriorityLevel] = {
    "priority:p0": PriorityLevel.CRITICAL,
    "priority:p1": PriorityLevel.HIGH,
    "priority:p2": PriorityLevel.MEDIUM,
    "priority:p3": PriorityLevel.LOW,
}


def _derive_item_id(owner: str, repo: str, number: int) -> str:
    slug = _SAFE_ID_CHARS.sub("-", f"{owner}-{repo}".lower()).strip("-._")
    return f"issue-{slug}-{number}"


def _extract_acceptance_criteria(body: str) -> list[str]:
    """Return text of all task-list checkboxes found in *body*."""
    return [m.group(1).strip() for m in _CHECKBOX_RE.finditer(body)]


def _map_priority(labels: list[str]) -> PriorityLevel:
    for label in labels:
        if label.lower() in _LABEL_PRIORITY_MAP:
            return _LABEL_PRIORITY_MAP[label.lower()]
    return PriorityLevel.MEDIUM


class IssueIntakeService:
    """Transform a GitHub issue URL into a persisted BacklogItem.

    Re-intaking an already-persisted issue is idempotent: the existing item
    is returned unchanged.
    """

    def __init__(
        self,
        backlog_service: BacklogService,
        issue_reader: IssueReader | None = None,
    ) -> None:
        self.backlog_service = backlog_service
        self.issue_reader = issue_reader or IssueReader()

    def intake(self, issue_url: str) -> BacklogItem:
        """Read *issue_url* and return a persisted BacklogItem.

        Raises
        ------
        ValueError
            If *issue_url* is not a valid GitHub issue URL.
        EnvironmentError
            If GITHUB_TOKEN is not set.
        RuntimeError
            If the issue cannot be fetched (with the original error message).
        """
        owner, repo, number = self._parse_url(issue_url)
        item_id = _derive_item_id(owner, repo, number)

        if self.backlog_service.exists(item_id):
            logger.info("Issue already ingested as backlog item %r; returning existing.", item_id)
            return self.backlog_service.get_item(item_id)

        issue = self._fetch_issue(issue_url)
        return self._create_item(item_id, issue)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_url(self, issue_url: str) -> tuple[str, str, int]:
        try:
            owner, repo, number = self.issue_reader.parse_url(issue_url)
        except ValueError as exc:
            raise ValueError(
                f"Cannot ingest issue: {exc}. "
                "Provide a URL in the form https://github.com/<owner>/<repo>/issues/<number>."
            ) from exc
        return owner, repo, number

    def _fetch_issue(self, issue_url: str) -> IssueData:
        try:
            return self.issue_reader.read(issue_url)
        except EnvironmentError:
            raise
        except Exception as exc:
            parsed = urlparse(issue_url)
            raise RuntimeError(
                f"Could not fetch issue {parsed.path!r}: {exc}. "
                "Check that the repository is accessible and the issue number is valid."
            ) from exc

    def _create_item(self, item_id: str, issue: IssueData) -> BacklogItem:
        acceptance_criteria = _extract_acceptance_criteria(issue.body)
        priority = _map_priority(issue.labels)
        description = issue.body.strip()

        item = self.backlog_service.create_item(
            item_id=item_id,
            title=issue.title,
            description=description,
            priority=priority,
            labels=list(issue.labels),
            acceptance_criteria=acceptance_criteria,
            source="github_issue",
            metadata={
                "issue_url": f"https://github.com/{issue.repo_full_name}/issues/{issue.number}",
                "issue_number": issue.number,
                "repo_full_name": issue.repo_full_name,
            },
        )
        logger.info(
            "Ingested issue #%d from %s as backlog item %r",
            issue.number,
            issue.repo_full_name,
            item_id,
        )
        return item
