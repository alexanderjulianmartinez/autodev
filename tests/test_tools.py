"""Tests for tool components."""

import os
import tempfile

import pytest

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
