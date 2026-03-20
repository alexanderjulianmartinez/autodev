"""Workspace management for run-local execution, snapshots, and diff capture."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from autodev.core.schemas import IsolationMode, RunMetadata, RunStatus, utc_now
from autodev.core.state_store import FileStateStore
from autodev.github.repo_cloner import RepoCloner
from autodev.tools.git_tool import GitTool

logger = logging.getLogger(__name__)


class WorkspaceManager:
    """Manage dedicated per-run workspaces and implementation artifacts."""

    def __init__(
        self,
        state_store: FileStateStore,
        repo_cloner: Optional[RepoCloner] = None,
        git_tool: Optional[GitTool] = None,
    ) -> None:
        self.state_store = state_store
        self.repo_cloner = repo_cloner or RepoCloner()
        self.git_tool = git_tool or GitTool()

    def create_run(
        self,
        backlog_item_id: str,
        *,
        run_id: Optional[str] = None,
        isolation_mode: IsolationMode = IsolationMode.SNAPSHOT,
        metadata: Optional[dict[str, Any]] = None,
    ) -> RunMetadata:
        run_identifier = run_id or f"run-{uuid4().hex[:12]}"
        workspace_path = self.workspace_dir(run_identifier)
        self.snapshots_dir(run_identifier)
        self.artifacts_dir(run_identifier)

        run = RunMetadata(
            run_id=run_identifier,
            backlog_item_id=backlog_item_id,
            status=RunStatus.RUNNING,
            workspace_path=str(workspace_path),
            isolation_mode=isolation_mode,
            started_at=utc_now(),
            metadata=dict(metadata or {}),
        )
        self.state_store.save_run(run)
        return run

    def base_repo_dir(self, run_id: str) -> Path:
        repository = self.state_store.run_dir(run_id) / "repository"
        repository.mkdir(parents=True, exist_ok=True)
        return repository

    def quarantine_dir(self, run_id: str) -> Path:
        quarantine = self.state_store.run_dir(run_id) / "quarantine"
        quarantine.mkdir(parents=True, exist_ok=True)
        return quarantine

    def workspace_dir(self, run_id: str) -> Path:
        workspace = self.state_store.run_dir(run_id) / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def snapshots_dir(self, run_id: str) -> Path:
        snapshots = self.state_store.run_dir(run_id) / "snapshots"
        snapshots.mkdir(parents=True, exist_ok=True)
        return snapshots

    def artifacts_dir(self, run_id: str) -> Path:
        artifacts = self.state_store.run_dir(run_id) / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        return artifacts

    def populate_workspace(self, run_id: str, source_path: str) -> Path:
        run = self.state_store.load_run(run_id)
        if run.isolation_mode != IsolationMode.SNAPSHOT:
            raise ValueError(
                "populate_workspace only supports snapshot isolation, got "
                f"{run.isolation_mode.value!r}"
            )

        source = Path(source_path).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(source)

        workspace = self.workspace_dir(run_id)
        if any(workspace.iterdir()):
            raise ValueError(f"Workspace for run {run_id!r} is already populated")

        self._copy_tree_preserving_symlinks(source, workspace, dirs_exist_ok=True)
        self._update_run_metadata(run_id, {"source_path": str(source)})
        return workspace

    def prepare_local_repository(self, run_id: str, source_path: str) -> Path:
        run = self.state_store.load_run(run_id)
        source = Path(source_path).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(source)

        if run.isolation_mode == IsolationMode.SNAPSHOT:
            return self.populate_workspace(run_id, str(source))

        branch_name = self._branch_name(run)
        if run.isolation_mode == IsolationMode.BRANCH:
            workspace = self.workspace_dir(run_id)
            self._ensure_empty_directory(workspace, run_id)
            self.git_tool.clone(str(source), str(workspace))
            self.git_tool.create_branch(str(workspace), branch_name)
            self._update_run_metadata(
                run_id,
                {
                    "source_path": str(source),
                    "isolation_branch": branch_name,
                },
            )
            return workspace

        if run.isolation_mode == IsolationMode.WORKTREE:
            base_repo = self.base_repo_dir(run_id)
            workspace = self.workspace_dir(run_id)
            self._ensure_empty_directory(base_repo, run_id)
            self._ensure_empty_directory(workspace, run_id)
            self.git_tool.clone(str(source), str(base_repo))
            self.git_tool.create_worktree(str(base_repo), str(workspace), branch_name)
            self._update_run_metadata(
                run_id,
                {
                    "source_path": str(source),
                    "base_repo_path": str(base_repo),
                    "isolation_branch": branch_name,
                },
            )
            return workspace

        raise ValueError(f"Unsupported isolation mode: {run.isolation_mode.value!r}")

    def clone_repo(self, run_id: str, repo_full_name: str) -> Path:
        run = self.state_store.load_run(run_id)
        branch_name = self._branch_name(run)

        if run.isolation_mode == IsolationMode.SNAPSHOT:
            workspace = self.workspace_dir(run_id)
            self._ensure_empty_directory(workspace, run_id)
            cloned_path = Path(self.repo_cloner.clone(repo_full_name, str(workspace))).resolve()
            self._update_run_metadata(run_id, {"repo_full_name": repo_full_name})
            return cloned_path

        if run.isolation_mode == IsolationMode.BRANCH:
            workspace = self.workspace_dir(run_id)
            self._ensure_empty_directory(workspace, run_id)
            cloned_path = Path(self.repo_cloner.clone(repo_full_name, str(workspace))).resolve()
            self.git_tool.create_branch(str(cloned_path), branch_name)
            self._update_run_metadata(
                run_id,
                {
                    "repo_full_name": repo_full_name,
                    "isolation_branch": branch_name,
                },
            )
            return cloned_path

        if run.isolation_mode == IsolationMode.WORKTREE:
            base_repo = self.base_repo_dir(run_id)
            workspace = self.workspace_dir(run_id)
            self._ensure_empty_directory(base_repo, run_id)
            self._ensure_empty_directory(workspace, run_id)
            cloned_base = Path(self.repo_cloner.clone(repo_full_name, str(base_repo))).resolve()
            self.git_tool.create_worktree(str(cloned_base), str(workspace), branch_name)
            self._update_run_metadata(
                run_id,
                {
                    "repo_full_name": repo_full_name,
                    "base_repo_path": str(cloned_base),
                    "isolation_branch": branch_name,
                },
            )
            return workspace.resolve()

        raise ValueError(f"Unsupported isolation mode: {run.isolation_mode.value!r}")

    def finalize_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        quarantine_on_failure: bool = False,
    ) -> RunMetadata:
        run = self.state_store.load_run(run_id)
        quarantine_path: Optional[Path] = None
        if quarantine_on_failure and status == RunStatus.FAILED:
            quarantine_path = self.quarantine_run(run_id)

        self._teardown_isolation(run)
        metadata_update: dict[str, Any] = {"teardown_completed_at": utc_now().isoformat()}
        if quarantine_path is not None:
            metadata_update["quarantined_workspace_path"] = str(quarantine_path)

        return self.state_store.update_run(
            run_id,
            lambda current: current.model_copy(
                update={
                    "status": status,
                    "completed_at": utc_now(),
                    "metadata": {**current.metadata, **metadata_update},
                }
            ),
        )

    def quarantine_run(self, run_id: str) -> Path:
        run = self.state_store.load_run(run_id)
        workspace = Path(run.workspace_path).expanduser().resolve()
        destination = self.quarantine_dir(run_id) / workspace.name
        if destination.exists():
            shutil.rmtree(destination)
        try:
            if run.isolation_mode == IsolationMode.WORKTREE:
                self._quarantine_worktree_repository(run, workspace, destination)
            else:
                self._copy_tree_preserving_symlinks(workspace, destination)
        except Exception:
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            raise
        return destination

    def rollback_run(self, run_id: str) -> None:
        run = self.state_store.load_run(run_id)
        workspace = Path(run.workspace_path).expanduser().resolve()
        if (workspace / ".git").exists() or (workspace / ".git").is_file():
            self.git_tool.reset_hard(str(workspace))
        self._update_run_metadata(run_id, {"rollback_completed_at": utc_now().isoformat()})

    def snapshot_file(self, run_id: str, file_path: str, *, label: str = "before-edit") -> Path:
        workspace = Path(self.state_store.load_run(run_id).workspace_path).expanduser().resolve()
        target = Path(file_path).expanduser().resolve()
        if not target.exists():
            raise FileNotFoundError(target)

        try:
            relative_path = target.relative_to(workspace)
        except ValueError as exc:
            raise ValueError(f"File {target} is outside workspace for run {run_id!r}") from exc

        safe_label = self._validate_snapshot_label(label)
        snapshots_root = self.snapshots_dir(run_id).resolve()
        destination = (snapshots_root / safe_label / relative_path).resolve()
        try:
            destination.relative_to(snapshots_root)
        except ValueError as exc:
            raise ValueError(
                f"Snapshot destination escaped snapshots directory for run {run_id!r}"
            ) from exc
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, destination)
        return destination

    def capture_implementation_artifacts(self, run_id: str) -> dict[str, Path]:
        diff_path, diff_success, diff_error = self._capture_diff_artifact(run_id)
        changed_files_path, changed_files_success, changed_files_error = (
            self._capture_changed_files_artifact(run_id)
        )
        errors = [error for error in [diff_error, changed_files_error] if error]
        self._update_run_metadata(
            run_id,
            {
                "implementation_diff_path": str(diff_path),
                "changed_files_path": str(changed_files_path),
                "last_artifact_capture_at": utc_now().isoformat(),
                "implementation_artifact_capture": {
                    "success": diff_success and changed_files_success,
                    "diff_success": diff_success,
                    "changed_files_success": changed_files_success,
                    "errors": errors,
                },
            },
        )
        return {"diff": diff_path, "changed_files": changed_files_path}

    def capture_diff(self, run_id: str) -> Path:
        path, _success, _error = self._capture_diff_artifact(run_id)
        return path

    def save_changed_files_summary(self, run_id: str) -> Path:
        path, _success, _error = self._capture_changed_files_artifact(run_id)
        return path

    def _capture_diff_artifact(self, run_id: str) -> tuple[Path, bool, Optional[str]]:
        workspace = self.workspace_dir(run_id)
        success, diff_text, error = self._run_git_command(
            workspace,
            ["diff", "--no-color", "--binary"],
        )
        path = self.artifacts_dir(run_id) / "working_tree.diff"
        if success:
            self._write_text(path, diff_text)
        else:
            self._write_text(path, f"Artifact capture failed: {error or 'unknown git error'}\n")
        return path, success, error

    def _capture_changed_files_artifact(self, run_id: str) -> tuple[Path, bool, Optional[str]]:
        workspace = self.workspace_dir(run_id)
        success, status_output, error = self._run_git_command(
            workspace,
            ["status", "--porcelain=v1", "-z"],
        )
        files = self._parse_porcelain_status(status_output) if success else []

        payload = {
            "generated_at": utc_now().isoformat(),
            "success": success,
            "files": files,
        }
        if error:
            payload["error"] = error
        path = self.artifacts_dir(run_id) / "changed_files.json"
        self._write_json(path, payload)
        return path, success, error

    def _parse_porcelain_status(self, status_output: str) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        records = status_output.split("\0")
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            if len(record) < 3:
                logger.warning("Skipping malformed git status record: %r", record)
                continue

            status = record[:2].strip()
            path = record[3:]
            entry: dict[str, str] = {"path": path, "status": status}
            if status[:1] in {"R", "C"} and index < len(records):
                previous_path = records[index]
                index += 1
                if previous_path:
                    entry["previous_path"] = previous_path
            entries.append(entry)
        return entries

    def _update_run_metadata(self, run_id: str, metadata: dict[str, Any]) -> RunMetadata:
        return self.state_store.update_run(
            run_id,
            lambda current: current.model_copy(
                update={
                    "metadata": {**current.metadata, **metadata},
                }
            ),
        )

    def _branch_name(self, run: RunMetadata) -> str:
        normalized = run.backlog_item_id.lower().replace("/", "-").replace("_", "-")
        return f"autodev/{normalized}-{run.run_id}"

    def _validate_snapshot_label(self, label: str) -> str:
        candidate = label.strip()
        if not candidate:
            raise ValueError("Snapshot label must not be empty")
        if candidate in {".", ".."}:
            raise ValueError(f"Invalid snapshot label: {label!r}")
        if "/" in candidate or "\\" in candidate or ".." in candidate:
            raise ValueError(f"Invalid snapshot label: {label!r}")
        return candidate

    def _ensure_empty_directory(self, path: Path, run_id: str) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if any(path.iterdir()):
            raise ValueError(f"Workspace assets for run {run_id!r} are already populated")

    def _copy_tree_preserving_symlinks(
        self,
        source: Path,
        destination: Path,
        *,
        dirs_exist_ok: bool = False,
    ) -> None:
        self._validate_symlinks_within_source(source)
        shutil.copytree(
            source,
            destination,
            dirs_exist_ok=dirs_exist_ok,
            symlinks=True,
            ignore_dangling_symlinks=True,
        )

    def _validate_symlinks_within_source(self, source: Path) -> None:
        source_root = source.resolve()
        for candidate in source_root.rglob("*"):
            if not candidate.is_symlink():
                continue
            try:
                target = candidate.resolve(strict=False)
                target.relative_to(source_root)
            except (OSError, RuntimeError, ValueError) as exc:
                raise ValueError(
                    f"Symlink {candidate} resolves outside source tree {source_root}"
                ) from exc

    def _teardown_isolation(self, run: RunMetadata) -> None:
        workspace = Path(run.workspace_path).expanduser().resolve()
        if run.isolation_mode == IsolationMode.WORKTREE:
            base_repo_path = run.metadata.get("base_repo_path")
            if base_repo_path:
                self.git_tool.remove_worktree(base_repo_path, str(workspace), force=True)
            if workspace.exists():
                shutil.rmtree(workspace, ignore_errors=True)
            return

        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)

    def _quarantine_worktree_repository(
        self,
        run: RunMetadata,
        workspace: Path,
        destination: Path,
    ) -> None:
        base_repo_path = run.metadata.get("base_repo_path")
        branch_name = run.metadata.get("isolation_branch")
        if not base_repo_path or not branch_name:
            shutil.copytree(workspace, destination)
            return

        base_repo = Path(base_repo_path).expanduser().resolve()
        if not base_repo.exists():
            shutil.copytree(workspace, destination)
            return

        self._clone_standalone_repository(base_repo, destination, branch_name)
        self._replace_repository_working_tree(destination, workspace)
        self._copy_worktree_git_state(workspace, destination)

    def _clone_standalone_repository(
        self,
        source_repo: Path,
        destination: Path,
        branch_name: str,
    ) -> None:
        completed = subprocess.run(
            [
                "git",
                "clone",
                "--no-hardlinks",
                "--branch",
                branch_name,
                str(source_repo),
                str(destination),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            error = completed.stderr.strip() or completed.stdout.strip() or "git clone failed"
            raise RuntimeError(f"Failed to create quarantined repository snapshot: {error}")

    def _replace_repository_working_tree(self, destination: Path, source_workspace: Path) -> None:
        self._validate_symlinks_within_source(source_workspace)

        for child in destination.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

        for child in source_workspace.iterdir():
            if child.name == ".git":
                continue
            target = destination / child.name
            self._copy_path_preserving_symlinks(child, target)

    def _copy_path_preserving_symlinks(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            shutil.copy2(source, destination, follow_symlinks=False)
            return
        if source.is_dir():
            shutil.copytree(
                source,
                destination,
                symlinks=True,
                ignore_dangling_symlinks=True,
            )
            return
        shutil.copy2(source, destination, follow_symlinks=False)

    def _copy_worktree_git_state(self, source_workspace: Path, destination: Path) -> None:
        source_git_dir = self._resolve_worktree_git_dir(source_workspace)
        if source_git_dir is None:
            return

        destination_git_dir = destination / ".git"
        for file_name in [
            "index",
            "HEAD",
            "MERGE_HEAD",
            "CHERRY_PICK_HEAD",
            "REVERT_HEAD",
            "ORIG_HEAD",
            "MERGE_MSG",
            "MERGE_MODE",
            "AUTO_MERGE",
        ]:
            source_file = source_git_dir / file_name
            if source_file.exists():
                shutil.copy2(source_file, destination_git_dir / file_name)

        for directory_name in ["rebase-apply", "rebase-merge", "sequencer"]:
            source_directory = source_git_dir / directory_name
            destination_directory = destination_git_dir / directory_name
            if source_directory.exists():
                if destination_directory.exists():
                    shutil.rmtree(destination_directory)
                shutil.copytree(source_directory, destination_directory)

    def _resolve_worktree_git_dir(self, workspace: Path) -> Optional[Path]:
        git_path = workspace / ".git"
        if git_path.is_dir():
            return git_path
        if not git_path.is_file():
            return None

        content = git_path.read_text(encoding="utf-8").strip()
        prefix = "gitdir:"
        if not content.startswith(prefix):
            return None

        git_dir = content[len(prefix) :].strip()
        resolved = Path(git_dir)
        if not resolved.is_absolute():
            resolved = (workspace / resolved).resolve()
        return resolved

    def _run_git_command(self, workspace: Path, args: list[str]) -> tuple[bool, str, Optional[str]]:
        git_path = workspace / ".git"
        if not git_path.exists():
            error = f"Workspace {workspace} is not a git repository"
            logger.warning("Skipping git command %s: %s", args, error)
            return False, "", error

        try:
            completed = subprocess.run(
                ["git", "-C", str(workspace), *args],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            error = "git executable is not available"
            logger.exception("Failed to run git command %s in %s", args, workspace)
            return False, "", error

        if completed.returncode != 0:
            error = completed.stderr.strip() or completed.stdout.strip() or "git command failed"
            logger.warning(
                "Git command failed in %s: git %s (%s)",
                workspace,
                " ".join(args),
                error,
            )
            return False, completed.stdout, error
        return True, completed.stdout, None

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        content = f"{json.dumps(payload, indent=2, sort_keys=True)}\n"
        self._atomic_write_text(path, content)

    def _write_text(self, path: Path, content: str) -> None:
        if content and not content.endswith("\n"):
            content = f"{content}\n"
        self._atomic_write_text(path, content)

    def _atomic_write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path_str = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temp_path = Path(temp_path_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
