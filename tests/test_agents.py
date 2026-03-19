"""Tests for agent components."""

from autodev.agents.base import AgentContext
from autodev.agents.coder import CoderAgent
from autodev.agents.debugger import DebuggerAgent
from autodev.agents.planner import PlannerAgent
from autodev.agents.reviewer import ReviewerAgent


class TestPlannerAgent:
    def test_run_produces_plan(self):
        agent = PlannerAgent()
        ctx = AgentContext(issue_url="https://github.com/a/b/issues/1")
        result = agent.run("generate plan", ctx)
        assert isinstance(result.plan, list)
        assert len(result.plan) > 0

    def test_run_does_not_modify_issue_url(self):
        agent = PlannerAgent()
        ctx = AgentContext(issue_url="https://github.com/a/b/issues/99")
        result = agent.run("generate plan", ctx)
        assert result.issue_url == "https://github.com/a/b/issues/99"

    def test_plan_items_are_strings(self):
        agent = PlannerAgent()
        ctx = AgentContext()
        result = agent.run("generate plan", ctx)
        assert all(isinstance(item, str) for item in result.plan)


class TestCoderAgent:
    def test_run_modifies_files_modified(self):
        agent = CoderAgent()
        ctx = AgentContext(plan=["1. Modify auth.py to add token validation"])
        result = agent.run("implement plan", ctx)
        assert isinstance(result.files_modified, list)

    def test_run_empty_plan(self):
        agent = CoderAgent()
        ctx = AgentContext(plan=[])
        result = agent.run("implement plan", ctx)
        assert result.files_modified == []

    def test_run_preserves_existing_files_modified(self):
        agent = CoderAgent()
        ctx = AgentContext(
            plan=["1. Update README.md"],
            files_modified=["existing_file.py"],
        )
        result = agent.run("implement plan", ctx)
        assert "existing_file.py" in result.files_modified


class TestReviewerAgent:
    def test_run_produces_review(self):
        agent = ReviewerAgent()
        ctx = AgentContext(
            files_modified=["auth.py"],
            validation_results="PASSED",
        )
        result = agent.run("review changes", ctx)
        assert "review" in result.metadata
        assert result.metadata["review_passed"] is True

    def test_run_flags_no_changes(self):
        agent = ReviewerAgent()
        ctx = AgentContext(files_modified=[])
        result = agent.run("review changes", ctx)
        assert result.metadata.get("review_passed") is False


class TestDebuggerAgent:
    def test_run_increments_iteration(self):
        agent = DebuggerAgent()
        ctx = AgentContext(iteration=0, validation_results="FAILED: assertion error")
        result = agent.run("debug failures", ctx)
        assert result.iteration == 1

    def test_run_adds_debug_suggestion(self):
        agent = DebuggerAgent()
        ctx = AgentContext(iteration=1, validation_results="FAILED: timeout")
        result = agent.run("debug failures", ctx)
        assert "debug_suggestion" in result.metadata

    def test_run_no_validation_results(self):
        agent = DebuggerAgent()
        ctx = AgentContext(iteration=0, validation_results="")
        result = agent.run("debug failures", ctx)
        assert "analyze" in result.metadata["debug_suggestion"].lower()
