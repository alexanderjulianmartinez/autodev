"""Tests for tool components."""

import os
import tempfile

import pytest

from autodev.core.state_store import FileStateStore
from autodev.core.supervisor import Supervisor
from autodev.tools.filesystem_tool import FilesystemTool
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

    def test_outside_base_path_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FilesystemTool(base_path=tmpdir)
            with pytest.raises(ValueError, match="outside"):
                tool.read_file("/etc/passwd")

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
