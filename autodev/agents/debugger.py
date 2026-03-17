"""DebuggerAgent: analyzes test failures and suggests patches."""

from __future__ import annotations

import logging

from autodev.agents.base import Agent, AgentContext

logger = logging.getLogger(__name__)


class DebuggerAgent(Agent):
    """Reads test failure output and proposes fixes."""

    def run(self, task: str, context: AgentContext) -> AgentContext:
        logger.info("DebuggerAgent running task: %s", task)

        new_iteration = context.iteration + 1
        metadata = dict(context.metadata)

        if context.test_results:
            logger.info("Analyzing test results for patches...")
            metadata["debug_suggestion"] = (
                f"Patch attempt #{new_iteration}: review failing tests in test_results."
            )
        else:
            metadata["debug_suggestion"] = "No test results available to analyze."

        context = context.model_copy(update={"iteration": new_iteration, "metadata": metadata})
        return context
