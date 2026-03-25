"""Tests for core components: TaskGraph, Supervisor, unified Orchestrator."""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from autodev.agents.base import AgentContext
from autodev.core.phase_registry import PhaseExecutionPayload, PhaseExecutionResult, PhaseRegistry
from autodev.core.runtime import Orchestrator, PipelineState
from autodev.core.schemas import (
    BacklogItem,
    FailureClass,
    IsolationMode,
    PhaseName,
    ReviewDecision,
    ReviewResult,
    RunStatus,
    TaskRecord,
    TaskStatus,
    ValidationCommandResult,
    ValidationResult,
    ValidationStatus,
)
from autodev.core.supervisor import Supervisor
from autodev.core.task_graph import TaskGraph, TaskNode


class TestTaskGraph:
    def test_add_node(self):
        graph = TaskGraph()
        node = TaskNode(name="plan", agent_type="planner")
        graph.add_node(node)
        assert "plan" in graph.nodes

    def test_add_edge(self):
        graph = TaskGraph()
        graph.add_node(TaskNode(name="a", agent_type="planner"))
        graph.add_node(TaskNode(name="b", agent_type="coder"))
        graph.add_edge("a", "b")
        order = graph.get_execution_order()
        assert order.index("a") < order.index("b")

    def test_get_execution_order_default_pipeline(self):
        graph = TaskGraph.default_pipeline()
        order = graph.get_execution_order()
        assert order == ["plan", "implement", "validate", "review"]

    def test_cycle_detection(self):
        graph = TaskGraph()
        graph.add_node(TaskNode(name="a", agent_type="x"))
        graph.add_node(TaskNode(name="b", agent_type="y"))
        graph.add_edge("a", "b")
        graph.add_edge("b", "a")
        with pytest.raises(ValueError, match="[Cc]ycle"):
            graph.get_execution_order()

    def test_add_edge_unknown_node_raises(self):
        graph = TaskGraph()
        graph.add_node(TaskNode(name="a", agent_type="x"))
        with pytest.raises(ValueError, match="Unknown node"):
            graph.add_edge("a", "nonexistent")


class TestSupervisor:
    def test_safe_command(self):
        sup = Supervisor()
        is_safe, reason = sup.validate_command("echo hello")
        assert is_safe
        assert reason == "ok"

    def test_blocked_rm_rf(self):
        sup = Supervisor()
        is_safe, reason = sup.validate_command("rm -rf /")
        assert not is_safe
        assert "rm -rf /" in reason

    def test_blocked_sudo(self):
        sup = Supervisor()
        is_safe, reason = sup.validate_command("sudo apt-get install vim")
        assert not is_safe

    def test_iteration_limit(self):
        sup = Supervisor(max_iterations=2)
        assert not sup.check_iteration_limit()
        sup.increment()
        sup.increment()
        assert sup.check_iteration_limit()

    def test_reset(self):
        sup = Supervisor(max_iterations=1)
        sup.increment()
        assert sup.check_iteration_limit()
        sup.reset()
        assert not sup.check_iteration_limit()
        assert sup.iteration_count == 0


