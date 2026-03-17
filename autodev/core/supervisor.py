"""Supervisor: safety guardrails and iteration limits."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Shell patterns that must never be executed.
BLOCKED_PATTERNS: list[str] = [
    "rm -rf /",
    "sudo",
    "mkfs",
    "dd if=",
    ":(){:",      # fork bomb
    "chmod 777 /",
    "wget http",  # network exfiltration helpers
    "curl http",
]


class Supervisor:
    """Validates commands and enforces execution limits."""

    def __init__(self, max_iterations: int = 3) -> None:
        self.max_iterations = max_iterations
        self._iteration_count: int = 0

    # ------------------------------------------------------------------
    # Command safety
    # ------------------------------------------------------------------

    def validate_command(self, cmd: str) -> tuple[bool, str]:
        """Return (is_safe, reason).

        A command is considered unsafe if it matches any blocked pattern.
        """
        lowered = cmd.lower()
        for pattern in BLOCKED_PATTERNS:
            if pattern.lower() in lowered:
                reason = f"Blocked pattern detected: '{pattern}'"
                logger.warning("Supervisor rejected command %r — %s", cmd, reason)
                return False, reason
        return True, "ok"

    # ------------------------------------------------------------------
    # Iteration limits
    # ------------------------------------------------------------------

    def check_iteration_limit(self) -> bool:
        """Return True if the iteration limit has been reached."""
        return self._iteration_count >= self.max_iterations

    def increment(self) -> None:
        """Increment the iteration counter."""
        self._iteration_count += 1

    def reset(self) -> None:
        """Reset the iteration counter."""
        self._iteration_count = 0

    @property
    def iteration_count(self) -> int:
        return self._iteration_count
