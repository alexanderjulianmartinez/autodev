"""Tests for tool components."""

import os
import shlex
import subprocess
import sys
import tempfile
from unittest.mock import patch

import pytest

from autodev.core.schemas import ValidationCommandResult, ValidationStatus
from autodev.core.state_store import FileStateStore
from autodev.core.supervisor import Supervisor
from autodev.tools.filesystem_tool import FilesystemTool
from autodev.tools.git_tool import GitTool
from autodev.tools.shell_tool import ShellTool
from autodev.tools.test_runner import TestRunner


class TestShellTool:
    def test_safe_command(self):
        tool = ShellTool()
        result = tool.run("echo hello")
        assert result["returncode"] == 0
        assert "hello" in result["stdout"]

    def test_blocked_command_returns_nonzero(self):
        tool = ShellTool()
        result = tool.run("rm -rf /")
        assert result["returncode"] != 0
        assert "Blocked" in result["stderr"]

    def test_blocked_sudo(self):
        tool = ShellTool()
        result = tool.run("sudo echo hi")
        assert result["returncode"] != 0

    def test_command_with_cwd(self):
        tool = ShellTool()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = tool.run("pwd", cwd=tmpdir)
            assert result["returncode"] == 0
            assert tmpdir in result["stdout"]

    def test_execute_interface(self):
        tool = ShellTool()
        result = tool.execute({"command": "echo test"})
        assert result["returncode"] == 0

    def test_guardrail_decisions_are_persisted_for_shell_commands(self, tmp_path):
        store = FileStateStore(str(tmp_path / "state"))
        supervisor = Supervisor(state_store=store)
        tool = ShellTool(supervisor=supervisor)

        blocked = tool.run("rm -rf /")
        allowed = tool.run("echo hello")
        decisions = store.load_report_entries("guardrails")

        assert blocked["returncode"] != 0
        assert allowed["returncode"] == 0
        assert [entry["allowed"] for entry in decisions] == [False, True]
        assert [entry["operation"] for entry in decisions] == ["shell_command", "shell_command"]


class TestFilesystemTool:
    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FilesystemTool(base_path=tmpdir)
            path = os.path.join(tmpdir, "hello.txt")
            tool.write_file(path, "hello world")
            assert tool.read_file(path) == "hello world"

    def test_list_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FilesystemTool(base_path=tmpdir)
            tool.write_file(os.path.join(tmpdir, "a.py"), "# a")
            tool.write_file(os.path.join(tmpdir, "b.txt"), "b")
            py_files = tool.list_files(tmpdir, pattern="*.py")
            assert any("a.py" in f for f in py_files)
            assert not any("b.txt" in f for f in py_files)

    def test_file_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FilesystemTool(base_path=tmpdir)
            path = os.path.join(tmpdir, "exists.txt")
            assert not tool.file_exists(path)
            tool.write_file(path, "data")
            assert tool.file_exists(path)

    def test_relative_paths_resolve_against_base_path(self, tmp_path):
        tool = FilesystemTool(base_path=str(tmp_path))

        tool.write_file("notes.txt", "hello")

        assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello"
        assert tool.read_file("notes.txt") == "hello"
        assert tool.file_exists("notes.txt")

    def test_list_files_accepts_relative_directory_from_base_path(self, tmp_path):
        tool = FilesystemTool(base_path=str(tmp_path))
        tool.write_file("src/app.py", "print('hi')\n")
        tool.write_file("src/readme.txt", "hello\n")

        py_files = tool.list_files("src", pattern="*.py")

        assert py_files == [str(tmp_path / "src" / "app.py")]

    def test_outside_base_path_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FilesystemTool(base_path=tmpdir)
            with pytest.raises(ValueError, match="outside"):
                tool.read_file("/etc/passwd")

    def test_prefix_matching_path_outside_base_path_is_rejected(self, tmp_path):
        base_path = tmp_path / "base"
        base_path.mkdir(parents=True)
        sibling_path = tmp_path / "base-evil"
        sibling_path.mkdir(parents=True)
        target = sibling_path / "outside.txt"
        target.write_text("escape", encoding="utf-8")

        tool = FilesystemTool(base_path=str(base_path))

        with pytest.raises(ValueError, match="outside"):
            tool.write_file(str(target), "still blocked")

    def test_blocked_file_write_is_rejected_and_persisted(self, tmp_path):
        store = FileStateStore(str(tmp_path / "state"))
        supervisor = Supervisor(state_store=store)
        tool = FilesystemTool(base_path=str(tmp_path), supervisor=supervisor)
        blocked_path = tmp_path / ".git" / "config"

        with pytest.raises(PermissionError, match="Blocked file write"):
            tool.write_file(str(blocked_path), "unsafe")

        decisions = store.load_report_entries("guardrails")
        assert decisions[-1]["operation"] == "file_write"
        assert decisions[-1]["allowed"] is False

    def test_blocked_worktree_git_file_write_is_rejected(self, tmp_path):
        store = FileStateStore(str(tmp_path / "state"))
        supervisor = Supervisor(state_store=store)
        tool = FilesystemTool(base_path=str(tmp_path), supervisor=supervisor)
        blocked_path = tmp_path / "workspace" / ".git"

        with pytest.raises(PermissionError, match="Blocked file write"):
            tool.write_file(str(blocked_path), "gitdir: /tmp/repo/.git/worktrees/run\n")

        decisions = store.load_report_entries("guardrails")
        assert decisions[-1]["target"] == str(blocked_path)
        assert decisions[-1]["allowed"] is False

    def test_repo_internal_bin_and_etc_directories_are_allowed(self, tmp_path):
        store = FileStateStore(str(tmp_path / "state"))
        supervisor = Supervisor(state_store=store)
        tool = FilesystemTool(base_path=str(tmp_path), supervisor=supervisor)
        bin_target = tmp_path / "bin" / "script.sh"
        etc_target = tmp_path / "config" / "etc" / "settings.ini"

        tool.write_file(str(bin_target), "echo safe\n")
        tool.write_file(str(etc_target), "[app]\nmode=safe\n")

        decisions = store.load_report_entries("guardrails")
        assert bin_target.read_text(encoding="utf-8") == "echo safe\n"
        assert etc_target.read_text(encoding="utf-8") == "[app]\nmode=safe\n"
        assert decisions[-2]["allowed"] is True
        assert decisions[-1]["allowed"] is True

    def test_os_protected_prefixes_remain_blocked(self):
        supervisor = Supervisor()

        assert supervisor.validate_file_write("/etc/passwd") == (
            False,
            "Blocked file write path: '/etc'",
        )
        assert supervisor.validate_file_write("/usr/bin/tool") == (
            False,
            "Blocked file write path: '/usr/bin'",
        )

    def test_allowed_file_write_is_persisted(self, tmp_path):
        store = FileStateStore(str(tmp_path / "state"))
        supervisor = Supervisor(state_store=store)
        tool = FilesystemTool(base_path=str(tmp_path), supervisor=supervisor)
        target = tmp_path / "notes.txt"

        tool.write_file(str(target), "safe")

        decisions = store.load_report_entries("guardrails")
        assert target.read_text(encoding="utf-8") == "safe"
        assert decisions[-1]["operation"] == "file_write"
        assert decisions[-1]["allowed"] is True


