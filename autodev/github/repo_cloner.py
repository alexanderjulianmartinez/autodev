"""RepoCloner: clone a GitHub repository to a local path."""

from __future__ import annotations

import logging
import os

from autodev.tools.git_tool import GitTool

logger = logging.getLogger(__name__)


class RepoCloner:
    """Clones a GitHub repository using GitTool."""

    def __init__(self) -> None:
        self._git = GitTool()

    def clone(self, repo_full_name: str, dest_path: str) -> str:
        """Clone *repo_full_name* (e.g. 'owner/repo') to *dest_path*.

        Uses GITHUB_TOKEN when available for authentication.
        Returns the destination path.
        """
        token = os.environ.get("GITHUB_TOKEN", "")
        if token:
            repo_url = f"https://{token}@github.com/{repo_full_name}.git"
        else:
            repo_url = f"https://github.com/{repo_full_name}.git"

        logger.info("Cloning %s → %s", repo_full_name, dest_path)
        return self._git.clone(repo_url, dest_path)
