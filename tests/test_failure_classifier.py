"""Tests for failure classification heuristics."""

from __future__ import annotations

from autodev.core.failure_classifier import classify_phase_failure
from autodev.core.schemas import FailureClass, PhaseName


def test_classifies_retryable_failure():
    failure = classify_phase_failure(
        PhaseName.PLAN,
        message="model request timed out while contacting provider",
        exception=TimeoutError("timed out"),
    )

    assert failure.failure_class == FailureClass.RETRYABLE


def test_classifies_validation_failure():
    failure = classify_phase_failure(
        PhaseName.VALIDATE,
        message="Validation failed after 1 command(s).\nassertion failed",
    )

    assert failure.failure_class == FailureClass.VALIDATION_FAILURE


def test_classifies_policy_failure():
    failure = classify_phase_failure(
        PhaseName.IMPLEMENT,
        message="Blocked file write path: '/etc'",
    )

    assert failure.failure_class == FailureClass.POLICY_FAILURE


def test_classifies_environment_failure():
    failure = classify_phase_failure(
        PhaseName.IMPLEMENT,
        message="git is not installed",
        exception=FileNotFoundError("git is not installed"),
    )

    assert failure.failure_class == FailureClass.ENVIRONMENT_FAILURE


def test_classifies_manual_intervention_failure():
    failure = classify_phase_failure(
        PhaseName.IMPLEMENT,
        message="Repository is in a merge conflict and requires manual intervention",
    )

    assert failure.failure_class == FailureClass.MANUAL_INTERVENTION