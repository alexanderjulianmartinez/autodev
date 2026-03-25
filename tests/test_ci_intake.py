"""Tests for CIRunReader and CIIntakeService."""

from __future__ import annotations

import pytest

from autodev.core.backlog_service import BacklogService
from autodev.core.schemas import PriorityLevel
from autodev.core.state_store import FileStateStore
from autodev.github.ci_intake import (
    CIIntakeService,
    _build_acceptance_criteria,
    _build_description,
    _derive_item_id,
    _map_priority,
)
from autodev.github.ci_runner import CIRunData, CIRunReader, _infer_command

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_RUN_URL = "https://github.com/octocat/Hello-World/actions/runs/999"


def _stub_run(**kwargs) -> CIRunData:
    defaults = dict(
        run_id=999,
        run_number=42,
        run_url=_VALID_RUN_URL,
        workflow_name="CI",
        branch="main",
        conclusion="failure",
        repo_full_name="octocat/Hello-World",
        failing_jobs=[
            {
                "name": "test",
                "conclusion": "failure",
                "failing_steps": [{"name": "Run pytest", "conclusion": "failure"}],
            }
        ],
        validation_commands=["pytest"],
    )
    defaults.update(kwargs)
    return CIRunData(**defaults)


def _make_service(tmp_path, stub_run=None) -> CIIntakeService:
    store = FileStateStore(str(tmp_path))
    svc = BacklogService(store)
    reader = CIRunReader()
    if stub_run is not None:
        reader.read = lambda _url: stub_run  # type: ignore[method-assign]
    return CIIntakeService(svc, reader)


# ---------------------------------------------------------------------------
# CIRunReader.parse_url
# ---------------------------------------------------------------------------


