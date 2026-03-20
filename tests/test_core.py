"""Tests for core components: TaskGraph, Supervisor, unified Orchestrator."""

from pathlib import Path

import pytest

from autodev.agents.base import AgentContext
from autodev.core.runtime import Orchestrator, PipelineState
from autodev.core.schemas import IsolationMode, RunStatus
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
            }
        )

        updated = orch._open_pr(context)

        assert created["branch_name"] == "autodev/issue-14-run"
        assert updated.metadata["pr_url"] == "https://example.com/pr/1"

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
