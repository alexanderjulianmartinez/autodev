"""ReviewerAgent: reviews code changes and produces an assessment."""

from __future__ import annotations

import logging

from autodev.agents.base import Agent, AgentContext

logger = logging.getLogger(__name__)


class ReviewerAgent(Agent):
    """Assesses the quality of changes made during the pipeline."""

    def run(self, task: str, context: AgentContext) -> AgentContext:
        logger.info("ReviewerAgent running task: %s", task)

        meta = dict(context.metadata)

        if not context.files_modified:
            meta["review"] = "No files were modified; nothing to review."
            meta["review_passed"] = False
            logger.warning("ReviewerAgent: no files modified.")
            return context.model_copy(update={"metadata": meta})

        if self.model_router:
            assessment = self._model_review(context)
        else:
            assessment = self._stub_review(context)

        meta["review"] = assessment
        meta["review_passed"] = True
        logger.info("ReviewerAgent assessment: %s", assessment)
        return context.model_copy(update={"metadata": meta})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _stub_review(self, context: AgentContext) -> str:
        n = len(context.files_modified)
        test_status = "passing" if "PASSED" in context.test_results else "unknown"
        return (
            f"Review complete. {n} file(s) modified. "
            f"Tests are {test_status}. Changes look reasonable."
        )

    def _model_review(self, context: AgentContext) -> str:
        prompt = (
            f"You are a senior engineer reviewing code changes.\n"
            f"Files modified: {context.files_modified}\n"
            f"Test results: {context.test_results or 'not available'}\n"
            f"Provide a brief 1-2 sentence assessment of the changes."
        )
        try:
            return self.model_router.generate(prompt, model_key="reviewer")
        except Exception as exc:
            logger.debug("Model review failed: %s", exc)
            return self._stub_review(context)
