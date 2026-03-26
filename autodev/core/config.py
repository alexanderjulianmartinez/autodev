"""PipelineConfig: Pydantic model for AutoDev runtime configuration.

Config files are loaded from (first match wins):
  1. ./autodev.yaml   — project-level
  2. ./autodev.yml
  3. ~/.autodev/pipeline.yaml — user-level
  4. ~/.autodev/pipeline.yml

All fields are optional; omitting a field uses the documented safe default.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from autodev.core.schemas import IsolationMode

logger = logging.getLogger(__name__)

# Ordered search path used by PipelineConfig.discover()
_CONFIG_SEARCH_PATHS: list[Path] = [
    Path("autodev.yaml"),
    Path("autodev.yml"),
    Path.home() / ".autodev" / "pipeline.yaml",
    Path.home() / ".autodev" / "pipeline.yml",
]


class ConfigError(ValueError):
    """Raised when a config file cannot be read, contains invalid YAML,
    or fails Pydantic validation."""


class ValidationConfig(BaseModel):
    """Controls the validation phase behaviour."""

    model_config = ConfigDict(extra="forbid")

    breadth: str = Field(
        default="targeted",
        description=(
            "Validation breadth. "
            "'targeted' runs tests only for changed files; "
            "'broader-fallback' expands to the full suite if targeted fails."
        ),
    )
    stop_on_first_failure: bool = Field(
        default=True,
        description="Halt validation after the first failing command.",
    )
    commands: list[str] = Field(
        default_factory=list,
        description=(
            "Explicit validation commands to run. "
            "Empty list = auto-detect from repo structure (pytest, npm test, etc.)."
        ),
    )

    @field_validator("breadth")
    @classmethod
    def _valid_breadth(cls, v: str) -> str:
        allowed = {"targeted", "broader-fallback"}
        if v not in allowed:
            raise ValueError(f"breadth must be one of {sorted(allowed)!r}; got {v!r}")
        return v


class RetryConfig(BaseModel):
    """Controls retry policy for retryable phase failures."""

    model_config = ConfigDict(extra="forbid")

    max_retries: int = Field(
        default=0,
        ge=0,
        description="Maximum number of retries for a retryable failure. 0 = no retries.",
    )
    backoff_base: float = Field(
        default=2.0,
        gt=0,
        description=(
            "Exponential backoff base in seconds. "
            "Delay before attempt N = backoff_base × 2^(N-1)."
        ),
    )


class PipelineConfig(BaseModel):
    """Full runtime configuration for an AutoDev pipeline run.

    Example YAML::

        isolation_mode: snapshot
        max_iterations: 3
        dry_run: false

        validation:
          breadth: targeted
          stop_on_first_failure: true
          commands: []

        retry:
          max_retries: 0
          backoff_base: 2.0
    """

    model_config = ConfigDict(extra="forbid")

    isolation_mode: IsolationMode = Field(
        default=IsolationMode.SNAPSHOT,
        description="Workspace isolation strategy: snapshot, branch, or worktree.",
    )
    max_iterations: int = Field(
        default=3,
        ge=1,
        description="Maximum debug/repair iterations allowed per run.",
    )
    dry_run: bool = Field(
        default=False,
        description="Skip PR creation and other external side-effects.",
    )
    validation: ValidationConfig = Field(
        default_factory=ValidationConfig,
        description="Validation phase policy.",
    )
    retry: RetryConfig = Field(
        default_factory=RetryConfig,
        description="Retry policy for retryable failures.",
    )

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> "PipelineConfig":
        """Load and validate a PipelineConfig from a YAML file.

        Raises:
            ConfigError: if the file cannot be read, is not valid YAML,
                         or contains unknown or invalid fields.
        """
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"Cannot read config file {path}: {exc}") from exc
        return cls.from_yaml_str(text, source=str(path))

    @classmethod
    def from_yaml_str(
        cls, text: str, *, source: str = "<string>"
    ) -> "PipelineConfig":
        """Parse and validate a PipelineConfig from a YAML string.

        Raises:
            ConfigError: if the YAML is malformed or contains unknown/invalid fields.
        """
        import yaml
        from pydantic import ValidationError

        try:
            data: Any = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML in {source}: {exc}") from exc

        if not isinstance(data, dict):
            raise ConfigError(
                f"Config {source} must be a YAML mapping; got {type(data).__name__}"
            )

        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            errors = "; ".join(
                f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
                for e in exc.errors()
            )
            raise ConfigError(f"Invalid pipeline config in {source}: {errors}") from exc

    @classmethod
    def discover(cls, *, search_paths: Optional[list[Path]] = None) -> "PipelineConfig":
        """Return the first config found in the standard search path, else defaults.

        Search order (first file that exists wins):
          1. ./autodev.yaml
          2. ./autodev.yml
          3. ~/.autodev/pipeline.yaml
          4. ~/.autodev/pipeline.yml

        Args:
            search_paths: Override the default search list (mainly for testing).
        """
        paths = search_paths if search_paths is not None else _CONFIG_SEARCH_PATHS
        for candidate in paths:
            if candidate.exists():
                logger.debug("Loading pipeline config from %s", candidate)
                return cls.load(candidate)
        logger.debug("No pipeline config found; using safe defaults.")
        return cls()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def as_context_metadata(self) -> dict[str, Any]:
        """Return a dict of validation settings suitable for injection into AgentContext.metadata.

        Keys match what PhaseRegistry._resolve_validation_policy() reads:
          - validation_breadth
          - validation_stop_on_first_failure
          - validation_commands  (only included when non-empty)
        """
        meta: dict[str, Any] = {
            "validation_breadth": self.validation.breadth,
            "validation_stop_on_first_failure": self.validation.stop_on_first_failure,
        }
        if self.validation.commands:
            meta["validation_commands"] = list(self.validation.commands)
        return meta