class TestOrchestrator:
    def test_phase_registry_registers_handlers_for_default_phases(self):
        registry = PhaseRegistry.default()

        assert set(registry.phases) == {
            PhaseName.PLAN,
            PhaseName.IMPLEMENT,
            PhaseName.VALIDATE,
            PhaseName.REVIEW,
            PhaseName.PROMOTE,
        }

    def test_phase_registry_execution_sets_boundary_timestamps(self, monkeypatch):
        registry = PhaseRegistry()
        timestamp_values = iter(
            [
                datetime(2026, 3, 25, 12, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 25, 12, 0, 1, tzinfo=timezone.utc),
            ]
        )

        class TimestampHandler:
            def execute(self, payload: PhaseExecutionPayload) -> PhaseExecutionResult:
                return PhaseExecutionResult(
                    phase=payload.phase,
                    task_id=payload.task_id,
                    status=TaskStatus.COMPLETED,
                    message="ok",
                    context=payload.to_context(),
                    started_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
                    completed_at=datetime(2000, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=1),
                )

        registry.register(PhaseName.PLAN, TimestampHandler())
        monkeypatch.setattr(
            "autodev.core.phase_registry.utc_now",
            lambda: next(timestamp_values),
        )

        result = registry.execute(
            PhaseExecutionPayload(
                phase=PhaseName.PLAN,
                task_id="run-1-plan",
            )
        )

        assert result.started_at == datetime(2026, 3, 25, 12, 0, 0, tzinfo=timezone.utc)
        assert result.completed_at == datetime(2026, 3, 25, 12, 0, 1, tzinfo=timezone.utc)

    def test_plan_phase_can_be_swapped_via_registry(self, tmp_path):
        orch = Orchestrator(work_dir=str(tmp_path))

        class CustomPlanHandler:
            def execute(self, payload: PhaseExecutionPayload) -> PhaseExecutionResult:
                updated = payload.to_context().model_copy(update={"plan": ["1. custom plan"]})
                return PhaseExecutionResult(
                    phase=payload.phase,
                    task_id=payload.task_id,
                    status=TaskStatus.COMPLETED,
                    message="custom planner",
                    artifacts=["plan.md"],
                    metrics={"plan_steps": 1},
                    context=updated,
                )

        orch.register_phase_handler(PhaseName.PLAN, CustomPlanHandler())

        updated = orch._plan(
            AgentContext(issue_url="https://github.com/octocat/Hello-World/issues/12")
        )

        assert updated.plan == ["1. custom plan"]
        assert orch.stage_outputs["plan"] == {
            "status": "completed",
            "message": "custom planner",
            "artifacts": ["plan.md"],
            "metrics": {"plan_steps": 1},
        }

    def test_plan_persists_repository_aware_planning_artifact(self, tmp_path):
        orch = Orchestrator(work_dir=str(tmp_path))
        context = AgentContext(
            issue_url="https://github.com/octocat/Hello-World/issues/15",
            metadata={
                "issue_title": "Add token validation to auth flow",
                "issue_body": (
                    "Acceptance criteria:\n- reject invalid tokens\n- preserve valid sessions\n"
                ),
            },
        )

        started = orch._start_run(context)
        workspace = Path(started.repo_path)
        (workspace / "auth.py").write_text(
            "def validate_token(token):\n    return bool(token)\n",
            encoding="utf-8",
        )
        tests_dir = workspace / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_auth.py").write_text(
            "def test_validate_token():\n    assert True\n",
            encoding="utf-8",
        )

        updated = orch._plan(started)
        artifact_path = Path(updated.metadata["planning_artifact_path"])
        artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        run = orch.state_store.load_run(updated.metadata["run_id"])

        assert artifact_path.exists()
        assert artifact_payload["planning_mode"] == "repository-aware"
        assert any(path.endswith("auth.py") for path in artifact_payload["likely_target_files"])
        assert artifact_payload["acceptance_criteria"] == [
            "reject invalid tokens",
            "preserve valid sessions",
        ]
        assert run.metadata["planning_artifact_path"] == str(artifact_path)
        assert str(artifact_path) in orch.stage_outputs["plan"]["artifacts"]

    def test_implement_uses_diff_output_for_changed_files(self, tmp_path):
        orch = Orchestrator(work_dir=str(tmp_path))
        started = orch._start_run(
            AgentContext(
                issue_url="https://github.com/octocat/Hello-World/issues/16",
                metadata={"issue_title": "Update README implementation note"},
            )
        )
        workspace = Path(started.repo_path)
        readme = workspace / "README.md"

        subprocess.run(["git", "-C", str(workspace), "init"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(workspace), "config", "user.email", "autodev@example.com"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(workspace), "config", "user.name", "AutoDev"],
            check=True,
            capture_output=True,
        )
        readme.write_text("# AutoDev\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(workspace), "add", "README.md"], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(workspace), "commit", "-m", "Initial"],
            check=True,
            capture_output=True,
        )

        implement_context = started.model_copy(
            update={
                "plan": ["1. Update README.md"],
                "files_modified": ["heuristic.py"],
                "metadata": {
                    **started.metadata,
                    "issue_title": "Update README implementation note",
                    "likely_target_files": ["README.md"],
                },
            }
        )

        updated = orch._implement(implement_context)
        changed_files_payload = json.loads(
            Path(updated.metadata["changed_files_path"]).read_text(encoding="utf-8")
        )

        assert updated.files_modified == ["README.md"]
        assert updated.metadata["implementation_change_summary"] == ["README.md"]
        assert changed_files_payload["success"] is True
        assert changed_files_payload["files"] == [{"path": "README.md", "status": "M"}]
        assert "heuristic.py" not in updated.files_modified
        assert (
            str(updated.metadata["implementation_diff_path"])
            in orch.stage_outputs["implement"]["artifacts"]
        )

    def test_validate_uses_orchestrator_work_dir_when_repo_path_is_missing(
        self, tmp_path, monkeypatch
    ):
        orch = Orchestrator(work_dir=str(tmp_path))
        captured: dict[str, str] = {}

        def fake_run_validation(
            self,
            repo_path=".",
            *,
            task_id,
            changed_files=None,
            explicit_commands=None,
            validation_breadth="targeted",
            stop_on_first_failure=True,
        ):
            captured["repo_path"] = repo_path
            captured["task_id"] = task_id
            captured["changed_files"] = list(changed_files or [])
            captured["explicit_commands"] = list(explicit_commands or [])
            captured["validation_breadth"] = validation_breadth
            captured["stop_on_first_failure"] = stop_on_first_failure
            return ValidationResult(
                task_id=task_id,
                status=ValidationStatus.PASSED,
                summary="Validation passed for 1 command(s).",
                commands=[
                    ValidationCommandResult(
                        command="pytest -q",
                        exit_code=0,
                        status=ValidationStatus.PASSED,
                        stdout="ok\n",
                        stderr="",
                        duration_seconds=0.01,
                    )
                ],
                changed_files=[],
                profiles=["python"],
                metadata={
                    "validation_breadth": validation_breadth,
                    "stop_on_first_failure": stop_on_first_failure,
                    "selection_reason": "python default validation was selected.",
                },
            )

        monkeypatch.setattr(
            "autodev.core.phase_registry.TestRunner.run_validation",
            fake_run_validation,
        )

        updated = orch._validate(AgentContext(repo_path=""))

        assert captured["repo_path"] == str(tmp_path)
        assert captured["validation_breadth"] == "targeted"
        assert captured["stop_on_first_failure"] is True
        assert updated.validation_results.startswith("PASSED")

    def test_validate_uses_backlog_explicit_commands_and_persists_result(
        self, tmp_path, monkeypatch
    ):
        orch = Orchestrator(work_dir=str(tmp_path))
        backlog_item = BacklogItem(
            item_id="AD-015-item",
            title="Validate auth change",
            metadata={"validation_commands": ["pytest tests/test_auth.py -q"]},
        )
        orch.state_store.save_backlog_item(backlog_item)
        started = orch._start_run(
            AgentContext(
                issue_url="https://github.com/octocat/Hello-World/issues/18",
                metadata={"backlog_item_id": backlog_item.item_id},
            )
        )
        captured: dict[str, object] = {}

        def fake_run_validation(
            self,
            repo_path=".",
            *,
            task_id,
            changed_files=None,
            explicit_commands=None,
            validation_breadth="targeted",
            stop_on_first_failure=True,
        ):
            captured["repo_path"] = repo_path
            captured["task_id"] = task_id
            captured["changed_files"] = list(changed_files or [])
            captured["explicit_commands"] = list(explicit_commands or [])
            captured["validation_breadth"] = validation_breadth
            captured["stop_on_first_failure"] = stop_on_first_failure
            return ValidationResult(
                task_id=task_id,
                status=ValidationStatus.PASSED,
                summary="Validation passed for 1 command(s).",
                commands=[
                    ValidationCommandResult(
                        command="pytest tests/test_auth.py -q",
                        exit_code=0,
                        status=ValidationStatus.PASSED,
                        stdout="ok\n",
                        stderr="",
                        duration_seconds=0.1,
                    )
                ],
                changed_files=list(changed_files or []),
                profiles=["explicit"],
                metadata={
                    "validation_breadth": validation_breadth,
                    "stop_on_first_failure": stop_on_first_failure,
                    "selection_reason": "Explicit validation commands were provided.",
                },
            )

        monkeypatch.setattr(
            "autodev.core.phase_registry.TestRunner.run_validation",
            fake_run_validation,
        )

        updated = orch._validate(started.model_copy(update={"files_modified": ["auth.py"]}))
        validation_path = Path(updated.metadata["validation_result_path"])
        persisted = orch.state_store.load_validation_result(
            updated.metadata["run_id"],
            f"{updated.metadata['run_id']}-validate",
        )

        assert captured["repo_path"] == started.repo_path
        assert captured["changed_files"] == ["auth.py"]
        assert captured["explicit_commands"] == ["pytest tests/test_auth.py -q"]
        assert captured["validation_breadth"] == "targeted"
        assert captured["stop_on_first_failure"] is True
        assert validation_path.exists()
        assert persisted.status == ValidationStatus.PASSED
        assert persisted.commands[0].command == "pytest tests/test_auth.py -q"
        assert str(validation_path) in orch.stage_outputs["validate"]["artifacts"]
        assert updated.metadata["validation_profiles"] == ["explicit"]

    def test_validate_uses_backlog_validation_policy_and_surfaces_reason(
        self, tmp_path, monkeypatch
    ):
        orch = Orchestrator(work_dir=str(tmp_path))
        backlog_item = BacklogItem(
            item_id="AD-017-item",
            title="Validate with broader fallback",
            metadata={
                "validation_breadth": "broader-fallback",
                "validation_continue_on_error": True,
            },
        )
        orch.state_store.save_backlog_item(backlog_item)
        started = orch._start_run(
            AgentContext(
                issue_url="https://github.com/octocat/Hello-World/issues/23",
                metadata={"backlog_item_id": backlog_item.item_id},
            )
        )
        captured: dict[str, object] = {}

        def fake_run_validation(
            self,
            repo_path=".",
            *,
            task_id,
            changed_files=None,
            explicit_commands=None,
            validation_breadth="targeted",
            stop_on_first_failure=True,
        ):
            captured["validation_breadth"] = validation_breadth
            captured["stop_on_first_failure"] = stop_on_first_failure
            return ValidationResult(
                task_id=task_id,
                status=ValidationStatus.PASSED,
                summary="Validation passed for 2 command(s).",
                commands=[
                    ValidationCommandResult(
                        command="pytest tests/test_auth.py -v",
                        exit_code=0,
                        status=ValidationStatus.PASSED,
                        stdout="ok\n",
                        stderr="",
                        duration_seconds=0.05,
                    ),
                    ValidationCommandResult(
                        command="pytest -q",
                        exit_code=0,
                        status=ValidationStatus.PASSED,
                        stdout="ok\n",
                        stderr="",
                        duration_seconds=0.05,
                    ),
                ],
                changed_files=list(changed_files or []),
                profiles=["changed-file-targeted", "broader-fallback"],
                metadata={
                    "validation_breadth": validation_breadth,
                    "stop_on_first_failure": stop_on_first_failure,
                    "selection_reason": (
                        "Targeted tests were inferred from changed files and broader "
                        "fallback validation was added."
                    ),
                },
            )

        monkeypatch.setattr(
            "autodev.core.phase_registry.TestRunner.run_validation",
            fake_run_validation,
        )

        updated = orch._validate(started.model_copy(update={"files_modified": ["auth.py"]}))

        assert captured["validation_breadth"] == "broader-fallback"
        assert captured["stop_on_first_failure"] is False
        assert updated.metadata["validation_breadth"] == "broader-fallback"
        assert updated.metadata["validation_stop_on_first_failure"] is False
        assert (
            "broader fallback validation was added"
            in updated.metadata["validation_selection_reason"].lower()
        )
        assert "Policy: breadth=broader-fallback, stop_on_first_failure=False" in (
            updated.validation_results
        )

    def test_validate_failure_persists_failure_class_and_blocks_durable_task(
        self, tmp_path, monkeypatch
    ):
        orch = Orchestrator(work_dir=str(tmp_path))
        started = orch._start_run(
            AgentContext(issue_url="https://github.com/octocat/Hello-World/issues/21")
        )
        durable_task = TaskRecord(
            task_id="issue-21__validate",
            backlog_item_id="issue-21",
            phase=PhaseName.VALIDATE,
            max_retries=2,
        )
        orch.state_store.save_task(durable_task)

        def fake_run_validation(
            self,
            repo_path=".",
            *,
            task_id,
            changed_files=None,
            explicit_commands=None,
            validation_breadth="targeted",
            stop_on_first_failure=True,
        ):
            return ValidationResult(
                task_id=task_id,
                status=ValidationStatus.FAILED,
                summary="Validation failed after 1 command(s).",
                commands=[
                    ValidationCommandResult(
                        command="pytest tests/test_auth.py -q",
                        exit_code=1,
                        status=ValidationStatus.FAILED,
                        stdout="",
                        stderr="assertion failed",
                        duration_seconds=0.1,
                    )
                ],
                changed_files=list(changed_files or []),
                profiles=["explicit"],
                metadata={
                    "validation_breadth": validation_breadth,
                    "stop_on_first_failure": stop_on_first_failure,
                    "selection_reason": "Explicit validation commands were provided.",
                },
            )

        monkeypatch.setattr(
            "autodev.core.phase_registry.TestRunner.run_validation",
            fake_run_validation,
        )

        updated = orch._validate(started.model_copy(update={"files_modified": ["auth.py"]}))
        run_id = updated.metadata["run_id"]
        task_result = orch.state_store.load_task_result(run_id, f"{run_id}-validate")
        task = orch.state_store.load_task("issue-21__validate")
        persisted_validation = orch.state_store.load_validation_result(run_id, f"{run_id}-validate")

        assert task_result.failure is not None
        assert task_result.failure.failure_class == FailureClass.VALIDATION_FAILURE
        assert persisted_validation.failure is not None
        assert persisted_validation.failure.failure_class == FailureClass.VALIDATION_FAILURE
        assert task.status == TaskStatus.BLOCKED
        assert task.last_failure is not None
        assert task.last_failure.failure_class == FailureClass.VALIDATION_FAILURE
        assert orch.stage_outputs["validate"]["failure_class"] == "validation_failure"

    def test_retryable_phase_exception_schedules_durable_task_retry(self, tmp_path):
        orch = Orchestrator(work_dir=str(tmp_path))
        started = orch._start_run(
            AgentContext(issue_url="https://github.com/octocat/Hello-World/issues/22")
        )
        durable_task = TaskRecord(
            task_id="issue-22__plan",
            backlog_item_id="issue-22",
            phase=PhaseName.PLAN,
            max_retries=2,
        )
        orch.state_store.save_task(durable_task)

        class TimeoutPlanHandler:
            def execute(self, payload: PhaseExecutionPayload) -> PhaseExecutionResult:
                raise TimeoutError("model request timed out")

        orch.register_phase_handler(PhaseName.PLAN, TimeoutPlanHandler())

        with pytest.raises(TimeoutError, match="timed out"):
            orch._plan(started)

        run_id = started.metadata["run_id"]
        task_result = orch.state_store.load_task_result(run_id, f"{run_id}-plan")
        task = orch.state_store.load_task("issue-22__plan")

        assert task_result.failure is not None
        assert task_result.failure.failure_class == FailureClass.RETRYABLE
        assert task.status == TaskStatus.PENDING
        assert task.retry_count == 1
        assert task.next_eligible_at is not None
        assert orch.stage_outputs["plan"]["failure_class"] == "retryable"

    def test_review_persists_structured_review_result(self, tmp_path):
        orch = Orchestrator(work_dir=str(tmp_path))
        started = orch._start_run(
            AgentContext(issue_url="https://github.com/octocat/Hello-World/issues/24")
        )
        diff_path = Path(started.repo_path) / "working_tree.diff"
        diff_path.write_text("diff --git a/auth.py b/auth.py\n+fix\n", encoding="utf-8")

        review_context = started.model_copy(
            update={
                "files_modified": ["auth.py"],
                "validation_results": "PASSED\n\n$ pytest tests/test_auth.py -q\nexit_code=0",
                "metadata": {
                    **started.metadata,
                    "implementation_diff_path": str(diff_path),
                    "acceptance_criteria": ["reject invalid tokens"],
                },
            }
        )

        updated = orch._review(review_context)
        review_path = Path(updated.metadata["review_result_path"])
        persisted = orch.state_store.load_review_result(
            updated.metadata["run_id"],
            f"{updated.metadata['run_id']}-review",
        )

        assert updated.metadata["review_decision"] == ReviewDecision.APPROVED.value
        assert updated.metadata["review_passed"] is True
        assert review_path.exists()
        assert persisted == ReviewResult(
            task_id=f"{updated.metadata['run_id']}-review",
            decision=ReviewDecision.APPROVED,
            summary=updated.metadata["review_summary"],
            checks=updated.metadata["review_checks"],
            blocking_reasons=[],
            metadata={
                "files_modified": ["auth.py"],
                "implementation_diff_path": str(diff_path),
                "validation_result_path": "",
                "acceptance_criteria": ["reject invalid tokens"],
                "policy_gate_failures": [],
                "secret_exposure_findings": [],
            },
            reviewed_at=persisted.reviewed_at,
        )
        assert orch.stage_outputs["review"]["metrics"]["review_decision"] == "approved"

    def test_review_blocks_secret_exposure_as_policy_failure(self, tmp_path):
        orch = Orchestrator(work_dir=str(tmp_path))
        started = orch._start_run(
            AgentContext(issue_url="https://github.com/octocat/Hello-World/issues/26")
        )
        secret_file = Path(started.repo_path) / "secrets.py"
        secret_file.write_text('TOKEN = "ghp_supersecretvalue12345"\n', encoding="utf-8")
        diff_path = Path(started.repo_path) / "working_tree.diff"
        diff_path.write_text(
            'diff --git a/secrets.py b/secrets.py\n+TOKEN = "ghp_supersecretvalue12345"\n',
            encoding="utf-8",
        )

        review_context = started.model_copy(
            update={
                "files_modified": ["secrets.py"],
                "validation_results": "PASSED\n\n$ pytest -q\nexit_code=0",
                "metadata": {
                    **started.metadata,
                    "implementation_diff_path": str(diff_path),
                    "acceptance_criteria": ["do not commit live secrets"],
                },
            }
        )

        updated = orch._review(review_context)
        persisted = orch.state_store.load_review_result(
            updated.metadata["run_id"],
            f"{updated.metadata['run_id']}-review",
        )

        assert updated.metadata["review_decision"] == ReviewDecision.BLOCKED.value
        assert updated.metadata["review_checks"]["secret_exposure_clear"] is False
        assert updated.metadata["secret_exposure_findings"][0]["detector"] == "github_token"
        assert (
            "ghp_supersecretvalue12345"
            not in updated.metadata["secret_exposure_findings"][0]["preview"]
        )
        assert (
            persisted.metadata["secret_exposure_findings"]
            == updated.metadata["secret_exposure_findings"]
        )
        assert orch.stage_outputs["review"]["failure_class"] == FailureClass.POLICY_FAILURE.value
        assert orch.stage_outputs["review"]["metrics"]["review_decision"] == "blocked"

    def test_run_pipeline_blocks_promotion_when_review_not_approved(self, tmp_path, monkeypatch):
        orch = Orchestrator(work_dir=str(tmp_path), dry_run=False)
        opened = {"called": False}

        monkeypatch.setattr(orch, "_read_issue", lambda context: context)
        monkeypatch.setattr(
            orch,
            "_plan",
            lambda context: context.model_copy(update={"plan": ["1. ok"]}),
        )
        monkeypatch.setattr(orch, "_implement", lambda context: context)
        monkeypatch.setattr(
            orch,
            "_validate",
            lambda context: context.model_copy(update={"validation_results": "FAILED"}),
        )
        monkeypatch.setattr(
            orch,
            "_review",
            lambda context: context.model_copy(
                update={
                    "metadata": {
                        **context.metadata,
                        "review_decision": ReviewDecision.CHANGES_REQUESTED.value,
                        "review_summary": "Review requested changes: validation did not pass.",
                    }
                }
            ),
        )

        def fake_open_pr(context):
            opened["called"] = True
            return context

        monkeypatch.setattr(orch, "_open_pr", fake_open_pr)

        context = orch.run_pipeline("https://github.com/octocat/Hello-World/issues/25")

        assert opened["called"] is False
        assert context.metadata["review_decision"] == ReviewDecision.CHANGES_REQUESTED.value
        assert orch.stage_outputs["promote"]["status"] == "blocked"
        assert "changes_requested" in orch.stage_outputs["promote"]["message"]

    def test_implement_uses_fallback_files_modified_when_artifact_parse_fails(
        self, tmp_path, monkeypatch
    ):
        orch = Orchestrator(work_dir=str(tmp_path))
        started = orch._start_run(
            AgentContext(issue_url="https://github.com/octocat/Hello-World/issues/17")
        )
        changed_files_path = Path(started.repo_path) / "changed_files.json"
        diff_path = Path(started.repo_path) / "working_tree.diff"
        changed_files_path.write_text("not json", encoding="utf-8")
        diff_path.write_text("diff --git a/README.md b/README.md\n", encoding="utf-8")

        monkeypatch.setattr(
            orch.workspace_manager,
            "capture_implementation_artifacts",
            lambda _run_id: {"diff": diff_path, "changed_files": changed_files_path},
        )
        monkeypatch.setattr(
            orch,
            "_execute_phase",
            lambda _phase, _context: started.model_copy(
                update={"files_modified": ["fallback.py"], "metadata": dict(started.metadata)}
            ),
        )

        updated = orch._implement(started)

        assert updated.files_modified == ["fallback.py"]
        assert updated.metadata["implementation_change_summary"] == ["fallback.py"]
        assert orch.stage_outputs["implement"]["metrics"]["files_modified"] == 1

    def test_execute_simple(self):
        orch = Orchestrator()
        pipeline = {"stages": [{"name": "plan"}, {"name": "implement"}]}
        result = orch.execute(pipeline, {"issue_url": "https://github.com/a/b/issues/1"})
        assert result["last_stage"] == "implement"

    def test_execute_sets_completed_state(self):
        orch = Orchestrator()
        orch.execute({"stages": [{"name": "plan"}]}, {})
        assert orch.state == PipelineState.COMPLETED

    def test_execute_empty_pipeline(self):
        orch = Orchestrator()
        result = orch.execute({"stages": []}, {"key": "value"})
        assert result["key"] == "value"
        assert orch.state == PipelineState.COMPLETED

    def test_start_run_creates_dedicated_workspace_record(self, tmp_path):
        orch = Orchestrator(work_dir=str(tmp_path))

        context = AgentContext(
            issue_url="https://github.com/octocat/Hello-World/issues/9",
            metadata={"repo_full_name": "octocat/Hello-World"},
        )

        updated = orch._start_run(context)
        run = orch.state_store.load_run(updated.metadata["run_id"])

        assert updated.metadata["backlog_item_id"] == "issue-9"
        assert updated.repo_path == updated.metadata["workspace_path"]
        assert Path(updated.repo_path).exists()
        assert run.workspace_path == updated.repo_path
        assert run.metadata["issue_url"] == context.issue_url

    def test_start_run_respects_configured_isolation_mode(self, tmp_path):
        orch = Orchestrator(work_dir=str(tmp_path), isolation_mode=IsolationMode.BRANCH)

        context = AgentContext(issue_url="https://github.com/octocat/Hello-World/issues/10")
        updated = orch._start_run(context)
        run = orch.state_store.load_run(updated.metadata["run_id"])

        assert updated.metadata["isolation_mode"] == IsolationMode.BRANCH.value
        assert run.isolation_mode == IsolationMode.BRANCH

    def test_start_run_configures_run_scoped_guardrail_report(self, tmp_path):
        orch = Orchestrator(work_dir=str(tmp_path))

        context = AgentContext(issue_url="https://github.com/octocat/Hello-World/issues/11")
        updated = orch._start_run(context)
        run_id = updated.metadata["run_id"]

        orch.supervisor.record_decision(
            operation="shell_command",
            target="echo hello",
            allowed=True,
            reason="ok",
        )

        entries = orch.state_store.load_report_entries(f"guardrails-{run_id}")

        assert len(entries) == 1
        assert entries[0]["operation"] == "shell_command"
        assert entries[0]["target"] == "echo hello"
        assert entries[0]["allowed"] is True
        assert entries[0]["reason"] == "ok"

    def test_derive_backlog_item_id_ignores_query_and_fragment(self, tmp_path):
        orch = Orchestrator(work_dir=str(tmp_path))

        backlog_item_id = orch._derive_backlog_item_id(
            "https://github.com/octocat/Hello-World/issues/14?foo=bar#issuecomment-1"
        )

        assert backlog_item_id == "issue-14"

    def test_derive_backlog_item_id_sanitizes_non_identifier_characters(self, tmp_path):
        orch = Orchestrator(work_dir=str(tmp_path))

        backlog_item_id = orch._derive_backlog_item_id(
            "https://example.com/issues/Feature Request: Add CLI Support!"
        )

        assert backlog_item_id == "issue-feature-request-add-cli-support"

    def test_clone_repo_threads_isolation_branch_into_context_metadata(self, tmp_path, monkeypatch):
        orch = Orchestrator(work_dir=str(tmp_path), isolation_mode=IsolationMode.BRANCH)
        context = AgentContext(
            issue_url="https://github.com/octocat/Hello-World/issues/14",
            metadata={"repo_full_name": "octocat/Hello-World"},
        )
        started = orch._start_run(context)
        run_id = started.metadata["run_id"]
        workspace_path = started.metadata["workspace_path"]

        orch.state_store.update_run(
            run_id,
            lambda current: current.model_copy(
                update={
                    "metadata": {**current.metadata, "isolation_branch": "autodev/issue-14-run"}
                }
            ),
        )
        monkeypatch.setattr(
            orch.workspace_manager,
            "clone_repo",
            lambda _run_id, _repo_full_name: Path(workspace_path),
        )

        updated = orch._clone_repo(started)

        assert updated.metadata["isolation_branch"] == "autodev/issue-14-run"

    def test_open_pr_uses_isolation_branch_when_present(self, tmp_path, monkeypatch):
        orch = Orchestrator(work_dir=str(tmp_path))
        created: dict[str, str] = {}

        class StubPRCreator:
            def create(self, repo_full_name, branch_name, title, body):
                created["repo_full_name"] = repo_full_name
                created["branch_name"] = branch_name
                created["title"] = title
                created["body"] = body
                return "https://example.com/pr/1"

        monkeypatch.setattr("autodev.core.runtime.PRCreator", StubPRCreator)
        context = AgentContext(
            metadata={
                "repo_full_name": "octocat/Hello-World",
                "issue_title": "Use branch",
                "isolation_branch": "autodev/issue-14-run",
                "review_decision": "approved",
            }
        )

        updated = orch._open_pr(context)

        assert created["branch_name"] == "autodev/issue-14-run"
        assert updated.metadata["pr_url"] == "https://example.com/pr/1"

    def test_promote_patch_bundle_persists_metadata(self, tmp_path):
        orch = Orchestrator(work_dir=str(tmp_path))
        started = orch._start_run(
            AgentContext(issue_url="https://github.com/octocat/Hello-World/issues/27")
        )
        diff_path = Path(started.repo_path) / "working_tree.diff"
        diff_path.write_text("diff --git a/app.py b/app.py\n+print('ok')\n", encoding="utf-8")
        context = started.model_copy(
            update={
                "files_modified": ["app.py"],
                "metadata": {
                    **started.metadata,
                    "review_decision": ReviewDecision.APPROVED.value,
                    "review_summary": "Review approved.",
                    "implementation_diff_path": str(diff_path),
                    "promotion_mode": "patch_bundle",
                },
            }
        )

        updated = orch._promote(context)
        patch_path = Path(updated.metadata["promotion_patch_path"])
        run = orch.state_store.load_run(updated.metadata["run_id"])

        assert patch_path.exists()
        assert patch_path.read_text(encoding="utf-8").startswith("diff --git")
        assert orch.stage_outputs["promote"]["status"] == "completed"
        assert orch.stage_outputs["promote"]["artifacts"] == [str(patch_path)]
        assert run.metadata["promotion"]["mode"] == "patch_bundle"
        assert run.metadata["promotion"]["patch_path"] == str(patch_path)
        assert run.metadata["promotion_branch"] == updated.metadata["promotion_branch"]

    def test_promote_branch_push_persists_branch_metadata(self, tmp_path, monkeypatch):
        orch = Orchestrator(work_dir=str(tmp_path))
        started = orch._start_run(
            AgentContext(issue_url="https://github.com/octocat/Hello-World/issues/28")
        )
        events: dict[str, object] = {}

        monkeypatch.setattr(
            orch,
            "_ensure_promotion_branch",
            lambda repo_path, branch_name: events.update(
                {"repo_path": repo_path, "branch_name": branch_name}
            ),
        )
        monkeypatch.setattr(orch, "_commit_promotion_changes", lambda repo_path, message: True)
        monkeypatch.setattr(
            orch.workspace_manager.git_tool,
            "push",
            lambda repo_path, branch_name: events.update(
                {"pushed_repo_path": repo_path, "pushed_branch": branch_name}
            ),
        )

        context = started.model_copy(
            update={
                "repo_path": started.repo_path,
                "metadata": {
                    **started.metadata,
                    "review_decision": ReviewDecision.APPROVED.value,
                    "issue_title": "Ship branch",
                    "promotion_mode": "branch_push",
                },
            }
        )

        updated = orch._promote(context)
        run = orch.state_store.load_run(updated.metadata["run_id"])

        assert events["branch_name"] == updated.metadata["promotion_branch"]
        assert events["pushed_branch"] == updated.metadata["promotion_branch"]
        assert updated.metadata["promotion_pushed"] is True
        assert updated.metadata["promotion_commit_created"] is True
        assert orch.stage_outputs["promote"]["metrics"]["promotion_mode"] == "branch_push"
        assert run.metadata["promotion"]["branch"] == updated.metadata["promotion_branch"]
        assert run.metadata["promotion"]["pushed"] is True

    def test_promote_pull_request_generates_title_and_body_from_artifacts(
        self, tmp_path, monkeypatch
    ):
        orch = Orchestrator(work_dir=str(tmp_path))
        started = orch._start_run(
            AgentContext(issue_url="https://github.com/octocat/Hello-World/issues/29")
        )
        planning_artifact = Path(started.repo_path) / "planning.json"
        planning_artifact.write_text('{"plan": ["1. Update auth.py"]}\n', encoding="utf-8")
        diff_path = Path(started.repo_path) / "working_tree.diff"
        diff_path.write_text("diff --git a/auth.py b/auth.py\n+fix\n", encoding="utf-8")
        review_result = Path(started.repo_path) / "review.json"
        review_result.write_text('{"decision": "approved"}\n', encoding="utf-8")
        created: dict[str, str] = {}

        monkeypatch.setattr(
            orch,
            "_push_branch",
            lambda context: context.model_copy(
                update={
                    "metadata": {
                        **context.metadata,
                        "promotion_branch": "autodev/issue-29",
                        "promotion_pushed": True,
                    }
                }
            ),
        )

        class StubPRCreator:
            def create(self, repo_full_name, branch_name, title, body):
                created["repo_full_name"] = repo_full_name
                created["branch_name"] = branch_name
                created["title"] = title
                created["body"] = body
                return "https://example.com/pr/29"

        monkeypatch.setattr("autodev.core.runtime.PRCreator", StubPRCreator)

        context = started.model_copy(
            update={
                "files_modified": ["auth.py", "tests/test_auth.py"],
                "validation_results": "PASSED\n\n$ pytest tests/test_auth.py -q\nexit_code=0",
                "metadata": {
                    **started.metadata,
                    "repo_full_name": "octocat/Hello-World",
                    "review_decision": ReviewDecision.APPROVED.value,
                    "review_summary": "Review approved after validation and policy checks.",
                    "issue_title": "Improve auth flow",
                    "acceptance_criteria": ["reject invalid tokens"],
                    "planning_artifact_path": str(planning_artifact),
                    "implementation_diff_path": str(diff_path),
                    "review_result_path": str(review_result),
                    "promotion_mode": "pull_request",
                },
            }
        )

        updated = orch._promote(context)
        run = orch.state_store.load_run(updated.metadata["run_id"])

        assert created["branch_name"] == "autodev/issue-29"
        assert created["title"] == "[AutoDev] Improve auth flow"
        assert "## Files Modified" in created["body"]
        assert "auth.py" in created["body"]
        assert str(diff_path) in created["body"]
        assert updated.metadata["pr_url"] == "https://example.com/pr/29"
        assert orch.stage_outputs["promote"]["metrics"]["promotion_mode"] == "pull_request"
        assert run.metadata["promotion"]["pr_title"] == created["title"]
        assert run.metadata["promotion"]["pr_url"] == "https://example.com/pr/29"

    def test_run_pipeline_finalizes_completed_run(self, tmp_path, monkeypatch):
        orch = Orchestrator(work_dir=str(tmp_path), dry_run=True)
        finalized: dict[str, object] = {}

        monkeypatch.setattr(orch, "_read_issue", lambda context: context)
        monkeypatch.setattr(
            orch,
            "_plan",
            lambda context: context.model_copy(update={"plan": ["1. ok"]}),
        )
        monkeypatch.setattr(orch, "_implement", lambda context: context)
        monkeypatch.setattr(
            orch,
            "_validate",
            lambda context: context.model_copy(update={"validation_results": "PASSED"}),
        )
        monkeypatch.setattr(orch, "_review", lambda context: context)

        def finalize_run(run_id, *, status, quarantine_on_failure=False):
            finalized["run_id"] = run_id
            finalized["status"] = status
            finalized["quarantine_on_failure"] = quarantine_on_failure
            return orch.state_store.load_run(run_id)

        monkeypatch.setattr(orch.workspace_manager, "finalize_run", finalize_run)

        context = orch.run_pipeline("https://github.com/octocat/Hello-World/issues/12")

        assert finalized["run_id"] == context.metadata["run_id"]
        assert finalized["status"] == RunStatus.COMPLETED
        assert finalized["quarantine_on_failure"] is False
        assert orch.state == PipelineState.COMPLETED

    def test_run_pipeline_does_not_fail_when_finalize_run_errors_after_success(
        self, tmp_path, monkeypatch
    ):
        orch = Orchestrator(work_dir=str(tmp_path), dry_run=True)

        monkeypatch.setattr(orch, "_read_issue", lambda context: context)
        monkeypatch.setattr(
            orch,
            "_plan",
            lambda context: context.model_copy(update={"plan": ["1. ok"]}),
        )
        monkeypatch.setattr(orch, "_implement", lambda context: context)
        monkeypatch.setattr(
            orch,
            "_validate",
            lambda context: context.model_copy(update={"validation_results": "PASSED"}),
        )
        monkeypatch.setattr(orch, "_review", lambda context: context)

        def finalize_run(_run_id, *, status, quarantine_on_failure=False):
            raise RuntimeError("teardown failed")

        monkeypatch.setattr(orch.workspace_manager, "finalize_run", finalize_run)

        context = orch.run_pipeline("https://github.com/octocat/Hello-World/issues/12")
        run = orch.state_store.load_run(context.metadata["run_id"])

        assert orch.state == PipelineState.COMPLETED
        assert run.metadata["finalize_run_error"] == "teardown failed"
        assert "finalize_run_error_at" in run.metadata

    def test_run_pipeline_finalizes_failed_run_with_quarantine(self, tmp_path, monkeypatch):
        orch = Orchestrator(work_dir=str(tmp_path), dry_run=True)
        finalized: dict[str, object] = {}

        monkeypatch.setattr(orch, "_read_issue", lambda context: context)

        def fail_plan(_context):
            raise RuntimeError("boom")

        monkeypatch.setattr(orch, "_plan", fail_plan)

        def finalize_run(run_id, *, status, quarantine_on_failure=False):
            finalized["run_id"] = run_id
            finalized["status"] = status
            finalized["quarantine_on_failure"] = quarantine_on_failure
            return orch.state_store.load_run(run_id)

        monkeypatch.setattr(orch.workspace_manager, "finalize_run", finalize_run)

        with pytest.raises(RuntimeError, match="boom"):
            orch.run_pipeline("https://github.com/octocat/Hello-World/issues/13")

        assert finalized["status"] == RunStatus.FAILED
        assert finalized["quarantine_on_failure"] is True
        assert orch.state == PipelineState.FAILED
