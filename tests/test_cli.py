"""Tests for the AutoDev CLI commands."""

from __future__ import annotations

from typer.testing import CliRunner

from autodev.cli.main import app
from autodev.core.backlog_service import BacklogService
from autodev.core.schemas import BacklogStatus, PriorityLevel, RunMetadata, RunStatus
from autodev.core.state_store import FileStateStore

runner = CliRunner()


def _store(tmp_path):
    return FileStateStore(str(tmp_path))


def _svc(tmp_path):
    return BacklogService(_store(tmp_path))


class TestBacklogAdd:
    def test_creates_item_and_prints_id(self, tmp_path):
        result = runner.invoke(
            app, ["backlog", "add", "Fix retry logic", "--work-dir", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "item-fix-retry-logic" in result.output

    def test_accepts_priority_flag(self, tmp_path):
        runner.invoke(
            app,
            [
                "backlog",
                "add",
                "High priority task",
                "--priority",
                "p1",
                "--work-dir",
                str(tmp_path),
            ],
        )
        item = _svc(tmp_path).get_item("item-high-priority-task")
        assert item.priority == PriorityLevel.HIGH

    def test_accepts_labels_and_criteria(self, tmp_path):
        runner.invoke(
            app,
            [
                "backlog",
                "add",
                "Labelled task",
                "--label",
                "type:core",
                "--label",
                "priority:p0",
                "--criterion",
                "step one",
                "--criterion",
                "step two",
                "--work-dir",
                str(tmp_path),
            ],
        )
        item = _svc(tmp_path).get_item("item-labelled-task")
        assert "type:core" in item.labels
        assert "step one" in item.acceptance_criteria

    def test_rejects_unknown_priority(self, tmp_path):
        result = runner.invoke(
            app, ["backlog", "add", "Task", "--priority", "ultra", "--work-dir", str(tmp_path)]
        )
        assert result.exit_code != 0
        assert "Unknown priority" in result.output

    def test_rejects_duplicate_item_id(self, tmp_path):
        runner.invoke(app, ["backlog", "add", "Same title", "--work-dir", str(tmp_path)])
        result = runner.invoke(app, ["backlog", "add", "Same title", "--work-dir", str(tmp_path)])
        assert result.exit_code != 0
        assert "already exists" in result.output


class TestBacklogList:
    def test_lists_all_items(self, tmp_path):
        svc = _svc(tmp_path)
        svc.create_item("item-a", "Alpha")
        svc.create_item("item-b", "Beta")
        result = runner.invoke(app, ["backlog", "list", "--work-dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "item-a" in result.output
        assert "item-b" in result.output

    def test_filters_by_status(self, tmp_path):
        svc = _svc(tmp_path)
        svc.create_item("item-planned", "Planned task")
        svc.create_item("item-active", "Active task")
        svc.update_item("item-active", status=BacklogStatus.ACTIVE)
        result = runner.invoke(
            app, ["backlog", "list", "--status", "active", "--work-dir", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "item-active" in result.output
        assert "item-planned" not in result.output

    def test_rejects_unknown_status(self, tmp_path):
        result = runner.invoke(
            app, ["backlog", "list", "--status", "bogus", "--work-dir", str(tmp_path)]
        )
        assert result.exit_code != 0
        assert "Unknown status" in result.output

    def test_prints_dim_message_when_empty(self, tmp_path):
        result = runner.invoke(app, ["backlog", "list", "--work-dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "No backlog items found" in result.output


class TestRunsShow:
    def _seed_run(self, tmp_path, run_id="run-001", status=RunStatus.COMPLETED):
        store = _store(tmp_path)
        run = RunMetadata(
            run_id=run_id,
            backlog_item_id="item-test",
            status=status,
            metadata={"issue_url": "https://github.com/org/repo/issues/1"},
        )
        store.save_run(run)
        return run

    def test_lists_runs(self, tmp_path):
        self._seed_run(tmp_path, "run-abc")
        result = runner.invoke(app, ["runs", "--work-dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "run-abc" in result.output

    def test_shows_run_details(self, tmp_path):
        self._seed_run(tmp_path, "run-xyz")
        result = runner.invoke(app, ["runs", "run-xyz", "--work-dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "run-xyz" in result.output
        assert "item-test" in result.output
        assert "https://github.com/org/repo/issues/1" in result.output

    def test_exits_nonzero_for_missing_run(self, tmp_path):
        result = runner.invoke(app, ["runs", "no-such-run", "--work-dir", str(tmp_path)])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_prints_dim_message_when_no_runs(self, tmp_path):
        result = runner.invoke(app, ["runs", "--work-dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "No runs found" in result.output


class TestRunResume:
    # The Orchestrator places its state store at {work_dir}/state, so tests
    # that need to pre-seed runs must write there too.
    def _orch_store(self, tmp_path):
        return FileStateStore(str(tmp_path / "state"))

    def test_resume_raises_for_missing_run(self, tmp_path):
        result = runner.invoke(app, ["run", "resume", "no-such-run", "--work-dir", str(tmp_path)])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_resume_raises_for_run_without_issue_url(self, tmp_path):
        store = self._orch_store(tmp_path)
        run = RunMetadata(run_id="empty-run", backlog_item_id="item-x", metadata={})
        store.save_run(run)
        result = runner.invoke(app, ["run", "resume", "empty-run", "--work-dir", str(tmp_path)])
        assert result.exit_code != 0
        assert "Cannot resume" in result.output
