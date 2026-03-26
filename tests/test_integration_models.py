"""Tests for autodev.integrations.models and autodev.integrations.normalize (AD-030)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autodev.integrations import EntityRef, ErrorEvent
from autodev.integrations.normalize import (
    extract_section_items,
    extract_task_list_items,
    infer_validation_commands,
    normalize_labels,
    normalize_priority,
    normalize_status,
    slugify,
)


# ---------------------------------------------------------------------------
# EntityRef
# ---------------------------------------------------------------------------


class TestEntityRef:
    def test_minimal(self):
        ref = EntityRef(
            provider_id="github", entity_type="issue", entity_id="owner/repo#42"
        )
        assert ref.provider_id == "github"
        assert ref.url == ""
        assert ref.display == ""

    def test_full(self):
        ref = EntityRef(
            provider_id="github",
            entity_type="pull_request",
            entity_id="owner/repo#7",
            url="https://github.com/owner/repo/pull/7",
            display="owner/repo#7",
        )
        assert ref.url.endswith("/7")
        assert ref.display == "owner/repo#7"

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            EntityRef(
                provider_id="github",
                entity_type="issue",
                entity_id="42",
                unknown="x",
            )


# ---------------------------------------------------------------------------
# ErrorEvent
# ---------------------------------------------------------------------------


class TestErrorEvent:
    def test_minimal(self):
        event = ErrorEvent(
            event_id="ev-1",
            source="ci",
            severity="error",
            category="test_failure",
            summary="pytest failed: 3 tests failed",
        )
        assert event.details == ""
        assert event.stack_trace == ""
        assert event.source_ref is None
        assert event.labels == {}

    def test_with_source_ref(self):
        ref = EntityRef(
            provider_id="github", entity_type="ci_run", entity_id="12345"
        )
        event = ErrorEvent(
            event_id="ev-2",
            source="ci",
            severity="critical",
            category="build_error",
            summary="Build failed",
            source_ref=ref,
        )
        assert event.source_ref is not None
        assert event.source_ref.entity_id == "12345"

    def test_with_labels(self):
        event = ErrorEvent(
            event_id="ev-3",
            source="monitoring",
            severity="warning",
            category="alert",
            summary="High error rate",
            labels={"env": "prod", "service": "api"},
        )
        assert event.labels["env"] == "prod"

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ErrorEvent(
                event_id="ev-4",
                source="ci",
                severity="error",
                category="other",
                summary="x",
                unknown_field="y",
            )

    def test_severity_and_category_stored_as_given(self):
        """No validation on severity/category values — adapters own the contract."""
        event = ErrorEvent(
            event_id="ev-5",
            source="runtime",
            severity="info",
            category="other",
            summary="startup complete",
        )
        assert event.severity == "info"
        assert event.category == "other"


# ---------------------------------------------------------------------------
# normalize_priority
# ---------------------------------------------------------------------------


class TestNormalizePriority:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("p0", "critical"),
            ("P0", "critical"),
            ("CRITICAL", "critical"),
            ("critical", "critical"),
            ("urgent", "critical"),
            ("blocker", "critical"),
            ("priority:p0", "critical"),
            ("p1", "high"),
            ("HIGH", "high"),
            ("major", "high"),
            ("priority:p1", "high"),
            ("p2", "medium"),
            ("medium", "medium"),
            ("normal", "medium"),
            ("priority:p2", "medium"),
            ("p3", "low"),
            ("low", "low"),
            ("minor", "low"),
            ("trivial", "low"),
            ("priority:p3", "low"),
            ("unknown", "medium"),
            ("", "medium"),
            (None, "medium"),
        ],
    )
    def test_maps_correctly(self, raw, expected):
        assert normalize_priority(raw) == expected

    def test_whitespace_stripped(self):
        assert normalize_priority("  p0  ") == "critical"


# ---------------------------------------------------------------------------
# normalize_status
# ---------------------------------------------------------------------------


class TestNormalizeStatus:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("open", "open"),
            ("OPEN", "open"),
            ("Todo", "open"),
            ("todo", "open"),
            ("backlog", "open"),
            ("new", "open"),
            ("pending", "open"),
            ("in_progress", "in_progress"),
            ("IN PROGRESS", "in_progress"),
            ("in progress", "in_progress"),
            ("active", "in_progress"),
            ("wip", "in_progress"),
            ("in review", "in_progress"),
            ("closed", "closed"),
            ("CLOSED", "closed"),
            ("done", "closed"),
            ("resolved", "closed"),
            ("completed", "closed"),
            ("merged", "closed"),
            ("success", "closed"),
            ("failed", "failed"),
            ("failure", "failed"),
            ("error", "failed"),
            ("cancelled", "failed"),
            ("canceled", "failed"),
            ("timed_out", "failed"),
            ("unknown-status", "open"),
            ("", "open"),
            (None, "open"),
        ],
    )
    def test_maps_correctly(self, raw, expected):
        assert normalize_status(raw) == expected

    def test_whitespace_stripped(self):
        assert normalize_status("  done  ") == "closed"


# ---------------------------------------------------------------------------
# normalize_labels
# ---------------------------------------------------------------------------


class TestNormalizeLabels:
    def test_empty_list(self):
        assert normalize_labels([]) == []

    def test_none_returns_empty(self):
        assert normalize_labels(None) == []

    def test_lowercases(self):
        assert normalize_labels(["Bug", "ENHANCEMENT"]) == ["bug", "enhancement"]

    def test_strips_whitespace(self):
        assert normalize_labels([" bug ", "  fix  "]) == ["bug", "fix"]

    def test_deduplicates_preserving_order(self):
        assert normalize_labels(["Bug", "BUG", "bug", "fix"]) == ["bug", "fix"]

    def test_skips_empty_strings(self):
        assert normalize_labels(["", "  ", "bug"]) == ["bug"]

    def test_preserves_order_of_first_occurrence(self):
        result = normalize_labels(["z", "a", "z", "b"])
        assert result == ["z", "a", "b"]


# ---------------------------------------------------------------------------
# extract_task_list_items
# ---------------------------------------------------------------------------


class TestExtractTaskListItems:
    def test_unchecked_items(self):
        body = "- [ ] Write tests\n- [ ] Update docs\n"
        assert extract_task_list_items(body) == ["Write tests", "Update docs"]

    def test_checked_items_included(self):
        body = "- [x] Write tests\n- [X] Update docs\n"
        assert extract_task_list_items(body) == ["Write tests", "Update docs"]

    def test_mixed_checked_unchecked(self):
        body = "- [ ] Write tests\n- [x] Already done\n"
        result = extract_task_list_items(body)
        assert "Write tests" in result
        assert "Already done" in result

    def test_asterisk_bullet(self):
        body = "* [ ] Item one\n* [x] Item two\n"
        assert extract_task_list_items(body) == ["Item one", "Item two"]

    def test_strips_item_text(self):
        body = "- [ ]   padded text   \n"
        assert extract_task_list_items(body) == ["padded text"]

    def test_non_task_list_lines_ignored(self):
        body = "## Section\n\nSome prose.\n\n- [ ] Task one\n\nMore prose.\n"
        assert extract_task_list_items(body) == ["Task one"]

    def test_empty_body(self):
        assert extract_task_list_items("") == []

    def test_none_body(self):
        assert extract_task_list_items(None) == []


# ---------------------------------------------------------------------------
# extract_section_items
# ---------------------------------------------------------------------------


class TestExtractSectionItems:
    _BODY = (
        "## Overview\n\nSome intro text.\n\n"
        "## Acceptance Criteria\n\n"
        "- All tests pass\n"
        "- No regressions\n\n"
        "## Notes\n\n"
        "- Unrelated note\n"
    )

    def test_extracts_named_section(self):
        result = extract_section_items(self._BODY, {"acceptance criteria"})
        assert result == ["All tests pass", "No regressions"]

    def test_section_stops_at_next_heading(self):
        result = extract_section_items(self._BODY, {"acceptance criteria"})
        assert "Unrelated note" not in result

    def test_case_insensitive_match(self):
        body = "## ACCEPTANCE CRITERIA\n- Item\n"
        result = extract_section_items(body, {"acceptance criteria"})
        assert result == ["Item"]

    def test_multiple_candidate_names(self):
        body = "## Changes\n- Do this\n"
        result = extract_section_items(body, {"acceptance criteria", "changes"})
        assert result == ["Do this"]

    def test_missing_section_returns_empty(self):
        result = extract_section_items(self._BODY, {"does not exist"})
        assert result == []

    def test_empty_body(self):
        assert extract_section_items("", {"acceptance criteria"}) == []

    def test_none_body(self):
        assert extract_section_items(None, {"acceptance criteria"}) == []


# ---------------------------------------------------------------------------
# infer_validation_commands
# ---------------------------------------------------------------------------


class TestInferValidationCommands:
    @pytest.mark.parametrize(
        "step_names, expected",
        [
            (["Run pytest"], ["pytest"]),
            (["Run tests"], ["pytest"]),
            (["Lint with ruff"], ["ruff check ."]),
            (["Type check with mypy"], ["mypy ."]),
            (["Run black check"], ["black --check ."]),
            (["flake8 lint"], ["flake8 ."]),
            (["Measure coverage"], ["pytest --cov"]),
            (["npm test"], ["npm test"]),
            (["go test"], ["go test ./..."]),
            (["cargo test"], ["cargo test"]),
        ],
    )
    def test_single_step(self, step_names, expected):
        assert infer_validation_commands(step_names) == expected

    def test_multiple_steps_deduplicates(self):
        names = ["Run pytest", "Run tests again", "Lint with ruff"]
        result = infer_validation_commands(names)
        assert result.count("pytest") == 1
        assert "ruff check ." in result

    def test_unrecognized_steps_ignored(self):
        names = ["Checkout", "Setup Python", "Install deps"]
        assert infer_validation_commands(names) == []

    def test_empty_list(self):
        assert infer_validation_commands([]) == []

    def test_none(self):
        assert infer_validation_commands(None) == []

    def test_preserves_order(self):
        names = ["Lint with ruff", "Run pytest"]
        result = infer_validation_commands(names)
        assert result.index("ruff check .") < result.index("pytest")


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_basic(self):
        assert slugify("My Repo Name") == "my-repo-name"

    def test_special_chars(self):
        assert slugify("owner/repo") == "owner-repo"

    def test_trailing_punctuation(self):
        assert slugify("My Repo!") == "my-repo"

    def test_max_length(self):
        result = slugify("a" * 100, max_length=20)
        assert len(result) <= 20

    def test_already_slug(self):
        assert slugify("my-repo-name") == "my-repo-name"

    def test_numbers_preserved(self):
        assert slugify("repo-v2") == "repo-v2"

    def test_empty_string(self):
        assert slugify("") == ""
