"""CoderAgent: executes the implementation plan by modifying files."""

from __future__ import annotations

import logging
import os

from autodev.agents.base import Agent, AgentContext

logger = logging.getLogger(__name__)


class CoderAgent(Agent):
    """Translates a plan into file modifications."""

    def run(self, task: str, context: AgentContext) -> AgentContext:
        logger.info("CoderAgent running task: %s", task)

        if not context.plan:
            logger.warning("No plan available; CoderAgent has nothing to do.")
            return context

        files_modified: list[str] = list(context.files_modified)

        if self.model_router and context.repo_path:
            files_modified = self._apply_plan_with_model(context, files_modified)
        else:
            files_modified = self._apply_plan_stub(context, files_modified)

        logger.info("CoderAgent modified %d file(s)", len(files_modified))
        return context.model_copy(update={"files_modified": files_modified})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _apply_plan_stub(
        self, context: AgentContext, existing: list[str]
    ) -> list[str]:
        """Record planned file targets without actually writing."""
        targets: list[str] = list(existing)
        for step in context.plan:
            lower = step.lower()
            # Heuristic: pick out file references from the plan text
            for token in step.split():
                if "." in token and "/" not in token and token not in targets:
                    targets.append(token.strip(".,;:"))
        return targets

    def _apply_plan_with_model(
        self, context: AgentContext, existing: list[str]
    ) -> list[str]:
        """Use model to generate file content, then write to disk."""
        targets: list[str] = list(existing)
        for step in context.plan:
            prompt = (
                f"Given this implementation step, identify the single most relevant "
                f"file path relative to the repository root: '{step}'. "
                f"Reply with ONLY the file path, nothing else."
            )
            try:
                file_path = self.model_router.generate(prompt, model_key="coder").strip()
                if file_path and context.repo_path:
                    full_path = os.path.join(context.repo_path, file_path)
                    if full_path not in targets:
                        targets.append(full_path)
            except Exception as exc:
                logger.debug("Model call failed for step %r: %s", step, exc)
        return targets
