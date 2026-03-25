"""Failure classification helpers for runtime phase outcomes."""

from __future__ import annotations

from typing import Any

from autodev.core.schemas import FailureClass, FailureDetail, PhaseName

RETRYABLE_KEYWORDS = (
    "timeout",
    "timed out",
    "temporary",
    "temporarily",
    "transient",
    "connection reset",
    "connection aborted",
    "network",
    "rate limit",
    "service unavailable",
)
POLICY_KEYWORDS = (
    "blocked:",
    "blocked pattern",
    "blocked file write",
    "approval",
    "security",
    "compliance",
    "policy",
)
ENVIRONMENT_KEYWORDS = (
    "command not found",
    "not found",
    "no such file or directory",
    "missing",
    "credential",
    "credentials",
    "api key",
    "executable",
    "git is not installed",
    "repository path is unavailable",
)
MANUAL_INTERVENTION_KEYWORDS = (
    "merge conflict",
    "ambiguous",
    "manual intervention",
    "unsafe action",
    "unrecoverable",
    "repo state",
    "conflict",
)
RETRYABLE_EXCEPTIONS = (TimeoutError, ConnectionError, BrokenPipeError)
ENVIRONMENT_EXCEPTIONS = (FileNotFoundError, ImportError, ModuleNotFoundError, OSError)


def classify_phase_failure(
    phase: PhaseName,
    *,
    message: str = "",
    exception: Exception | None = None,
    metadata: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
) -> FailureDetail:
    """Classify a failed phase into a durable failure detail."""

    payload_metadata = dict(metadata or {})
    payload_metrics = dict(metrics or {})
    candidate_messages = [
        str(message or "").strip(),
        str(payload_metadata.get("implementation_error", "")).strip(),
        str(payload_metadata.get("review", "")).strip(),
        str(payload_metadata.get("validation_results", "")).strip(),
        str(exception or "").strip(),
    ]
    combined_message = "\n".join(part for part in candidate_messages if part).strip()
    lowered = combined_message.lower()

    if _has_keyword(lowered, POLICY_KEYWORDS):
        failure_class = FailureClass.POLICY_FAILURE
    elif _has_keyword(lowered, MANUAL_INTERVENTION_KEYWORDS):
        failure_class = FailureClass.MANUAL_INTERVENTION
    elif exception is not None and isinstance(exception, RETRYABLE_EXCEPTIONS):
        failure_class = FailureClass.RETRYABLE
    elif _has_keyword(lowered, RETRYABLE_KEYWORDS):
        failure_class = FailureClass.RETRYABLE
    elif exception is not None and _is_environment_exception(exception, lowered):
        failure_class = FailureClass.ENVIRONMENT_FAILURE
    elif _has_keyword(lowered, ENVIRONMENT_KEYWORDS):
        failure_class = FailureClass.ENVIRONMENT_FAILURE
    elif phase == PhaseName.VALIDATE:
        failure_class = FailureClass.VALIDATION_FAILURE
    else:
        failure_class = FailureClass.MANUAL_INTERVENTION

    return FailureDetail(
        failure_class=failure_class,
        message=combined_message or f"{phase.value} phase failed",
        details={
            "phase": phase.value,
            "exception_type": type(exception).__name__ if exception is not None else "",
            "metrics": payload_metrics,
        },
    )


def _has_keyword(haystack: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in haystack for keyword in keywords)


def _is_environment_exception(exception: Exception, lowered_message: str) -> bool:
    if isinstance(exception, PermissionError):
        return not _has_keyword(lowered_message, POLICY_KEYWORDS)
    return isinstance(exception, ENVIRONMENT_EXCEPTIONS)