class TestTestRunner:
    def test_run_passing_tests(self):
        runner = TestRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test_sample.py")
            with open(test_file, "w") as f:
                f.write("def test_pass():\n    assert 1 == 1\n")
            result = runner.run(repo_path=tmpdir, test_command="pytest test_sample.py -v")
            assert result.passed

    def test_run_failing_tests(self):
        runner = TestRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test_fail.py")
            with open(test_file, "w") as f:
                f.write("def test_fail():\n    assert 1 == 2\n")
            result = runner.run(repo_path=tmpdir, test_command="pytest test_fail.py -v")
            assert not result.passed

    def test_blocked_test_command_is_rejected_by_supervisor(self, tmp_path):
        store = FileStateStore(str(tmp_path / "state"))
        supervisor = Supervisor(state_store=store)
        runner = TestRunner(supervisor=supervisor)

        result = runner.run(repo_path=str(tmp_path), test_command="sudo pytest")

        assert not result.passed
        assert "Blocked:" in result.error
        assert store.load_report_entries("guardrails")[-1]["operation"] == "test_command"

    def test_run_validation_uses_explicit_commands_when_provided(self, tmp_path):
        runner = TestRunner()
        test_file = tmp_path / "test_sample.py"
        test_file.write_text("def test_pass():\n    assert 1 == 1\n", encoding="utf-8")

        result = runner.run_validation(
            repo_path=str(tmp_path),
            task_id="validate-explicit",
            explicit_commands=["pytest test_sample.py -q"],
        )

        assert result.status == ValidationStatus.PASSED
        assert result.profiles == ["explicit"]
        assert result.commands[0].command == "pytest test_sample.py -q"

    def test_run_validation_executes_pytest_with_active_interpreter(self, monkeypatch, tmp_path):
        runner = TestRunner()
        captured: dict[str, object] = {}

        class Completed:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return Completed()

        monkeypatch.setattr("autodev.tools.test_runner.subprocess.run", fake_run)

        result = runner.run_validation(
            repo_path=str(tmp_path),
            task_id="validate-explicit",
            explicit_commands=["pytest test_sample.py -q"],
        )

        assert result.status == ValidationStatus.PASSED
        assert result.commands[0].command == "pytest test_sample.py -q"
        assert captured["command"] == shlex.join(
            [sys.executable, "-m", "pytest", "test_sample.py", "-q"]
        )

    def test_run_validation_derives_targeted_pytest_from_changed_files(self, tmp_path):
        runner = TestRunner()
        source_file = tmp_path / "auth.py"
        source_file.write_text(
            "def validate_token(token):\n    return bool(token)\n",
            encoding="utf-8",
        )
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_auth.py").write_text(
            "def test_validate_token():\n    assert True\n",
            encoding="utf-8",
        )

        commands, profiles, reason = runner.plan_validation(
            repo_path=str(tmp_path),
            changed_files=["auth.py"],
        )

        assert profiles == ["changed-file-targeted", "targeted"]
        assert commands == ["pytest tests/test_auth.py -v"]
        assert "strict targeted validation" in reason.lower()

    def test_plan_validation_broader_fallback_adds_project_default(self, tmp_path):
        runner = TestRunner()
        source_file = tmp_path / "auth.py"
        source_file.write_text(
            "def validate_token(token):\n    return bool(token)\n",
            encoding="utf-8",
        )
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_auth.py").write_text(
            "def test_validate_token():\n    assert True\n",
            encoding="utf-8",
        )

        commands, profiles, reason = runner.plan_validation(
            repo_path=str(tmp_path),
            changed_files=["auth.py"],
            validation_breadth="broader-fallback",
        )

        assert commands == ["pytest tests/test_auth.py -v", "pytest -q"]
        assert profiles == ["changed-file-targeted", "broader-fallback"]
        assert "broader fallback" in reason.lower()

    def test_run_validation_continue_on_error_executes_all_commands(self, monkeypatch):
        runner = TestRunner()
        command_results = iter(
            [
                ValidationCommandResult(
                    command="cmd1",
                    exit_code=1,
                    status=ValidationStatus.FAILED,
                    stdout="",
                    stderr="first failed",
                    duration_seconds=0.01,
                ),
                ValidationCommandResult(
                    command="cmd2",
                    exit_code=0,
                    status=ValidationStatus.PASSED,
                    stdout="ok",
                    stderr="",
                    duration_seconds=0.01,
                ),
            ]
        )

        monkeypatch.setattr(
            runner,
            "_run_validation_command",
            lambda **_kwargs: next(command_results),
        )

        result = runner.run_validation(
            repo_path=".",
            task_id="validate-continue",
            explicit_commands=["cmd1", "cmd2"],
            stop_on_first_failure=False,
        )

        assert len(result.commands) == 2
        assert result.status == ValidationStatus.FAILED
        assert result.metadata["stop_on_first_failure"] is False
        assert result.summary == "Validation failed after executing 2 command(s)."


