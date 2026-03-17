"""ShellTool: safely execute shell commands with guardrail checks."""

from __future__ import annotations

import logging
import subprocess
from typing import Any

from autodev.core.supervisor import BLOCKED_PATTERNS
from autodev.tools.base import Tool

logger = logging.getLogger(__name__)


class ShellTool(Tool):
    """Executes shell commands after validating them against a blocklist."""

    def execute(self, input: dict[str, Any]) -> dict[str, Any]:
        """Execute *input['command']* and return stdout/stderr/returncode."""
        command = input.get("command", "")
        cwd = input.get("cwd")
        timeout = int(input.get("timeout", 60))
        return self.run(command, cwd=cwd, timeout=timeout)

    def run(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]:
        """Run *command* in a subprocess.

        Returns a dict with keys: stdout, stderr, returncode.
        Blocked commands are rejected without execution.
        """
        is_safe, reason = self._validate(command)
        if not is_safe:
            logger.warning("ShellTool blocked command %r: %s", command, reason)
            return {"stdout": "", "stderr": f"Blocked: {reason}", "returncode": 1}

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": "Command timed out", "returncode": 1}
        except Exception as exc:
            return {"stdout": "", "stderr": str(exc), "returncode": 1}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(command: str) -> tuple[bool, str]:
        lowered = command.lower()
        for pattern in BLOCKED_PATTERNS:
            if pattern.lower() in lowered:
                return False, f"Blocked pattern: '{pattern}'"
        return True, "ok"
