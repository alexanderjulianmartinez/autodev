"""Workspace management for run-local execution, snapshots, and diff capture."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from autodev.core.schemas import IsolationMode, RunMetadata, RunStatus, utc_now
from autodev.core.state_store import FileStateStore
from autodev.github.repo_cloner import RepoCloner
from autodev.tools.git_tool import GitTool


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

        shutil.copytree(source, workspace, dirs_exist_ok=True)
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
        shutil.copytree(workspace, destination)
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

        destination = self.snapshots_dir(run_id) / label / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, destination)
        return destination

    def capture_implementation_artifacts(self, run_id: str) -> dict[str, Path]:
        diff_path = self.capture_diff(run_id)
        changed_files_path = self.save_changed_files_summary(run_id)
        self._update_run_metadata(
            run_id,
            {
                "implementation_diff_path": str(diff_path),
                "changed_files_path": str(changed_files_path),
                "last_artifact_capture_at": utc_now().isoformat(),
            },
        )
        return {"diff": diff_path, "changed_files": changed_files_path}

    def capture_diff(self, run_id: str) -> Path:
        workspace = self.workspace_dir(run_id)
        diff_text = self._run_git_command(workspace, ["diff", "--no-color", "--binary"])
        path = self.artifacts_dir(run_id) / "working_tree.diff"
        self._write_text(path, diff_text)
        return path

    def save_changed_files_summary(self, run_id: str) -> Path:
        workspace = self.workspace_dir(run_id)
        status_output = self._run_git_command(workspace, ["status", "--short"])
        files = []
        for line in status_output.splitlines():
            if not line.strip():
                continue
            status = line[:2].strip()
            path = line[3:].strip()
            files.append({"path": path, "status": status})

        payload = {"generated_at": utc_now().isoformat(), "files": files}
        path = self.artifacts_dir(run_id) / "changed_files.json"
        self._write_json(path, payload)
        return path

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

    def _ensure_empty_directory(self, path: Path, run_id: str) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if any(path.iterdir()):
            raise ValueError(f"Workspace assets for run {run_id!r} are already populated")

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

    def _run_git_command(self, workspace: Path, args: list[str]) -> str:
        if not (workspace / ".git").exists():
            return ""

        completed = subprocess.run(
            ["git", "-C", str(workspace), *args],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            return ""
        return completed.stdout

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{json.dumps(payload, indent=2, sort_keys=True)}\n", encoding="utf-8")

    def _write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if content and not content.endswith("\n"):
            content = f"{content}\n"
        path.write_text(content, encoding="utf-8")
