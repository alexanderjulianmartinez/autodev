"""GitTool: clone, branch, commit, and push via GitPython."""

from __future__ import annotations

import logging
import subprocess
from typing import Any
from urllib.parse import urlparse

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
        if action == "create_worktree":
            self.create_worktree(
                input["repo_path"],
                input["worktree_path"],
                input["branch_name"],
            )
            return {"ok": True}
        if action == "remove_worktree":
            self.remove_worktree(
                input["repo_path"],
                input["worktree_path"],
                force=bool(input.get("force", False)),
            )
            return {"ok": True}
        if action == "reset_hard":
            self.reset_hard(input["repo_path"], input.get("ref", "HEAD"))
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
        logger.info("Cloning %s → %s", self._sanitize_repo_url(repo_url), dest_path)
        try:
            import git  # GitPython

            git.Repo.clone_from(repo_url, dest_path)
        except ModuleNotFoundError:
            self._run_git_command(["clone", repo_url, dest_path])
        return dest_path

    def create_branch(self, repo_path: str, branch_name: str) -> None:
        """Create and check out a new branch."""
        try:
            import git

            repo = git.Repo(repo_path)
            repo.git.checkout("-b", branch_name)
        except ModuleNotFoundError:
            self._run_git_command(["-C", repo_path, "checkout", "-b", branch_name])
        logger.info("Created branch %r in %s", branch_name, repo_path)

    def create_worktree(self, repo_path: str, worktree_path: str, branch_name: str) -> None:
        """Create a worktree at *worktree_path* on a new branch."""
        try:
            import git

            repo = git.Repo(repo_path)
            repo.git.worktree("add", "-b", branch_name, worktree_path)
        except ModuleNotFoundError:
            self._run_git_command(
                ["-C", repo_path, "worktree", "add", "-b", branch_name, worktree_path]
            )
        logger.info(
            "Created worktree %r from %s on branch %r",
            worktree_path,
            repo_path,
            branch_name,
        )

    def remove_worktree(self, repo_path: str, worktree_path: str, *, force: bool = False) -> None:
        """Remove a worktree previously created under *repo_path*."""
        args = ["remove"]
        if force:
            args.append("--force")
        args.append(worktree_path)
        try:
            import git

            repo = git.Repo(repo_path)
            repo.git.worktree(*args)
        except ModuleNotFoundError:
            self._run_git_command(["-C", repo_path, "worktree", *args])
        logger.info("Removed worktree %r from %s", worktree_path, repo_path)

    def reset_hard(self, repo_path: str, ref: str = "HEAD") -> None:
        """Reset a repository to *ref* and discard uncommitted changes."""
        try:
            import git

            repo = git.Repo(repo_path)
            repo.git.reset("--hard", ref)
            repo.git.clean("-fd")
        except ModuleNotFoundError:
            self._run_git_command(["-C", repo_path, "reset", "--hard", ref])
            self._run_git_command(["-C", repo_path, "clean", "-fd"])
        logger.info("Reset %s to %r", repo_path, ref)

    def commit(
        self,
        repo_path: str,
        message: str,
        files: list[str] | None = None,
    ) -> None:
        """Stage *files* (or all changes) and create a commit."""
        try:
            import git

            repo = git.Repo(repo_path)
            if files:
                repo.index.add(files)
            else:
                repo.git.add("--all")
            repo.index.commit(message)
        except ModuleNotFoundError:
            if files:
                self._run_git_command(["-C", repo_path, "add", *files])
            else:
                self._run_git_command(["-C", repo_path, "add", "--all"])
            self._run_git_command(["-C", repo_path, "commit", "-m", message])
        logger.info("Committed: %r", message)

    def push(self, repo_path: str, branch_name: str) -> None:
        """Push *branch_name* to the default remote."""
        try:
            import git

            repo = git.Repo(repo_path)
            origin = repo.remotes["origin"]
            origin.push(branch_name)
        except ModuleNotFoundError:
            self._run_git_command(["-C", repo_path, "push", "origin", branch_name])
        logger.info("Pushed branch %r", branch_name)

    def _sanitize_repo_url(self, repo_url: str) -> str:
        parsed = urlparse(repo_url)
        if parsed.scheme and parsed.netloc:
            host = parsed.hostname or parsed.netloc.rsplit("@", maxsplit=1)[-1]
            path = parsed.path or ""
            return f"{host}{path}"
        if "@" in repo_url and ":" in repo_url:
            return repo_url.rsplit(":", maxsplit=1)[0].rsplit("@", maxsplit=1)[-1]
        return repo_url

    def _run_git_command(self, args: list[str]) -> None:
        try:
            completed = subprocess.run(
                ["git", *args],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("git executable is not available") from exc
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "git failed")