class TestGitTool:
    def test_missing_git_cli_raises_clear_runtime_error(self):
        tool = GitTool()

        with patch("autodev.tools.git_tool.subprocess.run", side_effect=FileNotFoundError()):
            with pytest.raises(RuntimeError, match="git executable is not available"):
                tool._run_git_command(["status"])

    def test_run_git_command_redacts_credentials_from_git_error_output(self):
        tool = GitTool()
        git_error = (
            "fatal: could not read Username for "
            "'https://ghp_secret-token@github.com/octocat/Hello-World.git': auth failed"
        )

        with patch(
            "autodev.tools.git_tool.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["git", "clone"],
                returncode=128,
                stdout="",
                stderr=git_error,
            ),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                tool._run_git_command(
                    ["clone", "https://ghp_secret-token@github.com/test/repo.git"]
                )

        assert "ghp_secret-token" not in str(exc_info.value)
        assert "https://***@github.com/octocat/Hello-World.git" in str(exc_info.value)

    def test_clone_logs_sanitized_repo_url(self, caplog):
        tool = GitTool()
        repo_url = "https://ghp_secret-token@github.com/octocat/Hello-World.git"

        class FakeRepo:
            @staticmethod
            def clone_from(_repo_url, _dest_path):
                return None

        fake_git_module = type("FakeGitModule", (), {"Repo": FakeRepo})()

        with patch.dict(sys.modules, {"git": fake_git_module}):
            with caplog.at_level("INFO"):
                tool.clone(repo_url, "/tmp/hello-world")

        assert "ghp_secret-token" not in caplog.text
        assert "github.com/octocat/Hello-World.git" in caplog.text

    def test_clone_redacts_credentials_from_gitpython_error(self):
        tool = GitTool()
        repo_url = "https://ghp_secret-token@github.com/octocat/Hello-World.git"

        class FakeRepo:
            @staticmethod
            def clone_from(_repo_url, _dest_path):
                raise Exception(
                    "fatal: could not read Username for "
                    "'https://ghp_secret-token@github.com/octocat/Hello-World.git': auth failed"
                )

        fake_git_module = type("FakeGitModule", (), {"Repo": FakeRepo})()

        with patch.dict(sys.modules, {"git": fake_git_module}):
            with pytest.raises(RuntimeError) as exc_info:
                tool.clone(repo_url, "/tmp/hello-world")

        assert "ghp_secret-token" not in str(exc_info.value)
        assert "https://***@github.com/octocat/Hello-World.git" in str(exc_info.value)
