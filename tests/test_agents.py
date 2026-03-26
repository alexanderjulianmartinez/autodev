"""Tests for agent components."""

from pathlib import Path

from autodev.agents.base import AgentContext
from autodev.agents.coder import CoderAgent
from autodev.agents.debugger import DebuggerAgent
from autodev.agents.planner import PlannerAgent
from autodev.agents.reviewer import ReviewerAgent
from autodev.core.schemas import ReviewDecision
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

    def test_run_prefers_explicit_target_files_and_requested_changes(self, tmp_path):
        agent = PlannerAgent()
        (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

        ctx = AgentContext(
            issue_url="https://github.com/a/demo/issues/4",
            repo_path=str(tmp_path),
            metadata={
                "issue_title": "Document dry run mode",
                "issue_body": (
                    "## Target Files\n"
                    "- README.md\n\n"
                    "## Requested Changes\n"
                    "- Explain that dry-run skips remote promotion.\n"
                    "- Mention that run artifacts are written to the state directory.\n\n"
                    "## Acceptance Criteria\n"
                    "- README.md mentions dry-run skips remote promotion.\n"
                ),
            },
        )

        result = agent.run("generate plan", ctx)

        assert result.metadata["likely_target_files"] == ["README.md"]
        assert result.metadata["requested_changes"] == [
            "Explain that dry-run skips remote promotion.",
            "Mention that run artifacts are written to the state directory.",
        ]
        assert result.metadata["execution_strategy"] == "text_update"
        assert any("requested documentation" in step.lower() for step in result.plan)

    def test_run_extracts_code_scaffold_strategy_and_validation_commands(self, tmp_path):
        agent = PlannerAgent()
        (tmp_path / "contracts.py").write_text("", encoding="utf-8")

        ctx = AgentContext(
            issue_url="https://github.com/a/demo/issues/5",
            repo_path=str(tmp_path),
            metadata={
                "issue_title": "Scaffold integration contracts",
                "issue_body": (
                    "## Target Files\n"
                    "- contracts.py\n\n"
                    "## Requested Changes\n"
                    "- add protocol IntegrationProvider with fetch and update methods\n"
                    "- add dataclass CapabilityDescriptor\n"
                    "- add function build_provider\n\n"
                    "## Validation Commands\n"
                    "- pytest tests/test_contracts.py -q\n\n"
                    "## Acceptance Criteria\n"
                    "- contracts.py defines IntegrationProvider\n"
                ),
            },
        )

        result = agent.run("generate plan", ctx)

        assert result.metadata["execution_strategy"] == "code_scaffold"
        assert result.metadata["validation_commands"] == ["pytest tests/test_contracts.py -q"]
        assert any("scaffold the requested code constructs" in step.lower() for step in result.plan)

    def test_score_candidate_file_skips_oversized_content_reads(self, tmp_path):
        agent = PlannerAgent()
        candidate = tmp_path / "notes.txt"
        candidate.write_text("validation " * 10000, encoding="utf-8")

        score = agent._score_candidate_file(candidate, "notes.txt", ["validation"])

        assert score == 0


class TestCoderAgent:
    def test_run_modifies_files_modified(self):
        agent = CoderAgent()
        ctx = AgentContext(plan=["1. Modify auth.py to add token validation"])
        result = agent.run("implement plan", ctx)
        assert isinstance(result.files_modified, list)

    def test_run_falls_back_to_stub_when_repo_path_is_missing(self):
        class StubRouter:
            def generate(self, _prompt, model_key=None):
                return "generated.py"

        agent = CoderAgent(model_router=StubRouter())
        ctx = AgentContext(plan=["1. Update README.md"], files_modified=[])

        result = agent.run("implement plan", ctx)

        assert "README.md" in result.files_modified
        assert "generated.py" not in result.files_modified

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

    def test_run_scaffolds_python_symbols_for_explicit_code_issue(self, tmp_path):
        store = FileStateStore(str(tmp_path / "state"))
        manager = WorkspaceManager(store)
        supervisor = Supervisor(state_store=store)
        run = manager.create_run("AD-028", run_id="run-028-code")
        workspace = tmp_path / "state" / "runs" / "run-028-code" / "workspace"

        agent = CoderAgent(workspace_manager=manager, supervisor=supervisor)
        ctx = AgentContext(
            repo_path=str(workspace),
            plan=["1. Scaffold integration contracts in contracts.py"],
            metadata={
                "run_id": run.run_id,
                "issue_title": "Scaffold integration contracts",
                "likely_target_files": ["contracts.py"],
                "requested_changes": [
                    "add protocol IntegrationProvider with fetch and update methods",
                    "add dataclass CapabilityDescriptor",
                    "add function build_provider",
                ],
            },
        )

        result = agent.run("implement plan", ctx)
        content = (workspace / "contracts.py").read_text(encoding="utf-8")

        assert result.metadata["implementation_status"] == "applied"
        assert result.files_modified == ["contracts.py"]
        assert "from typing import Protocol" in content
        assert "from dataclasses import dataclass" in content
        assert "class IntegrationProvider(Protocol):" in content
        assert "def fetch(self, identifier: str) -> object: ..." in content
        assert "@dataclass" in content
        assert "class CapabilityDescriptor:" in content
        assert "def build_provider() -> None:" in content

    def test_llm_code_gen_writes_model_output(self, tmp_path):
        """When model_router is present, _apply_single_edit uses LLM output."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        target = workspace / "utils.py"
        target.write_text("# placeholder\n", encoding="utf-8")

        class StubRouter:
            def generate(self, _prompt, model_key=None):
                return "def helper() -> None:\n    pass\n"

        agent = CoderAgent(model_router=StubRouter())
        ctx = AgentContext(
            repo_path=str(workspace),
            plan=["1. Implement helper in utils.py"],
            metadata={
                "issue_title": "Add helper function",
                "likely_target_files": ["utils.py"],
            },
        )

        result = agent.run("implement plan", ctx)

        assert result.metadata["implementation_status"] == "applied"
        assert target.read_text(encoding="utf-8") == "def helper() -> None:\n    pass\n"

    def test_llm_code_gen_falls_back_to_annotation_on_exception(self, tmp_path):
        """When the model raises, _apply_single_edit falls back to annotation."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        target = workspace / "utils.py"
        target.write_text("# placeholder\n", encoding="utf-8")

        class FailingRouter:
            def generate(self, _prompt, model_key=None):
                raise RuntimeError("API unavailable")

        agent = CoderAgent(model_router=FailingRouter())
        ctx = AgentContext(
            repo_path=str(workspace),
            plan=["1. Implement helper in utils.py"],
            metadata={
                "issue_title": "Add helper function",
                "likely_target_files": ["utils.py"],
            },
        )

        result = agent.run("implement plan", ctx)

        assert result.metadata["implementation_status"] == "applied"
        content = target.read_text(encoding="utf-8")
        assert "AutoDev implementation note" in content

    def test_llm_code_gen_falls_back_to_annotation_on_empty_response(self, tmp_path):
        """When the model returns empty/whitespace, annotation fallback is used."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        target = workspace / "utils.py"
        target.write_text("# placeholder\n", encoding="utf-8")

        class EmptyRouter:
            def generate(self, _prompt, model_key=None):
                return "   "

        agent = CoderAgent(model_router=EmptyRouter())
        ctx = AgentContext(
            repo_path=str(workspace),
            plan=["1. Implement helper in utils.py"],
            metadata={
                "issue_title": "Add helper function",
                "likely_target_files": ["utils.py"],
            },
        )

        result = agent.run("implement plan", ctx)

        assert result.metadata["implementation_status"] == "applied"
        content = target.read_text(encoding="utf-8")
        assert "AutoDev implementation note" in content


class TestReviewerAgent:
    def test_run_produces_review(self):
        agent = ReviewerAgent()
        ctx = AgentContext(
            files_modified=["auth.py"],
            validation_results="PASSED",
            metadata={"acceptance_criteria": ["reject invalid tokens"]},
        )
        result = agent.run("review changes", ctx)
        assert "review" in result.metadata
        assert result.metadata["review_decision"] == ReviewDecision.APPROVED.value
        assert result.metadata["review_checks"]["validation_passed"] is True
        assert result.metadata["review_passed"] is True

    def test_run_blocks_policy_failures(self):
        agent = ReviewerAgent()
        ctx = AgentContext(
            files_modified=["auth.py"],
            validation_results="PASSED",
            metadata={
                "acceptance_criteria": ["reject invalid tokens"],
                "policy_checks_passed": False,
                "policy_gate_failures": ["branch naming policy failed"],
            },
        )

        result = agent.run("review changes", ctx)

        assert result.metadata["review_decision"] == ReviewDecision.BLOCKED.value
        assert result.metadata["review_checks"]["policy_checks_passed"] is False
        assert result.metadata["policy_gate_failures"] == ["branch naming policy failed"]
        assert "branch naming policy failed" in result.metadata["review_blocking_reasons"]

    def test_run_blocks_secret_like_content(self, tmp_path):
        agent = ReviewerAgent()
        secret_file = Path(tmp_path) / "secrets.py"
        secret_file.write_text('OPENAI_API_KEY = "sk-1234567890abcdef"\n', encoding="utf-8")
        ctx = AgentContext(
            repo_path=str(tmp_path),
            files_modified=["secrets.py"],
            validation_results="PASSED",
            metadata={"acceptance_criteria": ["keep credentials out of source"]},
        )

        result = agent.run("review changes", ctx)

        assert result.metadata["review_decision"] == ReviewDecision.BLOCKED.value
        assert result.metadata["review_checks"]["secret_exposure_clear"] is False
        assert result.metadata["secret_exposure_findings"][0]["path"] == "secrets.py"
        assert (
            "sk-1234567890abcdef" not in result.metadata["secret_exposure_findings"][0]["preview"]
        )
        assert "secret-like content detected" in result.metadata["review_summary"]

    def test_run_flags_no_changes(self):
        agent = ReviewerAgent()
        ctx = AgentContext(files_modified=[], metadata={"acceptance_criteria": ["something"]})
        result = agent.run("review changes", ctx)
        assert result.metadata["review_decision"] == ReviewDecision.BLOCKED.value
        assert result.metadata.get("review_passed") is False

    def test_run_awaits_human_approval_when_required(self):
        agent = ReviewerAgent()
        ctx = AgentContext(
            files_modified=["auth.py"],
            validation_results="PASSED",
            metadata={
                "acceptance_criteria": ["reject invalid tokens"],
                "requires_human_approval": True,
            },
        )
        result = agent.run("review changes", ctx)

        assert result.metadata["review_decision"] == ReviewDecision.AWAITING_HUMAN_APPROVAL.value
        assert result.metadata["review_passed"] is False


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
