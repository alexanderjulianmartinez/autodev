"""Shared domain models for the AutoDev integration layer.

These models represent cross-cutting external entities that are not owned by
a single integration type.  They are designed to be produced *from* the
typed response models in each integration module (e.g. ``CIRunInfo``,
``AlertInfo``) and consumed by core runtime logic.

``ErrorEvent``
    A normalized error signal from any source: a CI run failure, a monitoring
    alert, a tool execution error, or a runtime exception.  Core logic (e.g.
    the failure classifier) operates on ``ErrorEvent`` instead of importing
    provider-specific types.

``EntityRef``
    A lightweight cross-system pointer.  Adapters attach one to their response
    models so that callers can trace an entity back to its origin without
    importing the adapter.
"""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from autodev.core.schemas import AutoDevModel


class EntityRef(AutoDevModel):
    """A cross-system pointer to an external entity.

    Used by adapters to attach provenance metadata to any response without
    requiring the caller to know the provider type.

    Example::

        ref = EntityRef(
            provider_id="github",
            entity_type="issue",
            entity_id="owner/repo#42",
            url="https://github.com/owner/repo/issues/42",
            display="owner/repo#42",
        )
    """

    provider_id: str = Field(
        description="Identifies the provider (e.g. 'github', 'linear', 'jira')."
    )
    entity_type: str = Field(
        description=(
            "Entity kind within the provider: 'issue', 'pull_request', "
            "'ci_run', 'alert', 'document', 'message'."
        )
    )
    entity_id: str = Field(description="Provider-local identifier (number, slug, UUID, etc.).")
    url: str = Field(default="", description="Canonical URL for the entity.")
    display: str = Field(
        default="",
        description="Human-readable label (e.g. 'owner/repo#42', 'Run #1234').",
    )


class ErrorEvent(AutoDevModel):
    """A normalized error signal from any integration source.

    Adapters construct ``ErrorEvent`` instances from provider-specific error
    payloads (failing CI jobs, firing alerts, caught exceptions) so that core
    logic can classify and route errors without importing provider types.

    Severity levels (``severity`` field):
      - ``"critical"`` — service down / data loss risk
      - ``"error"``    — operation failed, needs attention
      - ``"warning"``  — degraded state, may self-recover
      - ``"info"``     — informational signal, no action required

    Category values (``category`` field):
      - ``"test_failure"``   — one or more tests failed
      - ``"lint_error"``     — linting or type-check failure
      - ``"build_error"``    — compilation or packaging failure
      - ``"runtime_error"``  — uncaught exception at runtime
      - ``"alert"``          — monitoring/observability alert
      - ``"timeout"``        — operation timed out
      - ``"other"``          — uncategorized
    """

    event_id: str = Field(description="Unique identifier for this event.")
    source: str = Field(
        description=(
            "Integration type that produced this event: 'ci', 'monitoring', "
            "'runtime', 'git', 'issue_tracker', 'messaging', 'docs'."
        )
    )
    severity: str = Field(description="Severity level: 'critical', 'error', 'warning', or 'info'.")
    category: str = Field(
        description=(
            "Error category: 'test_failure', 'lint_error', 'build_error', "
            "'runtime_error', 'alert', 'timeout', or 'other'."
        )
    )
    summary: str = Field(description="One-line human-readable description.")
    details: str = Field(
        default="", description="Extended description, log excerpt, or error message."
    )
    stack_trace: str = Field(default="", description="Stack trace, if available.")
    occurred_at: str = Field(default="", description="ISO-8601 timestamp when the error occurred.")
    source_ref: Optional[EntityRef] = Field(
        default=None,
        description="Pointer back to the source entity (CI run, alert, etc.).",
    )
    labels: dict[str, str] = Field(
        default_factory=dict,
        description="Arbitrary key/value labels for filtering and routing.",
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Provider-specific fields that do not fit the standard schema.",
    )
