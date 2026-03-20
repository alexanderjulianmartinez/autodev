"""Tests for core components: TaskGraph, Supervisor, unified Orchestrator."""

from pathlib import Path

import pytest

from autodev.agents.base import AgentContext
from autodev.core.runtime import Orchestrator, PipelineState
from autodev.core.schemas import IsolationMode
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
