"""Base agent interface and shared context model."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class AgentContext(BaseModel):
    """Shared context passed between pipeline stages."""

    issue_url: str = ""
    repo_path: str = ""
    plan: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    test_results: str = ""
    iteration: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class Agent(ABC):
    """Abstract base class for all AutoDev agents."""

    def __init__(self, model_router: Any = None) -> None:
        self.model_router = model_router

    @abstractmethod
    def run(self, task: str, context: AgentContext) -> AgentContext:
        """Execute the agent's task and return an updated context."""
