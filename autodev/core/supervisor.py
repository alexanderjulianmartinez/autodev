"""Supervisor: safety guardrails and iteration limits."""

from __future__ import annotations

import logging
from pathlib import PurePosixPath

from autodev.core.schemas import utc_now
from autodev.core.state_store import FileStateStore

logger = logging.getLogger(__name__)

# Shell patterns that must never be executed.
BLOCKED_PATTERNS: list[str] = [
    "rm -rf /",
    "sudo",
    "mkfs",
    "dd if=",
    ":(){:",  # fork bomb
    "chmod 777 /",
    "wget http",  # network exfiltration helpers
    "curl http",
]

BLOCKED_WRITE_PATH_PARTS: set[str] = {
    ".git",
    ".ssh",
}

BLOCKED_SYSTEM_WRITE_PREFIXES: list[str] = [
    "/etc",
    "/bin",
    "/usr/bin",
    "/system",
]

BLOCKED_WINDOWS_WRITE_PREFIXES: list[str] = [
    "c:/windows",
    "c:/windows/system32",
    "c:/program files",
    "c:/program files (x86)",
    "c:/programdata/ssh",
]

BLOCKED_WRITE_FILENAMES: set[str] = {
    ".git",
    ".bashrc",
    ".zshrc",
    ".gitconfig",
    "authorized_keys",
}


class Supervisor:
    """Validates commands and enforces execution limits."""

    def __init__(
        self,
        max_iterations: int = 3,
        *,
        state_store: FileStateStore | None = None,
        report_name: str = "guardrails",
    ) -> None:
        self.max_iterations = max_iterations
        self._iteration_count: int = 0
        self._state_store = state_store
        self._report_name = report_name

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

    def validate_file_write(self, path: str) -> tuple[bool, str]:
        """Return (is_safe, reason) for a prospective file write."""
        normalized = path.replace("\\", "/").lower()
        path_parts = {part for part in PurePosixPath(normalized).parts if part not in {"/", ""}}

        for path_part in BLOCKED_WRITE_PATH_PARTS:
            if path_part in path_parts:
                reason = f"Blocked file write path part: '{path_part}'"
                logger.warning("Supervisor rejected file write %r — %s", path, reason)
                return False, reason

        blocked_prefix = self._blocked_system_write_prefix(normalized)
        if blocked_prefix is not None:
            reason = f"Blocked file write path: '{blocked_prefix}'"
            logger.warning("Supervisor rejected file write %r — %s", path, reason)
            return False, reason

        filename = normalized.rsplit("/", maxsplit=1)[-1]
        if filename in BLOCKED_WRITE_FILENAMES:
            reason = f"Blocked file write name: '{filename}'"
            logger.warning("Supervisor rejected file write %r — %s", path, reason)
            return False, reason

        return True, "ok"

    def _blocked_system_write_prefix(self, normalized_path: str) -> str | None:
        for prefix in [*BLOCKED_SYSTEM_WRITE_PREFIXES, *BLOCKED_WINDOWS_WRITE_PREFIXES]:
            if normalized_path == prefix or normalized_path.startswith(f"{prefix}/"):
                return prefix
        return None

    def record_decision(
        self,
        *,
        operation: str,
        target: str,
        allowed: bool,
        reason: str,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Persist and return a structured guardrail decision."""
        entry: dict[str, object] = {
            "recorded_at": utc_now().isoformat(),
            "operation": operation,
            "target": target,
            "allowed": allowed,
            "reason": reason,
            "metadata": dict(metadata or {}),
        }
        if self._state_store is not None:
            self._state_store.append_report_entry(self._report_name, entry)
        return entry

    def configure_reporting(
        self,
        *,
        state_store: FileStateStore | None = None,
        report_name: str | None = None,
    ) -> None:
        """Update persistence settings for future guardrail decisions."""
        if state_store is not None:
            self._state_store = state_store
        if report_name is not None:
            self._report_name = report_name

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
