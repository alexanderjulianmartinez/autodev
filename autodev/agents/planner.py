"""PlannerAgent: generates a structured implementation plan."""

from __future__ import annotations

import logging

from autodev.agents.base import Agent, AgentContext

logger = logging.getLogger(__name__)


class PlannerAgent(Agent):
    """Produces a structured, step-by-step implementation plan."""

    def run(self, task: str, context: AgentContext) -> AgentContext:
        logger.info("PlannerAgent running task: %s", task)

        if self.model_router:
            prompt = self._build_prompt(context)
            try:
                response = self.model_router.generate(prompt, model_key="planner")
                plan = self._parse_plan(response)
            except Exception as exc:
                logger.warning("Model call failed (%s); using default plan.", exc)
                plan = self._default_plan(context)
        else:
            plan = self._default_plan(context)

        logger.info("Plan generated with %d step(s)", len(plan))
        return context.model_copy(update={"plan": plan})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, context: AgentContext) -> str:
        issue_title = context.metadata.get("issue_title", "the issue")
        issue_body = context.metadata.get("issue_body", "")
        return (
            f"You are an expert software engineer. Generate a concise, numbered "
            f"implementation plan for the following GitHub issue.\n\n"
            f"Title: {issue_title}\n\nDescription:\n{issue_body}\n\n"
            f"Return ONLY a numbered list of steps, one per line."
        )

    def _parse_plan(self, response: str) -> list[str]:
        lines = [line.strip() for line in response.splitlines() if line.strip()]
        return lines if lines else self._default_plan(AgentContext())

    def _default_plan(self, context: AgentContext) -> list[str]:
        issue_title = context.metadata.get("issue_title", "the feature")
        return [
            f"1. Analyze the repository structure relevant to: {issue_title}",
            "2. Identify files that need modification",
            "3. Implement the required changes",
            "4. Add or update tests to cover the changes",
            "5. Verify all tests pass",
        ]
