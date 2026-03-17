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
    validation_results: str = ""
    iteration: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def test_results(self) -> str:
        return self.validation_results

    @test_results.setter
    def test_results(self, value: str) -> None:
        self.validation_results = value


class Agent(ABC):
    """Abstract base class for all AutoDev agents."""

    def __init__(self, model_router: Any = None) -> None:
        self.model_router = model_router

    @abstractmethod
    def run(self, task: str, context: AgentContext) -> AgentContext:
        """Execute the agent's task and return an updated context."""
