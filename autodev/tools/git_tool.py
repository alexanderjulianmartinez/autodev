"""GitTool: clone, branch, commit, and push via GitPython."""

from __future__ import annotations

import logging
from typing import Any

from autodev.tools.base import Tool

logger = logging.getLogger(__name__)


class GitTool(Tool):
    """Wraps common git operations using GitPython."""

    def execute(self, input: dict[str, Any]) -> dict[str, Any]:
        action = input.get("action", "")
        if action == "clone":
            return {"path": self.clone(input["repo_url"], input["dest_path"])}
        if action == "create_branch":
            self.create_branch(input["repo_path"], input["branch_name"])
            return {"ok": True}
        if action == "commit":
            self.commit(input["repo_path"], input["message"], input.get("files"))
            return {"ok": True}
        if action == "push":
            self.push(input["repo_path"], input["branch_name"])
            return {"ok": True}
        raise ValueError(f"Unknown git action: {action!r}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def clone(self, repo_url: str, dest_path: str) -> str:
        """Clone *repo_url* into *dest_path* and return the destination."""
        import git  # GitPython
        logger.info("Cloning %s → %s", repo_url, dest_path)
        git.Repo.clone_from(repo_url, dest_path)
        return dest_path

    def create_branch(self, repo_path: str, branch_name: str) -> None:
        """Create and check out a new branch."""
        import git
        repo = git.Repo(repo_path)
        repo.git.checkout("-b", branch_name)
        logger.info("Created branch %r in %s", branch_name, repo_path)

    def commit(
        self,
        repo_path: str,
        message: str,
        files: list[str] | None = None,
    ) -> None:
        """Stage *files* (or all changes) and create a commit."""
        import git
        repo = git.Repo(repo_path)
        if files:
            repo.index.add(files)
        else:
            repo.git.add("--all")
        repo.index.commit(message)
        logger.info("Committed: %r", message)

    def push(self, repo_path: str, branch_name: str) -> None:
        """Push *branch_name* to the default remote."""
        import git
        repo = git.Repo(repo_path)
        origin = repo.remotes["origin"]
        origin.push(branch_name)
        logger.info("Pushed branch %r", branch_name)
