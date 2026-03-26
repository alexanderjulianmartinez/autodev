"""GitTool: clone, branch, commit, and push via GitPython."""

from __future__ import annotations

import contextlib
import logging
import os
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, Generator, Optional
from urllib.parse import urlparse, urlunparse

from autodev.tools.base import Tool

logger = logging.getLogger(__name__)
GIT_URL_CREDENTIALS_PATTERN = re.compile(r"(?P<scheme>https?://)(?P<userinfo>[^/\s@]+)@")


@contextlib.contextmanager
def _git_credential_env(url: str) -> Generator[tuple[str, dict[str, str]], None, None]:
    """Strip embedded credentials from a git URL and expose them via GIT_ASKPASS.

    Yields ``(clean_url, extra_env)``.  If the URL carries no credentials,
    yields ``(url, {})`` without creating any temp files.

    The GIT_ASKPASS helper is a tiny Python script that reads the token from
    ``_AUTODEV_GIT_TOKEN`` in the subprocess environment rather than
    hardcoding it in the script body or in a subprocess argument — preventing
    the token from being visible in ``/proc/<pid>/cmdline`` or ``ps`` output.
    """
    parsed = urlparse(url)
    token = parsed.password or parsed.username or ""
    if not token:
        yield url, {}
        return

    # Reconstruct URL without credentials in the netloc
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    clean_url = urlunparse(parsed._replace(netloc=netloc))

    helper = (
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "prompt = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "if 'Username' in prompt:\n"
        "    print(os.environ.get('_AUTODEV_GIT_USER', 'x-token'))\n"
        "else:\n"
        "    print(os.environ.get('_AUTODEV_GIT_TOKEN', ''))\n"
    )
    fd, helper_path = tempfile.mkstemp(suffix=".py")
    try:
        os.write(fd, helper.encode())
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        os.close(fd)
        yield (
            clean_url,
            {
                "GIT_ASKPASS": helper_path,
                "GIT_TERMINAL_PROMPT": "0",
                "_AUTODEV_GIT_TOKEN": token,
                "_AUTODEV_GIT_USER": parsed.username or "x-token",
            },
        )
    finally:
        try:
            os.unlink(helper_path)
        except OSError:
            pass


def sanitize_git_output(text: str) -> str:
    if not text:
        return text
    return GIT_URL_CREDENTIALS_PATTERN.sub(r"\g<scheme>***@", text)


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
        """Clone *repo_url* into *dest_path* and return the destination.

        If the URL contains embedded credentials (``https://token@host/...``),
        they are extracted and supplied via a temporary GIT_ASKPASS helper so
        the token never appears in subprocess argument lists or ``/proc`` cmdline
        entries.  The helper file is deleted unconditionally when the clone
        completes or fails.
        """
        logger.info("Cloning %s → %s", self._sanitize_repo_url(repo_url), dest_path)
        with _git_credential_env(repo_url) as (url, cred_env):
            merged_env: Optional[dict[str, str]] = {**os.environ, **cred_env} if cred_env else None
            try:
                import git  # GitPython
            except ModuleNotFoundError:
                self._run_git_command(["clone", url, dest_path], env=merged_env)
                return dest_path

            try:
                git.Repo.clone_from(url, dest_path, env=merged_env)
            except Exception as exc:
                # Always wrap in RuntimeError with a sanitized message so that
                # any credential material in the exception is redacted,
                # regardless of whether the sanitizer regex matched.
                raise RuntimeError(sanitize_git_output(str(exc))) from exc
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

    def run_git(self, args: list[str], *, env: Optional[dict[str, str]] = None) -> str:
        """Run a raw git command and return stdout; raises RuntimeError with sanitized output."""
        try:
            completed = subprocess.run(
                ["git", *args],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("git executable is not available") from exc
        if completed.returncode != 0:
            error = sanitize_git_output(
                completed.stderr.strip() or completed.stdout.strip() or "git failed"
            )
            raise RuntimeError(error)
        return completed.stdout

    def _run_git_command(self, args: list[str], env: Optional[dict[str, str]] = None) -> None:
        self.run_git(args, env=env)
