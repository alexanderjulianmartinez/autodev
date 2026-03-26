"""CIRunReader: fetch GitHub Actions workflow run data from a run URL."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

_RUN_URL_RE = re.compile(
    r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/actions/runs/(?P<run_id>\d+)",
    re.IGNORECASE,
)

# Step-name substring → inferred CLI validation command
_STEP_CMD_PATTERNS = [
    (re.compile(r"pytest|run tests?", re.IGNORECASE), "pytest"),
    (re.compile(r"\bruff\b|lint", re.IGNORECASE), "ruff check ."),
    (re.compile(r"mypy|type.?check", re.IGNORECASE), "mypy ."),
    (re.compile(r"\bblack\b|format", re.IGNORECASE), "black --check ."),
    (re.compile(r"\bflake8\b", re.IGNORECASE), "flake8 ."),
    (re.compile(r"\bcoverage\b", re.IGNORECASE), "pytest --cov"),
]


def _infer_command(step_name: str) -> Optional[str]:
    """Return a candidate CLI command inferred from a CI step name, or None."""
    for pattern, cmd in _STEP_CMD_PATTERNS:
        if pattern.search(step_name):
            return cmd
    return None


@dataclass
class CIRunData:
    """Structured data extracted from a GitHub Actions workflow run."""

    run_id: int
    run_number: int
    run_url: str
    workflow_name: str
    branch: str
    conclusion: str  # "failure", "cancelled", "timed_out", etc.
    repo_full_name: str
    failing_jobs: list[dict[str, Any]] = field(default_factory=list)
    validation_commands: list[str] = field(default_factory=list)


class CIRunReader:
    """Reads GitHub Actions workflow run data using the PyGithub library."""

    def read(self, run_url: str) -> CIRunData:
        """Fetch and return CI run data for the given GitHub Actions run URL.

        Raises
        ------
        ValueError
            If *run_url* is not a valid GitHub Actions run URL.
        EnvironmentError
            If GITHUB_TOKEN is not set.
        RuntimeError
            If the run cannot be fetched (with the original error message).
        """
        owner, repo, run_id = self.parse_url(run_url)

        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise EnvironmentError(
                "GITHUB_TOKEN environment variable is not set. "
                "Please set it to read GitHub Actions run data."
            )

        from github import Github  # PyGithub

        gh = Github(token)
        gh_repo = gh.get_repo(f"{owner}/{repo}")
        run = gh_repo.get_workflow_run(run_id)

        failing_jobs: list[dict[str, Any]] = []
        validation_commands: list[str] = []
        seen_cmds: set[str] = set()

        for job in run.get_jobs():
            if job.conclusion in ("failure", "cancelled", "timed_out"):
                failing_steps = [
                    {"name": s.name, "conclusion": s.conclusion}
                    for s in job.steps
                    if s.conclusion in ("failure", "cancelled", "timed_out")
                ]
                failing_jobs.append(
                    {
                        "name": job.name,
                        "conclusion": job.conclusion,
                        "failing_steps": failing_steps,
                    }
                )
                for step in failing_steps:
                    cmd = _infer_command(step["name"])
                    if cmd and cmd not in seen_cmds:
                        seen_cmds.add(cmd)
                        validation_commands.append(cmd)

        return CIRunData(
            run_id=run_id,
            run_number=run.run_number,
            run_url=run_url,
            workflow_name=run.name or "CI",
            branch=run.head_branch or "",
            conclusion=run.conclusion or "failure",
            repo_full_name=f"{owner}/{repo}",
            failing_jobs=failing_jobs,
            validation_commands=validation_commands,
        )

    @staticmethod
    def parse_url(run_url: str) -> tuple[str, str, int]:
        """Return (owner, repo, run_id) parsed from *run_url*.

        Raises ValueError for invalid URLs.
        """
        match = _RUN_URL_RE.match(run_url.strip())
        if not match:
            raise ValueError(
                f"Invalid GitHub Actions run URL: {run_url!r}\n"
                "Expected format: https://github.com/<owner>/<repo>/actions/runs/<run_id>"
            )
        return match.group("owner"), match.group("repo"), int(match.group("run_id"))
