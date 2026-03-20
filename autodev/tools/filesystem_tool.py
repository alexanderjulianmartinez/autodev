"""FilesystemTool: sandboxed file read/write operations."""

from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path
from typing import Any

from autodev.core.supervisor import Supervisor
from autodev.tools.base import Tool

logger = logging.getLogger(__name__)


class FilesystemTool(Tool):
    """Provides file operations sandboxed to a configured base path."""

    def __init__(
        self,
        base_path: str | None = None,
        supervisor: Supervisor | None = None,
    ) -> None:
        self.base_path = Path(base_path).resolve() if base_path else None
        self.supervisor = supervisor or Supervisor()

    def execute(self, input: dict[str, Any]) -> dict[str, Any]:
        action = input.get("action", "")
        if action == "read":
            return {"content": self.read_file(input["path"])}
        if action == "write":
            self.write_file(input["path"], input["content"])
            return {"ok": True}
        if action == "list":
            return {"files": self.list_files(input["path"], input.get("pattern", "*"))}
        raise ValueError(f"Unknown action: {action!r}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def read_file(self, path: str) -> str:
        resolved = self._resolve(path)
        logger.debug("Reading file: %s", resolved)
        return resolved.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> None:
        resolved = self._resolve(path)
        is_safe, reason = self.supervisor.validate_file_write(str(resolved))
        self.supervisor.record_decision(
            operation="file_write",
            target=str(resolved),
            allowed=is_safe,
            reason=reason,
            metadata={"base_path": str(self.base_path) if self.base_path else ""},
        )
        if not is_safe:
            raise PermissionError(reason)
        logger.debug("Writing file: %s", resolved)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")

    def list_files(self, dir_path: str, pattern: str = "*") -> list[str]:
        resolved = self._resolve(dir_path)
        matches: list[str] = []
        for root, _dirs, files in os.walk(resolved):
            for fname in files:
                if fnmatch.fnmatch(fname, pattern):
                    matches.append(os.path.join(root, fname))
        return matches

    def file_exists(self, path: str) -> bool:
        try:
            return self._resolve(path).exists()
        except (ValueError, OSError):
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve(self, path: str) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute() and self.base_path is not None:
            candidate = self.base_path / candidate
        target = candidate.resolve()
        if self.base_path is not None:
            try:
                target.relative_to(self.base_path)
            except ValueError as exc:
                raise ValueError(
                    f"Path {path!r} is outside the allowed base path {self.base_path!r}"
                ) from exc
        return target
