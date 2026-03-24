"""Tests for agent components."""

from autodev.agents.base import AgentContext
from autodev.agents.coder import CoderAgent
from autodev.agents.debugger import DebuggerAgent
from autodev.agents.planner import PlannerAgent
from autodev.agents.reviewer import ReviewerAgent
from autodev.core.state_store import FileStateStore
from autodev.core.supervisor import Supervisor
from autodev.core.workspace_manager import WorkspaceManager
from autodev.tools.filesystem_tool import FilesystemTool


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

    def test_run_extracts_acceptance_criteria_in_fallback_mode(self):
        agent = PlannerAgent()
        ctx = AgentContext(
            issue_url="https://github.com/a/b/issues/2",
            metadata={
                "issue_title": "Add token validation",
                "issue_body": (
                    "Acceptance criteria:\n- reject invalid tokens\n- preserve valid sessions\n"
                ),
            },
        )

        result = agent.run("generate plan", ctx)

        assert result.metadata["planning_mode"] == "fallback"
        assert result.metadata["acceptance_criteria"] == [
            "reject invalid tokens",
            "preserve valid sessions",
        ]
        assert result.metadata["validation_hints"]
        assert any("acceptance criteria" in step.lower() for step in result.plan)

    def test_run_uses_repository_context_to_identify_target_files(self, tmp_path):
        agent = PlannerAgent()
        (tmp_path / "auth.py").write_text("def validate_token(token):\n    return bool(token)\n")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_auth.py").write_text("def test_validate_token():\n    assert True\n")
        (tmp_path / "README.md").write_text("auth overview\n")

        ctx = AgentContext(
            issue_url="https://github.com/a/b/issues/3",
            repo_path=str(tmp_path),
            metadata={
                "issue_title": "Add token validation to auth flow",
                "issue_body": (
                    "Acceptance criteria:\n- reject invalid tokens\n- preserve valid sessions\n"
                ),
            },
        )

        result = agent.run("generate plan", ctx)

        assert result.metadata["planning_mode"] == "repository-aware"
        assert any(path.endswith("auth.py") for path in result.metadata["likely_target_files"])
        assert any("pytest" in hint.lower() for hint in result.metadata["validation_hints"])
        assert any("auth.py" in step for step in result.plan)


class TestCoderAgent:
    def test_run_modifies_files_modified(self):
        agent = CoderAgent()
        ctx = AgentContext(plan=["1. Modify auth.py to add token validation"])
        result = agent.run("implement plan", ctx)
        assert isinstance(result.files_modified, list)

    def test_run_applies_controlled_edit_to_workspace_file(self, tmp_path):
        store = FileStateStore(str(tmp_path / "state"))
        manager = WorkspaceManager(store)
        supervisor = Supervisor(state_store=store)
        run = manager.create_run("AD-014", run_id="run-014")
        workspace = tmp_path / "state" / "runs" / "run-014" / "workspace"
        readme = workspace / "README.md"
        readme.write_text("# AutoDev\n", encoding="utf-8")

        agent = CoderAgent(workspace_manager=manager, supervisor=supervisor)
        ctx = AgentContext(
            repo_path=str(workspace),
            plan=["1. Update README.md"],
            metadata={
                "run_id": run.run_id,
                "issue_title": "Document implementation workflow",
                "likely_target_files": ["README.md"],
            },
        )

        result = agent.run("implement plan", ctx)

        assert result.metadata["implementation_status"] == "applied"
        assert result.files_modified == ["README.md"]
        assert "AutoDev implementation note: Document implementation workflow" in readme.read_text(
            encoding="utf-8"
        )
        assert result.metadata["implementation_edit_summaries"][0]["snapshot_path"].endswith(
            "snapshots/before-implement/README.md"
        )

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

    def test_run_rolls_back_failed_write_and_marks_status(self, tmp_path, monkeypatch):
        store = FileStateStore(str(tmp_path / "state"))
        manager = WorkspaceManager(store)
        supervisor = Supervisor(state_store=store)
        run = manager.create_run("AD-014", run_id="run-014-rollback")
        workspace = tmp_path / "state" / "runs" / "run-014-rollback" / "workspace"
        first = workspace / "first.py"
        second = workspace / "second.py"
        first.write_text("print('first')\n", encoding="utf-8")
        second.write_text("print('second')\n", encoding="utf-8")

        original_write = FilesystemTool.write_file
        write_calls = {"count": 0}

        def failing_write(tool, path, content):
            write_calls["count"] += 1
            if write_calls["count"] == 2:
                raise OSError("disk full")
            return original_write(tool, path, content)

        monkeypatch.setattr(FilesystemTool, "write_file", failing_write)

        agent = CoderAgent(workspace_manager=manager, supervisor=supervisor)
        ctx = AgentContext(
            repo_path=str(workspace),
            plan=["1. Update first.py", "2. Update second.py"],
            metadata={
                "run_id": run.run_id,
                "issue_title": "Implement safer writes",
                "likely_target_files": ["first.py", "second.py"],
            },
        )

        result = agent.run("implement plan", ctx)

        assert result.metadata["implementation_status"] == "rolled_back"
        assert result.metadata["implementation_error"] == "disk full"
        assert result.metadata["rolled_back_files"] == ["first.py"]
        assert result.files_modified == []
        assert first.read_text(encoding="utf-8") == "print('first')\n"
        assert second.read_text(encoding="utf-8") == "print('second')\n"


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