class TestCIRunReaderParseUrl:
    def test_valid_url_returns_owner_repo_run_id(self):
        owner, repo, run_id = CIRunReader.parse_url(_VALID_RUN_URL)
        assert owner == "octocat"
        assert repo == "Hello-World"
        assert run_id == 999

    def test_valid_url_with_trailing_slash(self):
        owner, repo, run_id = CIRunReader.parse_url(_VALID_RUN_URL + "/")
        assert run_id == 999

    def test_invalid_url_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid GitHub Actions run URL"):
            CIRunReader.parse_url("https://github.com/octocat/Hello-World/issues/1")

    def test_non_url_raises_value_error(self):
        with pytest.raises(ValueError):
            CIRunReader.parse_url("not-a-url")

    def test_missing_token_raises_environment_error(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        reader = CIRunReader()
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            reader.read(_VALID_RUN_URL)


# ---------------------------------------------------------------------------
# _infer_command
# ---------------------------------------------------------------------------


class TestInferCommand:
    def test_pytest_step(self):
        assert _infer_command("Run pytest") == "pytest"

    def test_run_tests_step(self):
        assert _infer_command("Run tests") == "pytest"

    def test_ruff_step(self):
        assert _infer_command("Run ruff") == "ruff check ."

    def test_lint_step(self):
        assert _infer_command("Lint code") == "ruff check ."

    def test_mypy_step(self):
        assert _infer_command("Run mypy") == "mypy ."

    def test_type_check_step(self):
        assert _infer_command("Type check") == "mypy ."

    def test_unknown_step_returns_none(self):
        assert _infer_command("Deploy to staging") is None

    def test_coverage_step(self):
        assert _infer_command("Run coverage") == "pytest --cov"

    def test_case_insensitive(self):
        assert _infer_command("RUN PYTEST") == "pytest"


# ---------------------------------------------------------------------------
# _map_priority
# ---------------------------------------------------------------------------


class TestMapPriority:
    def test_main_branch_is_critical(self):
        assert _map_priority("main") == PriorityLevel.CRITICAL

    def test_master_branch_is_critical(self):
        assert _map_priority("master") == PriorityLevel.CRITICAL

    def test_feature_branch_is_high(self):
        assert _map_priority("feature/my-feature") == PriorityLevel.HIGH

    def test_empty_branch_is_high(self):
        assert _map_priority("") == PriorityLevel.HIGH


# ---------------------------------------------------------------------------
# _derive_item_id
# ---------------------------------------------------------------------------


class TestDeriveItemId:
    def test_standard_case(self):
        assert _derive_item_id("octocat", "Hello-World", 999) == "ci-octocat-hello-world-999"

    def test_special_chars_slugified(self):
        item_id = _derive_item_id("my-org", "my.repo", 1)
        assert item_id.startswith("ci-")
        assert "1" in item_id


# ---------------------------------------------------------------------------
# _build_acceptance_criteria
# ---------------------------------------------------------------------------


class TestBuildAcceptanceCriteria:
    def test_failing_steps_become_criteria(self):
        run = _stub_run()
        criteria = _build_acceptance_criteria(run)
        assert "Fix failing step: Run pytest" in criteria

    def test_deduplicates_same_step_across_jobs(self):
        run = _stub_run(
            failing_jobs=[
                {
                    "name": "job-a",
                    "conclusion": "failure",
                    "failing_steps": [{"name": "Run pytest", "conclusion": "failure"}],
                },
                {
                    "name": "job-b",
                    "conclusion": "failure",
                    "failing_steps": [{"name": "Run pytest", "conclusion": "failure"}],
                },
            ]
        )
        criteria = _build_acceptance_criteria(run)
        assert criteria.count("Fix failing step: Run pytest") == 1

    def test_no_failing_steps_uses_fallback(self):
        run = _stub_run(
            failing_jobs=[{"name": "test", "conclusion": "failure", "failing_steps": []}]
        )
        criteria = _build_acceptance_criteria(run)
        assert len(criteria) == 1
        assert "CI" in criteria[0]


# ---------------------------------------------------------------------------
# CIIntakeService.intake — happy path
# ---------------------------------------------------------------------------


class TestCIIntakeServiceIntake:
    def test_creates_backlog_item_with_correct_id(self, tmp_path):
        svc = _make_service(tmp_path, _stub_run())
        item = svc.intake(_VALID_RUN_URL)
        assert item.item_id == "ci-octocat-hello-world-999"

    def test_source_is_github_actions(self, tmp_path):
        svc = _make_service(tmp_path, _stub_run())
        item = svc.intake(_VALID_RUN_URL)
        assert item.source == "github_actions"

    def test_title_format(self, tmp_path):
        svc = _make_service(tmp_path, _stub_run())
        item = svc.intake(_VALID_RUN_URL)
        assert item.title == "CI Fix: CI failed on run #42 (main)"

    def test_main_branch_priority_is_critical(self, tmp_path):
        svc = _make_service(tmp_path, _stub_run(branch="main"))
        item = svc.intake(_VALID_RUN_URL)
        assert item.priority == PriorityLevel.CRITICAL

    def test_feature_branch_priority_is_high(self, tmp_path):
        svc = _make_service(tmp_path, _stub_run(branch="feature-x"))
        item = svc.intake(_VALID_RUN_URL)
        assert item.priority == PriorityLevel.HIGH

    def test_labels(self, tmp_path):
        svc = _make_service(tmp_path, _stub_run())
        item = svc.intake(_VALID_RUN_URL)
        assert "source:github-actions" in item.labels
        assert "type:ci-fix" in item.labels

    def test_acceptance_criteria_from_failing_steps(self, tmp_path):
        svc = _make_service(tmp_path, _stub_run())
        item = svc.intake(_VALID_RUN_URL)
        assert "Fix failing step: Run pytest" in item.acceptance_criteria

    def test_metadata_contains_run_url(self, tmp_path):
        svc = _make_service(tmp_path, _stub_run())
        item = svc.intake(_VALID_RUN_URL)
        assert item.metadata["run_url"] == _VALID_RUN_URL

    def test_metadata_contains_repo_full_name(self, tmp_path):
        svc = _make_service(tmp_path, _stub_run())
        item = svc.intake(_VALID_RUN_URL)
        assert item.metadata["repo_full_name"] == "octocat/Hello-World"

    def test_metadata_contains_validation_commands(self, tmp_path):
        svc = _make_service(tmp_path, _stub_run())
        item = svc.intake(_VALID_RUN_URL)
        assert item.metadata["validation_commands"] == ["pytest"]

    def test_metadata_contains_failing_jobs(self, tmp_path):
        svc = _make_service(tmp_path, _stub_run())
        item = svc.intake(_VALID_RUN_URL)
        assert len(item.metadata["failing_jobs"]) == 1
        assert item.metadata["failing_jobs"][0]["name"] == "test"

    def test_intake_is_idempotent(self, tmp_path):
        svc = _make_service(tmp_path, _stub_run())
        item1 = svc.intake(_VALID_RUN_URL)
        item2 = svc.intake(_VALID_RUN_URL)
        assert item1.item_id == item2.item_id

    def test_description_contains_workflow_name(self, tmp_path):
        svc = _make_service(tmp_path, _stub_run(workflow_name="My Workflow"))
        item = svc.intake(_VALID_RUN_URL)
        assert "My Workflow" in item.description

    def test_description_contains_failing_step(self, tmp_path):
        svc = _make_service(tmp_path, _stub_run())
        item = svc.intake(_VALID_RUN_URL)
        assert "Run pytest" in item.description


# ---------------------------------------------------------------------------
# CIIntakeService.intake — error handling
# ---------------------------------------------------------------------------


class TestCIIntakeServiceErrors:
    def test_invalid_url_raises_value_error(self, tmp_path):
        svc = _make_service(tmp_path)
        with pytest.raises(ValueError, match="Cannot ingest CI run"):
            svc.intake("https://github.com/octocat/Hello-World/issues/1")

    def test_missing_token_propagates_environment_error(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        svc = _make_service(tmp_path)
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            svc.intake(_VALID_RUN_URL)

    def test_fetch_error_is_wrapped_as_runtime_error(self, tmp_path):
        store = FileStateStore(str(tmp_path))
        backlog_svc = BacklogService(store)
        reader = CIRunReader()

        def _raise(_url: str) -> CIRunData:
            raise RuntimeError("unexpected API error")

        reader.read = _raise  # type: ignore[method-assign]
        svc = CIIntakeService(backlog_svc, reader)
        with pytest.raises(RuntimeError, match="Could not fetch CI run"):
            svc.intake(_VALID_RUN_URL)
