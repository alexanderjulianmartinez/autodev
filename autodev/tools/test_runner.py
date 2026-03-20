"""TestRunner: runs a test suite in a subprocess and returns results."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import Any

from autodev.core.supervisor import Supervisor
from autodev.tools.base import Tool

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    passed: bool
    output: str
    error: str
    return_code: int


class TestRunner(Tool):
    """Executes a test suite and returns structured results."""

    __test__ = False

    DEFAULT_TIMEOUT = 120

    def __init__(self, supervisor: Supervisor | None = None) -> None:
        self.supervisor = supervisor or Supervisor()

    def execute(self, input: dict[str, Any]) -> dict[str, Any]:
        result = self.run(
            repo_path=input.get("repo_path", "."),
            test_command=input.get("test_command", "pytest"),
        )
        return {
            "passed": result.passed,
            "output": result.output,
            "error": result.error,
            "return_code": result.return_code,
        }

    def run(self, repo_path: str = ".", test_command: str = "pytest") -> TestResult:
        """Run *test_command* in *repo_path* and return a TestResult."""
        logger.info("Running tests in %r with command %r", repo_path, test_command)
        is_safe, reason = self.supervisor.validate_command(test_command)
        self.supervisor.record_decision(
            operation="test_command",
            target=test_command,
            allowed=is_safe,
            reason=reason,
            metadata={"repo_path": repo_path},
        )
        if not is_safe:
            return TestResult(
                passed=False,
                output="",
                error=f"Blocked: {reason}",
                return_code=1,
            )
        try:
            proc = subprocess.run(
                test_command,
                shell=True,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=self.DEFAULT_TIMEOUT,
            )
            return TestResult(
                passed=proc.returncode == 0,
                output=proc.stdout,
                error=proc.stderr,
                return_code=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            return TestResult(
                passed=False,
                output="",
                error="Test run timed out",
                return_code=1,
            )
        except Exception as exc:
            return TestResult(passed=False, output="", error=str(exc), return_code=1)
