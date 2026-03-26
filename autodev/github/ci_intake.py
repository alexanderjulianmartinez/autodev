"""CIIntakeService: normalize a GitHub Actions run into a durable BacklogItem."""

from __future__ import annotations

import logging
import re

from autodev.core.backlog_service import BacklogService
from autodev.core.schemas import BacklogItem, PriorityLevel
from autodev.github.ci_runner import CIRunData, CIRunReader

logger = logging.getLogger(__name__)

_SAFE_ID_CHARS = re.compile(r"[^a-z0-9._-]+")
_MAIN_BRANCHES = {"main", "master"}


def _derive_item_id(owner: str, repo: str, run_id: int) -> str:
    slug = _SAFE_ID_CHARS.sub("-", f"{owner}-{repo}".lower()).strip("-._")
    return f"ci-{slug}-{run_id}"


def _map_priority(branch: str) -> PriorityLevel:
    """CRITICAL for main/master branches; HIGH for all others."""
    return PriorityLevel.CRITICAL if branch in _MAIN_BRANCHES else PriorityLevel.HIGH


def _build_description(run: CIRunData) -> str:
    lines = [
        f"CI workflow **{run.workflow_name}** (run #{run.run_number}) "
        f"failed on branch `{run.branch}`.",
        "",
        "## Failing Jobs",
    ]
    for job in run.failing_jobs:
        lines.append(f"\n### {job['name']} — {job['conclusion']}")
        if job["failing_steps"]:
            lines.append("Failing steps:")
            for step in job["failing_steps"]:
                lines.append(f"- {step['name']} ({step['conclusion']})")
    if run.validation_commands:
        lines += ["", "## Candidate Validation Commands"]
        for cmd in run.validation_commands:
            lines.append(f"- `{cmd}`")
    return "\n".join(lines)


def _build_acceptance_criteria(run: CIRunData) -> list[str]:
    criteria: list[str] = []
    seen: set[str] = set()
    for job in run.failing_jobs:
        for step in job["failing_steps"]:
            text = f"Fix failing step: {step['name']}"
            if text not in seen:
                seen.add(text)
                criteria.append(text)
    return criteria or [f"Fix {run.workflow_name} CI failure on {run.branch}"]


class CIIntakeService:
    """Transform a GitHub Actions run URL into a persisted BacklogItem.

    Re-intaking an already-persisted run is idempotent: the existing item
    is returned unchanged.
    """

    def __init__(
        self,
        backlog_service: BacklogService,
        ci_reader: CIRunReader | None = None,
    ) -> None:
        self.backlog_service = backlog_service
        self.ci_reader = ci_reader or CIRunReader()

    def intake(self, run_url: str) -> BacklogItem:
        """Read *run_url* and return a persisted BacklogItem.

        Raises
        ------
        ValueError
            If *run_url* is not a valid GitHub Actions run URL.
        EnvironmentError
            If GITHUB_TOKEN is not set.
        RuntimeError
            If the run cannot be fetched (with the original error message).
        """
        owner, repo, run_id = self._parse_url(run_url)
        item_id = _derive_item_id(owner, repo, run_id)

        if self.backlog_service.exists(item_id):
            logger.info("CI run already ingested as backlog item %r; returning existing.", item_id)
            return self.backlog_service.get_item(item_id)

        run = self._fetch_run(run_url)
        return self._create_item(item_id, run)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_url(self, run_url: str) -> tuple[str, str, int]:
        try:
            return self.ci_reader.parse_url(run_url)
        except ValueError as exc:
            raise ValueError(
                f"Cannot ingest CI run: {exc}. "
                "Provide a URL in the form "
                "https://github.com/<owner>/<repo>/actions/runs/<run_id>."
            ) from exc

    def _fetch_run(self, run_url: str) -> CIRunData:
        try:
            return self.ci_reader.read(run_url)
        except EnvironmentError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Could not fetch CI run {run_url!r}: {exc}. "
                "Check that the repository is accessible and the run ID is valid."
            ) from exc

    def _create_item(self, item_id: str, run: CIRunData) -> BacklogItem:
        title = f"CI Fix: {run.workflow_name} failed on run #{run.run_number} ({run.branch})"
        item = self.backlog_service.create_item(
            item_id=item_id,
            title=title,
            description=_build_description(run),
            priority=_map_priority(run.branch),
            labels=["source:github-actions", "type:ci-fix"],
            acceptance_criteria=_build_acceptance_criteria(run),
            source="github_actions",
            metadata={
                "run_url": run.run_url,
                "repo_full_name": run.repo_full_name,
                "workflow_name": run.workflow_name,
                "run_number": run.run_number,
                "branch": run.branch,
                "failing_jobs": run.failing_jobs,
                "validation_commands": run.validation_commands,
            },
        )
        logger.info(
            "Ingested CI run #%d from %s as backlog item %r",
            run.run_number,
            run.repo_full_name,
            item_id,
        )
        return item
