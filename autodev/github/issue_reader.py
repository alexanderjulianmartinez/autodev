"""IssueReader: fetch GitHub issue data from a URL."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass
class IssueData:
    """Structured data extracted from a GitHub issue."""

    number: int
    title: str
    body: str
    labels: list[str]
    repo_full_name: str


# Pattern: https://github.com/<owner>/<repo>/issues/<number>
_ISSUE_URL_RE = re.compile(
    r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)",
    re.IGNORECASE,
)


class IssueReader:
    """Reads GitHub issues using the PyGithub library."""

    def read(self, issue_url: str) -> IssueData:
        """Fetch and return issue data for the given URL.

        Raises
        ------
        ValueError
            If *issue_url* is not a valid GitHub issue URL.
        EnvironmentError
            If GITHUB_TOKEN is not set.
        """
        match = _ISSUE_URL_RE.match(issue_url.strip())
        if not match:
            raise ValueError(
                f"Invalid GitHub issue URL: {issue_url!r}\n"
                "Expected format: https://github.com/<owner>/<repo>/issues/<number>"
            )

        owner = match.group("owner")
        repo = match.group("repo")
        number = int(match.group("number"))
        repo_full_name = f"{owner}/{repo}"

        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise EnvironmentError(
                "GITHUB_TOKEN environment variable is not set. Please set it to read GitHub issues."
            )

        from github import Github  # PyGithub

        gh = Github(token)
        gh_repo = gh.get_repo(repo_full_name)
        issue = gh_repo.get_issue(number)

        return IssueData(
            number=number,
            title=issue.title,
            body=issue.body or "",
            labels=[label.name for label in issue.labels],
            repo_full_name=repo_full_name,
        )

    @staticmethod
    def parse_url(issue_url: str) -> tuple[str, str, int]:
        """Return (owner, repo, issue_number) parsed from *issue_url*.

        Raises ValueError for invalid URLs.
        """
        match = _ISSUE_URL_RE.match(issue_url.strip())
        if not match:
            raise ValueError(f"Invalid GitHub issue URL: {issue_url!r}")
        return match.group("owner"), match.group("repo"), int(match.group("number"))
