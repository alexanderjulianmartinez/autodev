"""Base tool interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Abstract base class for all AutoDev tools."""

    @abstractmethod
    def execute(self, input: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool with the given input and return output."""
