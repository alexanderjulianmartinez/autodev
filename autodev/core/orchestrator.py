"""Orchestrator: pipeline state machine."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class PipelineState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Orchestrator:
    """Manages pipeline execution state and passes context between stages."""

    def __init__(self) -> None:
        self._state: PipelineState = PipelineState.PENDING
        self._stage_outputs: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def execute(self, pipeline_config: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Execute a pipeline configuration with the given starting context.

        Returns the accumulated context after all stages complete.
        """
        self._state = PipelineState.RUNNING
        current_context = dict(context)

        stages = pipeline_config.get("stages", [])
        logger.info("Orchestrator starting pipeline with %d stage(s)", len(stages))

        try:
            for stage in stages:
                stage_name = stage.get("name", "unnamed")
                logger.info("Executing stage: %s", stage_name)
                # In a real run agents would be invoked here; we persist the
                # stage marker so callers can inspect what ran.
                self._stage_outputs[stage_name] = {"status": "completed"}
                current_context["last_stage"] = stage_name

            self._state = PipelineState.COMPLETED
        except Exception as exc:
            self._state = PipelineState.FAILED
            current_context["error"] = str(exc)
            logger.error("Pipeline failed at stage %r: %s", current_context.get("last_stage"), exc)

        return current_context

    # ------------------------------------------------------------------
    # State inspection
    # ------------------------------------------------------------------

    @property
    def state(self) -> PipelineState:
        return self._state

    @property
    def stage_outputs(self) -> dict[str, Any]:
        return dict(self._stage_outputs)

    def reset(self) -> None:
        self._state = PipelineState.PENDING
        self._stage_outputs.clear()
