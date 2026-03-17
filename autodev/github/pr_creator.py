"""PRCreator: open a pull request on GitHub."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


class PRCreator:
    """Creates pull requests using the PyGithub library."""

    def create(
        self,
        repo_full_name: str,
        branch_name: str,
        title: str,
        body: str,
        base_branch: str = "main",
    ) -> str:
        """Create a pull request and return its HTML URL.

        Raises
        ------
        EnvironmentError
            If GITHUB_TOKEN is not set.
        """
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise EnvironmentError(
                "GITHUB_TOKEN environment variable is not set. "
                "Please set it to create pull requests."
            )

        from github import Github  # PyGithub

        gh = Github(token)
        repo = gh.get_repo(repo_full_name)
        pr = repo.create_pull(
            title=title,
            body=body,
            head=branch_name,
            base=base_branch,
        )
        logger.info("Pull request created: %s", pr.html_url)
        return pr.html_url
