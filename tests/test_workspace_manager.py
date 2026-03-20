"""Tests for dedicated run workspaces and implementation artifacts."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from autodev.core.schemas import IsolationMode, RunStatus
from autodev.core.state_store import FileStateStore
from autodev.core.workspace_manager import WorkspaceManager


def initialize_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "README.md").write_text("# AutoDev\n", encoding="utf-8")

    subprocess.run(["git", "init", str(path)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True, capture_output=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "AutoDev",
        "GIT_AUTHOR_EMAIL": "autodev@example.com",
        "GIT_COMMITTER_NAME": "AutoDev",
        "GIT_COMMITTER_EMAIL": "autodev@example.com",
    }
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "Initial commit"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def git_commit_all(path: Path, message: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "AutoDev",
        "GIT_AUTHOR_EMAIL": "autodev@example.com",
        "GIT_COMMITTER_NAME": "AutoDev",
        "GIT_COMMITTER_EMAIL": "autodev@example.com",
    }
    subprocess.run(["git", "-C", str(path), "add", "--all"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", message],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def test_create_run_persists_dedicated_workspace_record(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)

    run = manager.create_run("AD-009", run_id="run-009")

    assert Path(run.workspace_path) == tmp_path / "state" / "runs" / "run-009" / "workspace"
    assert store.load_run("run-009") == run
    assert manager.snapshots_dir("run-009").exists()
    assert manager.artifacts_dir("run-009").exists()


def test_prepare_local_repository_creates_branch_isolation(tmp_path):
    source_repo = tmp_path / "source-repo"
    initialize_git_repo(source_repo)

    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    run = manager.create_run(
        "AD-010",
        run_id="run-010-branch",
        isolation_mode=IsolationMode.BRANCH,
    )

    workspace = manager.prepare_local_repository(run.run_id, str(source_repo))
    current_branch = subprocess.run(
        ["git", "-C", str(workspace), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    run_copy = store.load_run(run.run_id)

    assert workspace == Path(run.workspace_path)
    assert current_branch == run_copy.metadata["isolation_branch"]


def test_prepare_local_repository_creates_worktree_isolation(tmp_path):
    source_repo = tmp_path / "source-repo"
    initialize_git_repo(source_repo)

    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    run = manager.create_run(
        "AD-010",
        run_id="run-010-worktree",
        isolation_mode=IsolationMode.WORKTREE,
    )

    workspace = manager.prepare_local_repository(run.run_id, str(source_repo))
    gitdir_file = workspace / ".git"
    run_copy = store.load_run(run.run_id)

    assert workspace == Path(run.workspace_path)
    assert gitdir_file.is_file()
    assert Path(run_copy.metadata["base_repo_path"]).exists()
    assert run_copy.metadata["isolation_branch"].startswith("autodev/ad-010-")


def test_snapshot_file_copies_pre_edit_contents(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    run = manager.create_run("AD-009", run_id="run-009")
    target = Path(run.workspace_path) / "src" / "app.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("print('before')\n", encoding="utf-8")

    snapshot = manager.snapshot_file(run.run_id, str(target), label="before-implement")
    target.write_text("print('after')\n", encoding="utf-8")

    assert (
        snapshot
        == tmp_path
        / "state"
        / "runs"
        / "run-009"
        / "snapshots"
        / "before-implement"
        / "src"
        / "app.py"
    )
    assert snapshot.read_text(encoding="utf-8") == "print('before')\n"


def test_snapshot_file_rejects_unsafe_label(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    run = manager.create_run("AD-009", run_id="run-009")
    target = Path(run.workspace_path) / "src" / "app.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("print('before')\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid snapshot label"):
        manager.snapshot_file(run.run_id, str(target), label="../escape")


def test_capture_implementation_artifacts_persists_diff_and_changed_files(tmp_path):
    source_repo = tmp_path / "source-repo"
    initialize_git_repo(source_repo)

    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    run = manager.create_run("AD-009", run_id="run-009")
    workspace = manager.populate_workspace(run.run_id, str(source_repo))

    (workspace / "README.md").write_text("# AutoDev\n\nUpdated.\n", encoding="utf-8")
    (workspace / "notes.txt").write_text("new file\n", encoding="utf-8")

    artifacts = manager.capture_implementation_artifacts(run.run_id)
    changed_files = json.loads(artifacts["changed_files"].read_text(encoding="utf-8"))
    run_copy = store.load_run(run.run_id)
    artifacts_dir = tmp_path / "state" / "runs" / "run-009" / "artifacts"

    assert artifacts["diff"] == artifacts_dir / "working_tree.diff"
    assert artifacts["changed_files"] == artifacts_dir / "changed_files.json"
    assert "README.md" in artifacts["diff"].read_text(encoding="utf-8")
    assert {entry["path"] for entry in changed_files["files"]} == {
        "README.md",
        "notes.txt",
    }
    assert run_copy.metadata["implementation_diff_path"] == str(artifacts["diff"])
    assert run_copy.metadata["changed_files_path"] == str(artifacts["changed_files"])
    assert run_copy.metadata["implementation_artifact_capture"]["success"] is True


def test_capture_implementation_artifacts_tracks_renames_via_porcelain_status(tmp_path):
    source_repo = tmp_path / "source-repo"
    initialize_git_repo(source_repo)
    original = source_repo / "old name.txt"
    original.write_text("before rename\n", encoding="utf-8")
    git_commit_all(source_repo, "Add rename target")

    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    run = manager.create_run("AD-011", run_id="run-011-rename-status")
    workspace = manager.populate_workspace(run.run_id, str(source_repo))

    (workspace / "old name.txt").rename(workspace / "new name.txt")
    subprocess.run(
        ["git", "-C", str(workspace), "add", "--all"],
        check=True,
        capture_output=True,
    )
    artifacts = manager.capture_implementation_artifacts(run.run_id)
    changed_files = json.loads(artifacts["changed_files"].read_text(encoding="utf-8"))

    assert changed_files["success"] is True
    assert changed_files["files"] == [
        {
            "path": "new name.txt",
            "previous_path": "old name.txt",
            "status": "R",
        }
    ]


def test_parse_porcelain_status_uses_destination_as_path_for_rename_records(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)

    parsed = manager._parse_porcelain_status("R  new name.txt\0old name.txt\0")

    assert parsed == [
        {
            "path": "new name.txt",
            "previous_path": "old name.txt",
            "status": "R",
        }
    ]


def test_capture_implementation_artifacts_surfaces_non_git_failure(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    run = manager.create_run("AD-011", run_id="run-011")
    workspace = Path(run.workspace_path)
    (workspace / "README.md").write_text("not a git repo\n", encoding="utf-8")

    artifacts = manager.capture_implementation_artifacts(run.run_id)
    diff_text = artifacts["diff"].read_text(encoding="utf-8")
    changed_files = json.loads(artifacts["changed_files"].read_text(encoding="utf-8"))
    run_copy = store.load_run(run.run_id)

    assert "Artifact capture failed:" in diff_text
    assert changed_files["success"] is False
    assert "not a git repository" in changed_files["error"]
    assert run_copy.metadata["implementation_artifact_capture"]["success"] is False
    assert run_copy.metadata["implementation_artifact_capture"]["errors"]


def test_populate_workspace_preserves_internal_symlinks(tmp_path):
    source = tmp_path / "source"
    source.mkdir(parents=True)
    real_file = source / "README.md"
    real_file.write_text("# AutoDev\n", encoding="utf-8")
    link_path = source / "README.link"
    link_path.symlink_to("README.md")

    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    run = manager.create_run("AD-009", run_id="run-009-symlink")

    workspace = manager.populate_workspace(run.run_id, str(source))
    copied_link = workspace / "README.link"

    assert copied_link.is_symlink()
    assert os.readlink(copied_link) == "README.md"


def test_populate_workspace_rejects_symlink_escaping_source_tree(tmp_path):
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("host data\n", encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir(parents=True)
    (source / "escape.link").symlink_to(outside_file)

    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    run = manager.create_run("AD-009", run_id="run-009-bad-symlink")
    workspace = Path(run.workspace_path)

    with pytest.raises(ValueError, match="resolves outside source tree"):
        manager.populate_workspace(run.run_id, str(source))

    assert not any(workspace.iterdir())


def test_finalize_run_can_quarantine_failure_and_teardown_worktree(tmp_path):
    source_repo = tmp_path / "source-repo"
    initialize_git_repo(source_repo)

    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    run = manager.create_run(
        "AD-010",
        run_id="run-010-failed",
        isolation_mode=IsolationMode.WORKTREE,
    )
    workspace = manager.prepare_local_repository(run.run_id, str(source_repo))
    (workspace / "README.md").write_text("# AutoDev\n\nFailure case\n", encoding="utf-8")

    finalized = manager.finalize_run(
        run.run_id,
        status=RunStatus.FAILED,
        quarantine_on_failure=True,
    )
    quarantined_path = Path(finalized.metadata["quarantined_workspace_path"])

    assert finalized.status == RunStatus.FAILED
    assert finalized.completed_at is not None
    assert quarantined_path.exists()
    assert (quarantined_path / ".git").is_dir()
    assert (quarantined_path / "README.md").read_text(encoding="utf-8").endswith("Failure case\n")
    assert not workspace.exists()

    status_output = subprocess.run(
        ["git", "-C", str(quarantined_path), "status", "--short"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    branch_name = subprocess.run(
        ["git", "-C", str(quarantined_path), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert "README.md" in status_output
    assert branch_name == store.load_run(run.run_id).metadata["isolation_branch"]


def test_quarantine_worktree_preserves_untracked_files_after_teardown(tmp_path):
    source_repo = tmp_path / "source-repo"
    initialize_git_repo(source_repo)

    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    run = manager.create_run(
        "AD-011",
        run_id="run-011-worktree-quarantine",
        isolation_mode=IsolationMode.WORKTREE,
    )
    workspace = manager.prepare_local_repository(run.run_id, str(source_repo))
    (workspace / "notes.txt").write_text("needs inspection\n", encoding="utf-8")

    finalized = manager.finalize_run(
        run.run_id,
        status=RunStatus.FAILED,
        quarantine_on_failure=True,
    )
    quarantined_path = Path(finalized.metadata["quarantined_workspace_path"])

    status_output = subprocess.run(
        ["git", "-C", str(quarantined_path), "status", "--short"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert "notes.txt" in status_output
    assert (quarantined_path / "notes.txt").read_text(encoding="utf-8") == "needs inspection\n"


def test_quarantine_worktree_preserves_internal_symlinks(tmp_path):
    source_repo = tmp_path / "source-repo"
    initialize_git_repo(source_repo)

    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    run = manager.create_run(
        "AD-011",
        run_id="run-011-worktree-symlink",
        isolation_mode=IsolationMode.WORKTREE,
    )
    workspace = manager.prepare_local_repository(run.run_id, str(source_repo))
    (workspace / "notes.txt").write_text("needs inspection\n", encoding="utf-8")
    (workspace / "notes.link").symlink_to("notes.txt")

    quarantined_path = manager.quarantine_run(run.run_id)

    assert (quarantined_path / "notes.link").is_symlink()
    assert os.readlink(quarantined_path / "notes.link") == "notes.txt"


def test_quarantine_worktree_rejects_symlink_escaping_workspace(tmp_path):
    source_repo = tmp_path / "source-repo"
    initialize_git_repo(source_repo)
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("host data\n", encoding="utf-8")

    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    run = manager.create_run(
        "AD-011",
        run_id="run-011-worktree-bad-symlink",
        isolation_mode=IsolationMode.WORKTREE,
    )
    workspace = manager.prepare_local_repository(run.run_id, str(source_repo))
    (workspace / "escape.link").symlink_to(outside_file)
    quarantine_destination = manager.quarantine_dir(run.run_id) / workspace.name

    with pytest.raises(ValueError, match="resolves outside source tree"):
        manager.quarantine_run(run.run_id)

    assert not quarantine_destination.exists()


def test_quarantine_worktree_fallback_preserves_internal_symlinks(tmp_path):
    source_repo = tmp_path / "source-repo"
    initialize_git_repo(source_repo)

    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    run = manager.create_run(
        "AD-011",
        run_id="run-011-worktree-fallback-symlink",
        isolation_mode=IsolationMode.WORKTREE,
    )
    workspace = manager.prepare_local_repository(run.run_id, str(source_repo))
    (workspace / "notes.txt").write_text("needs inspection\n", encoding="utf-8")
    (workspace / "notes.link").symlink_to("notes.txt")
    store.update_run(
        run.run_id,
        lambda current: current.model_copy(
            update={
                "metadata": {k: v for k, v in current.metadata.items() if k != "base_repo_path"}
            }
        ),
    )

    quarantined_path = manager.quarantine_run(run.run_id)

    assert (quarantined_path / "notes.link").is_symlink()
    assert os.readlink(quarantined_path / "notes.link") == "notes.txt"


def test_quarantine_worktree_fallback_rejects_escaping_symlink(tmp_path):
    source_repo = tmp_path / "source-repo"
    initialize_git_repo(source_repo)
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("host data\n", encoding="utf-8")

    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    run = manager.create_run(
        "AD-011",
        run_id="run-011-worktree-fallback-bad-symlink",
        isolation_mode=IsolationMode.WORKTREE,
    )
    workspace = manager.prepare_local_repository(run.run_id, str(source_repo))
    (workspace / "escape.link").symlink_to(outside_file)
    store.update_run(
        run.run_id,
        lambda current: current.model_copy(
            update={
                "metadata": {k: v for k, v in current.metadata.items() if k != "base_repo_path"}
            }
        ),
    )
    quarantine_destination = manager.quarantine_dir(run.run_id) / workspace.name

    with pytest.raises(ValueError, match="resolves outside source tree"):
        manager.quarantine_run(run.run_id)

    assert not quarantine_destination.exists()


def test_replace_repository_working_tree_cleans_destination_directory_symlink(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    source_workspace = tmp_path / "source-workspace"
    source_workspace.mkdir(parents=True)
    (source_workspace / "notes.txt").write_text("updated\n", encoding="utf-8")

    destination = tmp_path / "destination"
    destination.mkdir(parents=True)
    (destination / ".git").mkdir()
    external_dir = tmp_path / "external-dir"
    external_dir.mkdir(parents=True)
    (destination / "linked-dir").symlink_to(external_dir, target_is_directory=True)

    manager._replace_repository_working_tree(destination, source_workspace)

    assert not (destination / "linked-dir").exists()
    assert (destination / "notes.txt").read_text(encoding="utf-8") == "updated\n"


def test_resolve_worktree_git_dir_accepts_expected_base_repo_metadata_root(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    base_repo = tmp_path / "base-repo"
    expected_git_dir = base_repo / ".git" / "worktrees" / "run-1"
    expected_git_dir.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / ".git").write_text(f"gitdir: {expected_git_dir}\n", encoding="utf-8")

    resolved = manager._resolve_worktree_git_dir(workspace, base_repo_path=base_repo)

    assert resolved == expected_git_dir.resolve()


def test_resolve_worktree_git_dir_rejects_pointer_outside_expected_root(tmp_path):
    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    base_repo = tmp_path / "base-repo"
    (base_repo / ".git" / "worktrees").mkdir(parents=True)
    outside_git_dir = tmp_path / "outside-gitdir"
    outside_git_dir.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / ".git").write_text(f"gitdir: {outside_git_dir}\n", encoding="utf-8")

    resolved = manager._resolve_worktree_git_dir(workspace, base_repo_path=base_repo)

    assert resolved is None


def test_quarantine_snapshot_preserves_internal_symlinks(tmp_path):
    source = tmp_path / "source"
    source.mkdir(parents=True)
    (source / "README.md").write_text("# AutoDev\n", encoding="utf-8")
    (source / "README.link").symlink_to("README.md")

    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    run = manager.create_run("AD-011", run_id="run-011-snapshot-quarantine")
    workspace = manager.populate_workspace(run.run_id, str(source))

    quarantined_path = manager.quarantine_run(run.run_id)

    assert quarantined_path == manager.quarantine_dir(run.run_id) / workspace.name
    assert (quarantined_path / "README.link").is_symlink()
    assert os.readlink(quarantined_path / "README.link") == "README.md"


def test_quarantine_snapshot_rejects_symlink_escaping_workspace(tmp_path):
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("host data\n", encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir(parents=True)
    (source / "escape.link").symlink_to(outside_file)

    store = FileStateStore(str(tmp_path / "state"))
    manager = WorkspaceManager(store)
    run = manager.create_run("AD-011", run_id="run-011-snapshot-bad-quarantine")
    workspace = Path(run.workspace_path)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "escape.link").symlink_to(outside_file)
    quarantine_destination = manager.quarantine_dir(run.run_id) / workspace.name

    with pytest.raises(ValueError, match="resolves outside source tree"):
        manager.quarantine_run(run.run_id)

    assert not quarantine_destination.exists()
