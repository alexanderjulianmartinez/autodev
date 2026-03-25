"""Tests for RunReporter: per-run artifacts and global history reports."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from autodev.core.run_reporter import (
    FAILURE_HISTORY_REPORT,
    VALIDATION_HISTORY_REPORT,
    RunReporter,
)
from autodev.core.schemas import (
    IsolationMode,
    ReviewDecision,
    ReviewResult,
    RunMetadata,
    RunStatus,
    ValidationCommandResult,
    ValidationResult,
    ValidationStatus,
)
from autodev.core.state_store import FileStateStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path) -> FileStateStore:
    return FileStateStore(str(tmp_path))


def _seed_run(store: FileStateStore, run_id: str = "run-001") -> RunMetadata:
    meta = RunMetadata(
        run_id=run_id,
        backlog_item_id="item-test",
        metadata={"issue_url": "https://github.com/org/repo/issues/1"},
    )
    store.save_run(meta)
    return meta


def _make_reporter(store: FileStateStore) -> RunReporter:
    return RunReporter(store)


# ---------------------------------------------------------------------------
# write() — happy path
# ---------------------------------------------------------------------------


class TestRunReporterWrite:
    def test_returns_summary_json_path(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_run(store, "run-001")
        reporter = _make_reporter(store)

        result = reporter.write(
            "run-001",
            status=RunStatus.COMPLETED,
            stage_outputs={},
            context_metadata={},
            files_modified=[],
        )

        assert result is not None
        assert result.name == "summary.json"
        assert result.exists()

    def test_writes_summary_json_with_required_keys(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_run(store, "run-002")
        reporter = _make_reporter(store)

        path = reporter.write(
            "run-002",
            status=RunStatus.COMPLETED,
            stage_outputs={"plan": {"status": "completed"}},
            context_metadata={"issue_title": "Fix bug"},
            files_modified=["src/foo.py"],
        )

        data = json.loads(path.read_text())
        assert data["run_id"] == "run-002"
        assert data["backlog_item_id"] == "item-test"
        assert data["status"] == "completed"
        assert data["files_modified"] == ["src/foo.py"]
        assert "plan" in data["stages"]

    def test_writes_summary_md_file(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_run(store, "run-003")

        reporter = _make_reporter(store)
        reporter.write(
            "run-003",
            status=RunStatus.COMPLETED,
            stage_outputs={},
            context_metadata={},
            files_modified=[],
        )

        md_path = store.run_dir("run-003") / "summary.md"
        assert md_path.exists()
        content = md_path.read_text()
        assert "run-003" in content
        assert "completed" in content

    def test_returns_none_for_missing_run(self, tmp_path):
        store = _make_store(tmp_path)
        reporter = _make_reporter(store)

        result = reporter.write(
            "no-such-run",
            status=RunStatus.FAILED,
            stage_outputs={},
            context_metadata={},
            files_modified=[],
        )

        assert result is None

    def test_includes_issue_url_and_title(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_run(store, "run-004")
        reporter = _make_reporter(store)

        path = reporter.write(
            "run-004",
            status=RunStatus.COMPLETED,
            stage_outputs={},
            context_metadata={
                "issue_url": "https://github.com/org/repo/issues/42",
                "issue_title": "My issue",
            },
            files_modified=[],
        )

        data = json.loads(path.read_text())
        assert data["issue_url"] == "https://github.com/org/repo/issues/42"
        assert data["issue_title"] == "My issue"


# ---------------------------------------------------------------------------
# Failure summary in JSON
# ---------------------------------------------------------------------------


class TestFailureSummary:
    def test_failures_included_when_status_failed(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_run(store, "run-fail")
        reporter = _make_reporter(store)

        path = reporter.write(
            "run-fail",
            status=RunStatus.FAILED,
            stage_outputs={
                "validate": {
                    "status": "failed",
                    "message": "tests failed",
                    "failure_class": "validation_failure",
                }
            },
            context_metadata={},
            files_modified=[],
        )

        data = json.loads(path.read_text())
        assert "failures" in data
        assert data["failures"][0]["stage"] == "validate"
        assert data["failures"][0]["failure_class"] == "validation_failure"

    def test_failures_omitted_when_all_stages_pass(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_run(store, "run-ok")
        reporter = _make_reporter(store)

        path = reporter.write(
            "run-ok",
            status=RunStatus.COMPLETED,
            stage_outputs={"plan": {"status": "completed"}},
            context_metadata={},
            files_modified=[],
        )

        data = json.loads(path.read_text())
        assert "failures" not in data


# ---------------------------------------------------------------------------
# Validation history
# ---------------------------------------------------------------------------


class TestValidationHistory:
    def _make_validation_result(self, run_id: str) -> ValidationResult:  # noqa: ARG002
        return ValidationResult(
            task_id="task-1",
            status=ValidationStatus.PASSED,
            commands=[
                ValidationCommandResult(
                    command="pytest",
                    exit_code=0,
                    status=ValidationStatus.PASSED,
                )
            ],
        )

    def test_appends_validation_history_entry(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_run(store, "run-v1")
        vr = self._make_validation_result("run-v1")
        store.save_validation_result("run-v1", vr)

        reporter = _make_reporter(store)
        reporter.write(
            "run-v1",
            status=RunStatus.COMPLETED,
            stage_outputs={},
            context_metadata={},
            files_modified=[],
        )

        entries = store.load_report_entries(VALIDATION_HISTORY_REPORT)
        assert len(entries) == 1
        assert entries[0]["run_id"] == "run-v1"
        assert entries[0]["status"] == "passed"
        assert entries[0]["commands_run"] == 1
        assert entries[0]["commands_passed"] == 1

    def test_no_validation_history_when_no_results(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_run(store, "run-novr")
        reporter = _make_reporter(store)

        reporter.write(
            "run-novr",
            status=RunStatus.COMPLETED,
            stage_outputs={},
            context_metadata={},
            files_modified=[],
        )

        entries = store.load_report_entries(VALIDATION_HISTORY_REPORT)
        assert entries == []

    def test_accumulates_across_multiple_runs(self, tmp_path):
        store = _make_store(tmp_path)
        reporter = _make_reporter(store)

        for run_id in ("run-a", "run-b"):
            _seed_run(store, run_id)
            vr = self._make_validation_result(run_id)
            store.save_validation_result(run_id, vr)
            reporter.write(
                run_id,
                status=RunStatus.COMPLETED,
                stage_outputs={},
                context_metadata={},
                files_modified=[],
            )

        entries = store.load_report_entries(VALIDATION_HISTORY_REPORT)
        assert len(entries) == 2
        assert {e["run_id"] for e in entries} == {"run-a", "run-b"}


# ---------------------------------------------------------------------------
# Failure history
# ---------------------------------------------------------------------------


class TestFailureHistory:
    def test_appends_failure_history_on_failed_run(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_run(store, "run-fh")
        reporter = _make_reporter(store)

        reporter.write(
            "run-fh",
            status=RunStatus.FAILED,
            stage_outputs={
                "implement": {
                    "status": "failed",
                    "message": "agent error",
                    "failure_class": "environment_failure",
                }
            },
            context_metadata={},
            files_modified=[],
        )

        entries = store.load_report_entries(FAILURE_HISTORY_REPORT)
        assert len(entries) == 1
        assert entries[0]["stage"] == "implement"
        assert entries[0]["failure_class"] == "environment_failure"

    def test_no_failure_history_on_completed_run(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_run(store, "run-ok2")
        reporter = _make_reporter(store)

        reporter.write(
            "run-ok2",
            status=RunStatus.COMPLETED,
            stage_outputs={"plan": {"status": "completed"}},
            context_metadata={},
            files_modified=[],
        )

        entries = store.load_report_entries(FAILURE_HISTORY_REPORT)
        assert entries == []


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


class TestMarkdownRendering:
    def test_md_contains_stage_entries(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_run(store, "run-md")
        reporter = _make_reporter(store)

        reporter.write(
            "run-md",
            status=RunStatus.COMPLETED,
            stage_outputs={
                "plan": {"status": "completed"},
                "validate": {"status": "failed", "message": "test failure"},
            },
            context_metadata={},
            files_modified=["foo.py"],
        )

        md = (store.run_dir("run-md") / "summary.md").read_text()
        assert "plan" in md
        assert "validate" in md
        assert "foo.py" in md

    def test_md_shows_pr_url(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_run(store, "run-pr")
        reporter = _make_reporter(store)

        reporter.write(
            "run-pr",
            status=RunStatus.COMPLETED,
            stage_outputs={},
            context_metadata={
                "promotion_mode": "pr",
                "pr_url": "https://github.com/org/repo/pull/99",
            },
            files_modified=[],
        )

        md = (store.run_dir("run-pr") / "summary.md").read_text()
        assert "https://github.com/org/repo/pull/99" in md
