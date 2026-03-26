"""End-to-end tests for the Orchestrator pipeline.

These tests exercise the full phase-registry machinery (intake → start_run →
plan → implement → validate → review) by stubbing only the external boundaries:
LLM calls (agent.run) and validation shell commands (TestRunner.run_validation).
All state-store, workspace, scheduler, and RunReporter logic runs for real.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from autodev.agents.base import AgentContext
from autodev.core.phase_registry import PhaseExecutionPayload, PhaseRegistry
from autodev.core.runtime import Orchestrator, PipelineState
from autodev.core.schemas import (
    PhaseName,
    ReviewDecision,
    RunStatus,
    ValidationCommandResult,
    ValidationResult,
    ValidationStatus,
)
from autodev.core.state_store import FileStateStore

# ---------------------------------------------------------------------------
# Shared stubs used across multiple test classes
# ---------------------------------------------------------------------------

_ISSUE_URL = "https://github.com/octocat/Hello-World/issues/7"
_CI_RUN_URL = "https://github.com/octocat/Hello-World/actions/runs/12345"


def _stub_plan(self: Any, task: str, context: AgentContext) -> AgentContext:
    return context.model_copy(update={"plan": ["Step 1: add validation", "Step 2: add tests"]})


def _stub_implement(self: Any, task: str, context: AgentContext) -> AgentContext:
    return context.model_copy(
        update={
            "files_modified": ["src/auth.py"],
            "metadata": {**context.metadata, "implementation_status": "applied"},
        }
    )


def _stub_validate(
    self: Any,
    repo_path: str = ".",
    *,
    task_id: str,
    changed_files: Any = None,
    explicit_commands: Any = None,
    validation_breadth: str = "targeted",
    stop_on_first_failure: bool = True,
) -> ValidationResult:
    return ValidationResult(
        task_id=task_id,
        status=ValidationStatus.PASSED,
        summary="All checks passed.",
        commands=[
            ValidationCommandResult(
                command="pytest -q",
                exit_code=0,
                status=ValidationStatus.PASSED,
                stdout="1 passed",
                stderr="",
            )
        ],
    )


def _stub_review_approved(self: Any, task: str, context: AgentContext) -> AgentContext:
    return context.model_copy(
        update={
            "metadata": {
                **context.metadata,
                "review_decision": ReviewDecision.APPROVED.value,
                "review_summary": "LGTM",
                "review_blocking_reasons": [],
            }
        }
    )


def _make_orch(tmp_path: Path) -> Orchestrator:
    return Orchestrator(work_dir=str(tmp_path), dry_run=True)


# ---------------------------------------------------------------------------
# PhaseExecutionPayload round-trip tests
# ---------------------------------------------------------------------------


class TestPhaseExecutionPayloadRoundTrip:
    def test_from_context_preserves_all_fields(self):
        ctx = AgentContext(
            issue_url=_ISSUE_URL,
            repo_path="/tmp/repo",
            plan=["Step 1", "Step 2"],
            files_modified=["foo.py", "bar.py"],
            validation_results="PASSED",
            iteration=2,
            metadata={"run_id": "run-123", "custom_key": "value"},
        )
        payload = PhaseExecutionPayload.from_context(PhaseName.PLAN, ctx, task_id="run-123-plan")

        assert payload.phase == PhaseName.PLAN
        assert payload.task_id == "run-123-plan"
        assert payload.issue_url == _ISSUE_URL
        assert payload.repo_path == "/tmp/repo"
        assert payload.plan == ["Step 1", "Step 2"]
        assert payload.files_modified == ["foo.py", "bar.py"]
        assert payload.validation_results == "PASSED"
        assert payload.iteration == 2
        assert payload.metadata["run_id"] == "run-123"
        assert payload.metadata["custom_key"] == "value"

    def test_to_context_round_trips_all_fields(self):
        ctx = AgentContext(
            issue_url=_ISSUE_URL,
            repo_path="/tmp/repo",
            plan=["Step 1"],
            files_modified=["baz.py"],
            validation_results="FAILED",
            iteration=1,
            metadata={"key": "val"},
        )
        payload = PhaseExecutionPayload.from_context(PhaseName.VALIDATE, ctx, task_id="t1")
        recovered = payload.to_context()

        assert recovered.issue_url == ctx.issue_url
        assert recovered.repo_path == ctx.repo_path
        assert recovered.plan == ctx.plan
        assert recovered.files_modified == ctx.files_modified
        assert recovered.validation_results == ctx.validation_results
        assert recovered.iteration == ctx.iteration
        assert recovered.metadata == ctx.metadata

    def test_from_context_makes_defensive_copies(self):
        """Mutations to the original context must not affect the payload."""
        original_plan = ["Step 1"]
        ctx = AgentContext(issue_url=_ISSUE_URL, plan=original_plan)
        payload = PhaseExecutionPayload.from_context(PhaseName.PLAN, ctx, task_id="t1")
        original_plan.append("Step 2")
        assert len(payload.plan) == 1

    def test_from_context_metadata_is_independent_copy(self):
        meta = {"key": "original"}
        ctx = AgentContext(issue_url=_ISSUE_URL, metadata=meta)
        payload = PhaseExecutionPayload.from_context(PhaseName.PLAN, ctx, task_id="t1")
        meta["key"] = "mutated"
        assert payload.metadata["key"] == "original"


# ---------------------------------------------------------------------------
# PhaseRegistry error handling
# ---------------------------------------------------------------------------


class TestPhaseRegistryErrorHandling:
    def test_get_raises_for_unregistered_phase(self):
        registry = PhaseRegistry()
        with pytest.raises(KeyError, match="No handler registered"):
            registry.get(PhaseName.PLAN)

    def test_execute_propagates_handler_exception(self):
        registry = PhaseRegistry()

        class BoomHandler:
            def execute(self, payload: PhaseExecutionPayload):
                raise RuntimeError("handler exploded")

        registry.register(PhaseName.PLAN, BoomHandler())
        with pytest.raises(RuntimeError, match="handler exploded"):
            registry.execute(PhaseExecutionPayload(phase=PhaseName.PLAN, task_id="t1"))

    def test_execute_missing_phase_raises_key_error(self):
        registry = PhaseRegistry()
        with pytest.raises(KeyError):
            registry.execute(PhaseExecutionPayload(phase=PhaseName.PLAN, task_id="t1"))


# ---------------------------------------------------------------------------
# End-to-end run_pipeline (real phase machinery, stubbed boundaries)
# ---------------------------------------------------------------------------


class TestRunPipelineE2E:
    """Full pipeline: real phase-registry handlers, stubbed LLM+validation."""

    def _setup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Orchestrator:
        orch = _make_orch(tmp_path)
        # Stub only external boundaries
        monkeypatch.setattr("autodev.agents.planner.PlannerAgent.run", _stub_plan)
        monkeypatch.setattr("autodev.agents.coder.CoderAgent.run", _stub_implement)
        monkeypatch.setattr("autodev.tools.test_runner.TestRunner.run_validation", _stub_validate)
        monkeypatch.setattr("autodev.agents.reviewer.ReviewerAgent.run", _stub_review_approved)
        # Stub issue intake so we don't need a real GitHub token
        monkeypatch.setattr(orch, "_read_issue", lambda ctx: ctx)
        return orch

    def test_pipeline_reaches_completed_state(self, tmp_path, monkeypatch):
        orch = self._setup(tmp_path, monkeypatch)
        orch.run_pipeline(_ISSUE_URL)
        assert orch.state == PipelineState.COMPLETED

    def test_pipeline_populates_all_stage_outputs(self, tmp_path, monkeypatch):
        orch = self._setup(tmp_path, monkeypatch)
        orch.run_pipeline(_ISSUE_URL)

        assert orch.stage_outputs["intake"]["status"] == "completed"
        assert orch.stage_outputs["plan"]["status"] == "completed"
        assert orch.stage_outputs["implement"]["status"] == "completed"
        assert orch.stage_outputs["validate"]["status"] == "completed"
        assert orch.stage_outputs["review"]["status"] == "completed"

    def test_pipeline_persists_run_as_completed(self, tmp_path, monkeypatch):
        orch = self._setup(tmp_path, monkeypatch)
        ctx = orch.run_pipeline(_ISSUE_URL)

        run_id = ctx.metadata.get("run_id")
        assert run_id is not None
        run = orch.state_store.load_run(run_id)
        assert run.status == RunStatus.COMPLETED

    def test_pipeline_writes_summary_json(self, tmp_path, monkeypatch):
        orch = self._setup(tmp_path, monkeypatch)
        ctx = orch.run_pipeline(_ISSUE_URL)

        run_id = ctx.metadata["run_id"]
        summary_path = orch.state_store.run_dir(run_id) / "summary.json"
        assert summary_path.exists()
        data = json.loads(summary_path.read_text())
        assert data["status"] == "completed"
        assert "plan" in data["stages"]
        assert "validate" in data["stages"]
        assert "review" in data["stages"]

    def test_pipeline_plan_steps_flow_to_implement(self, tmp_path, monkeypatch):
        orch = self._setup(tmp_path, monkeypatch)
        ctx = orch.run_pipeline(_ISSUE_URL)
        # The plan produced by the stub must survive through to the final context
        assert "Step 1: add validation" in ctx.plan

    def test_pipeline_files_modified_from_implement(self, tmp_path, monkeypatch):
        orch = self._setup(tmp_path, monkeypatch)
        ctx = orch.run_pipeline(_ISSUE_URL)
        assert "src/auth.py" in ctx.files_modified

    def test_pipeline_validation_result_persisted(self, tmp_path, monkeypatch):
        orch = self._setup(tmp_path, monkeypatch)
        ctx = orch.run_pipeline(_ISSUE_URL)

        run_id = ctx.metadata["run_id"]
        results = orch.state_store.list_validation_results(run_id)
        assert len(results) >= 1
        assert results[0].status == ValidationStatus.PASSED

    def test_pipeline_review_decision_approved(self, tmp_path, monkeypatch):
        orch = self._setup(tmp_path, monkeypatch)
        ctx = orch.run_pipeline(_ISSUE_URL)
        assert ctx.metadata.get("review_decision") == ReviewDecision.APPROVED.value

    def test_pipeline_dry_run_skips_pr_creation(self, tmp_path, monkeypatch):
        orch = self._setup(tmp_path, monkeypatch)
        ctx = orch.run_pipeline(_ISSUE_URL)
        # dry_run=True means promotion is skipped
        assert ctx.metadata.get("pr_url") is None
        promote_stage = orch.stage_outputs.get("promote", {})
        assert promote_stage.get("status") in ("skipped", "blocked", None)

    def test_pipeline_failed_run_persisted_as_failed(self, tmp_path, monkeypatch):
        orch = _make_orch(tmp_path)
        monkeypatch.setattr(orch, "_read_issue", lambda ctx: ctx)

        def boom_plan(self, task, context):
            raise RuntimeError("LLM unavailable")

        monkeypatch.setattr("autodev.agents.planner.PlannerAgent.run", boom_plan)

        with pytest.raises(RuntimeError, match="LLM unavailable"):
            orch.run_pipeline(_ISSUE_URL)

        assert orch.state == PipelineState.FAILED


# ---------------------------------------------------------------------------
# run_ci_pipeline E2E
# ---------------------------------------------------------------------------


class TestRunCIPipelineE2E:
    """CI fix pipeline: same machinery, CI intake stub instead of issue intake."""

    def _setup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Orchestrator:
        orch = _make_orch(tmp_path)
        monkeypatch.setattr("autodev.agents.planner.PlannerAgent.run", _stub_plan)
        monkeypatch.setattr("autodev.agents.coder.CoderAgent.run", _stub_implement)
        monkeypatch.setattr("autodev.tools.test_runner.TestRunner.run_validation", _stub_validate)
        monkeypatch.setattr("autodev.agents.reviewer.ReviewerAgent.run", _stub_review_approved)

        # Stub CI intake: inject metadata without hitting GitHub
        def _fake_read_ci_run(ctx: AgentContext) -> AgentContext:
            meta = dict(ctx.metadata)
            meta["backlog_item_id"] = "ci-octocat-hello-world-12345"
            meta["issue_title"] = "CI Fix: CI failed on run #12345 (main)"
            meta["issue_body"] = "Failing step: Run pytest"
            meta["repo_full_name"] = "octocat/Hello-World"
            meta["run_url"] = _CI_RUN_URL
            meta["validation_commands"] = ["pytest"]
            return ctx.model_copy(update={"metadata": meta})

        monkeypatch.setattr(orch, "_read_ci_run", _fake_read_ci_run)
        return orch

    def test_ci_pipeline_reaches_completed_state(self, tmp_path, monkeypatch):
        orch = self._setup(tmp_path, monkeypatch)
        orch.run_ci_pipeline(_CI_RUN_URL)
        assert orch.state == PipelineState.COMPLETED

    def test_ci_pipeline_populates_all_stage_outputs(self, tmp_path, monkeypatch):
        orch = self._setup(tmp_path, monkeypatch)
        orch.run_ci_pipeline(_CI_RUN_URL)

        assert orch.stage_outputs["intake"]["status"] == "completed"
        assert orch.stage_outputs["plan"]["status"] == "completed"
        assert orch.stage_outputs["validate"]["status"] == "completed"
        assert orch.stage_outputs["review"]["status"] == "completed"

    def test_ci_pipeline_persists_run_with_ci_backlog_item(self, tmp_path, monkeypatch):
        orch = self._setup(tmp_path, monkeypatch)
        ctx = orch.run_ci_pipeline(_CI_RUN_URL)

        run_id = ctx.metadata.get("run_id")
        assert run_id is not None
        run = orch.state_store.load_run(run_id)
        assert run.status == RunStatus.COMPLETED
        # backlog_item_id reflects CI origin
        assert run.backlog_item_id == "ci-octocat-hello-world-12345"

    def test_ci_pipeline_carries_validation_commands_in_context(self, tmp_path, monkeypatch):
        orch = self._setup(tmp_path, monkeypatch)
        ctx = orch.run_ci_pipeline(_CI_RUN_URL)
        assert ctx.metadata.get("validation_commands") == ["pytest"]

    def test_ci_pipeline_writes_summary_json(self, tmp_path, monkeypatch):
        orch = self._setup(tmp_path, monkeypatch)
        ctx = orch.run_ci_pipeline(_CI_RUN_URL)

        run_id = ctx.metadata["run_id"]
        summary_path = orch.state_store.run_dir(run_id) / "summary.json"
        assert summary_path.exists()
        data = json.loads(summary_path.read_text())
        assert data["status"] == "completed"


# ---------------------------------------------------------------------------
# resume_pipeline
# ---------------------------------------------------------------------------


class TestResumePipeline:
    def _seed_run(self, tmp_path: Path, issue_url: str = _ISSUE_URL) -> tuple[str, str]:
        """Create a minimal persisted run and return (work_dir, run_id)."""
        from autodev.core.schemas import RunMetadata

        state_path = str(tmp_path / "state")
        store = FileStateStore(state_path)
        run = RunMetadata(
            run_id="run-resume-001",
            backlog_item_id="issue-7",
            metadata={"issue_url": issue_url},
        )
        store.save_run(run)
        return str(tmp_path), "run-resume-001"

    def test_resume_executes_pipeline_successfully(self, tmp_path, monkeypatch):
        work_dir, run_id = self._seed_run(tmp_path)
        orch = Orchestrator(work_dir=work_dir, dry_run=True)

        monkeypatch.setattr("autodev.agents.planner.PlannerAgent.run", _stub_plan)
        monkeypatch.setattr("autodev.agents.coder.CoderAgent.run", _stub_implement)
        monkeypatch.setattr("autodev.tools.test_runner.TestRunner.run_validation", _stub_validate)
        monkeypatch.setattr("autodev.agents.reviewer.ReviewerAgent.run", _stub_review_approved)
        monkeypatch.setattr(orch, "_read_issue", lambda ctx: ctx)

        ctx = orch.resume_pipeline(run_id)
        assert orch.state == PipelineState.COMPLETED
        assert ctx.metadata.get("run_id") is not None

    def test_resume_raises_for_missing_run(self, tmp_path):
        orch = _make_orch(tmp_path)
        with pytest.raises(FileNotFoundError):
            orch.resume_pipeline("no-such-run")

    def test_resume_raises_for_run_without_issue_url(self, tmp_path):
        from autodev.core.schemas import RunMetadata

        store = FileStateStore(str(tmp_path / "state"))
        run = RunMetadata(run_id="empty-run", backlog_item_id="item-x", metadata={})
        store.save_run(run)

        orch = Orchestrator(work_dir=str(tmp_path), dry_run=True)
        with pytest.raises(ValueError, match="issue_url"):
            orch.resume_pipeline("empty-run")


# ---------------------------------------------------------------------------
# Stage output shape contract
# ---------------------------------------------------------------------------


class TestStageOutputContract:
    """Verify the shape of stage_outputs entries for each phase."""

    def _run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Orchestrator:
        orch = _make_orch(tmp_path)
        monkeypatch.setattr("autodev.agents.planner.PlannerAgent.run", _stub_plan)
        monkeypatch.setattr("autodev.agents.coder.CoderAgent.run", _stub_implement)
        monkeypatch.setattr("autodev.tools.test_runner.TestRunner.run_validation", _stub_validate)
        monkeypatch.setattr("autodev.agents.reviewer.ReviewerAgent.run", _stub_review_approved)
        monkeypatch.setattr(orch, "_read_issue", lambda ctx: ctx)
        orch.run_pipeline(_ISSUE_URL)
        return orch

    def test_plan_stage_output_has_metrics(self, tmp_path, monkeypatch):
        orch = self._run(tmp_path, monkeypatch)
        plan_out = orch.stage_outputs["plan"]
        assert "metrics" in plan_out
        assert "plan_steps" in plan_out["metrics"]
        assert plan_out["metrics"]["plan_steps"] == 2

    def test_implement_stage_output_has_files_modified_metric(self, tmp_path, monkeypatch):
        orch = self._run(tmp_path, monkeypatch)
        impl_out = orch.stage_outputs["implement"]
        assert impl_out["metrics"]["files_modified"] == 1

    def test_validate_stage_output_has_status_completed(self, tmp_path, monkeypatch):
        orch = self._run(tmp_path, monkeypatch)
        assert orch.stage_outputs["validate"]["status"] == "completed"

    def test_review_stage_output_has_metrics_with_decision(self, tmp_path, monkeypatch):
        orch = self._run(tmp_path, monkeypatch)
        review_out = orch.stage_outputs["review"]
        assert "metrics" in review_out
        assert review_out["metrics"]["review_decision"] == ReviewDecision.APPROVED.value
