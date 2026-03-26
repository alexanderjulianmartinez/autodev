"""IntegrationsConfig: Pydantic model for declaring which provider to use per integration type.

Configuration lives in ``integrations.yaml`` (or an ``integrations:`` section of
``autodev.yaml``).  All integration types are optional; omitting one disables it.

Example YAML::

    git:
      provider: github
      settings:
        token: "${GITHUB_TOKEN}"

    issue_tracker:
      provider: github_issues
      settings:
        token: "${GITHUB_TOKEN}"

    ci:
      provider: github_actions
      settings:
        token: "${GITHUB_TOKEN}"

    monitoring:
      provider: prometheus
      settings:
        base_url: "http://prometheus:9090"

Or embedded inside ``autodev.yaml``::

    integrations:
      git:
        provider: github
        settings:
          token: "${GITHUB_TOKEN}"
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from autodev.core.config import ConfigError

logger = logging.getLogger(__name__)

_CONFIG_SEARCH_PATHS: list[Path] = [
    Path("integrations.yaml"),
    Path("integrations.yml"),
    Path.home() / ".autodev" / "integrations.yaml",
    Path.home() / ".autodev" / "integrations.yml",
]


class ProviderConfig(BaseModel):
    """Configuration for one provider in one integration slot."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(
        description="Provider identifier, e.g. 'github', 'linear', 'slack'."
    )
    settings: dict[str, str] = Field(
        default_factory=dict,
        description="Provider-specific key/value settings (tokens, base URLs, etc.).",
    )


class IntegrationsConfig(BaseModel):
    """Top-level integration configuration.

    Each field is one integration type.  Omit a field to disable that type;
    the registry will raise ``LookupError`` if runtime code requests a
    capability it owns.
    """

    model_config = ConfigDict(extra="forbid")

    git: Optional[ProviderConfig] = Field(
        default=None,
        description="Git-hosting provider (repository, branch, PR, diff, clone).",
    )
    issue_tracker: Optional[ProviderConfig] = Field(
        default=None,
        description="Issue-tracking provider (fetch, create, update, list issues).",
    )
    ci: Optional[ProviderConfig] = Field(
        default=None,
        description="CI/CD provider (fetch runs, trigger runs, list runs).",
    )
    monitoring: Optional[ProviderConfig] = Field(
        default=None,
        description="Observability provider (alerts, metrics queries).",
    )
    messaging: Optional[ProviderConfig] = Field(
        default=None,
        description="Messaging provider (send and fetch messages).",
    )
    docs: Optional[ProviderConfig] = Field(
        default=None,
        description="Documentation provider (fetch, update, search documents).",
    )

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml_str(
        cls, text: str, *, source: str = "<string>"
    ) -> "IntegrationsConfig":
        """Parse and validate from a YAML string.

        The YAML may be:
        - a direct mapping of integration types (``git:``, ``ci:``, …), or
        - a mapping with a top-level ``integrations:`` key (as embedded in
          ``autodev.yaml``).

        Raises:
            ConfigError: on malformed YAML or invalid/unknown fields.
        """
        import yaml
        from pydantic import ValidationError

        try:
            data: Any = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML in {source}: {exc}") from exc

        if not isinstance(data, dict):
            raise ConfigError(
                f"Integration config {source} must be a YAML mapping; "
                f"got {type(data).__name__}"
            )

        # Unwrap an optional top-level ``integrations:`` key
        if "integrations" in data and isinstance(data.get("integrations"), dict):
            data = data["integrations"]

        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            errors = "; ".join(
                f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
                for e in exc.errors()
            )
            raise ConfigError(
                f"Invalid integration config in {source}: {errors}"
            ) from exc

    @classmethod
    def load(cls, path: str | Path) -> "IntegrationsConfig":
        """Load and validate from a YAML file.

        Raises:
            ConfigError: if the file cannot be read or is invalid.
        """
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(
                f"Cannot read integration config {path}: {exc}"
            ) from exc
        return cls.from_yaml_str(text, source=str(path))

    @classmethod
    def discover(
        cls, *, search_paths: Optional[list[Path]] = None
    ) -> "IntegrationsConfig":
        """Return the first config found in the standard search path, else all-disabled defaults.

        Search order (first existing file wins):
          1. ``./integrations.yaml``
          2. ``./integrations.yml``
          3. ``~/.autodev/integrations.yaml``
          4. ``~/.autodev/integrations.yml``

        Args:
            search_paths: Override the default search list (mainly for testing).
        """
        paths = search_paths if search_paths is not None else _CONFIG_SEARCH_PATHS
        for candidate in paths:
            if candidate.exists():
                logger.debug("Loading integration config from %s", candidate)
                return cls.load(candidate)
        logger.debug("No integration config found; all integration types disabled.")
        return cls()
