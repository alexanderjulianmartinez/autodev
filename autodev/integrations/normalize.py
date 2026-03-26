"""Provider-agnostic normalization helpers for the integration layer.

Adapter authors use these utilities to map provider-specific strings and
structures to the canonical values expected by the integration models.  Using
these helpers keeps individual adapters thin and ensures consistent output
regardless of the upstream provider.

All functions are pure (no side effects, no I/O) and accept ``str | None``
wherever a field may be absent in the provider payload.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Priority normalization
# ---------------------------------------------------------------------------

_PRIORITY_MAP: dict[str, str] = {
    # critical
    "p0": "critical",
    "priority:p0": "critical",
    "critical": "critical",
    "urgent": "critical",
    "blocker": "critical",
    "highest": "critical",  # Jira
    # high
    "p1": "high",
    "priority:p1": "high",
    "high": "high",
    "major": "high",
    # medium
    "p2": "medium",
    "priority:p2": "medium",
    "medium": "medium",
    "normal": "medium",
    "moderate": "medium",
    # low
    "p3": "low",
    "priority:p3": "low",
    "low": "low",
    "minor": "low",
    "trivial": "low",
    "lowest": "low",  # Jira
}


def normalize_priority(raw: str | None) -> str:
    """Map a provider-specific priority string to a canonical value.

    Canonical values: ``"critical"``, ``"high"``, ``"medium"``, ``"low"``.
    Unknown or absent values return ``"medium"``.

    Args:
        raw: Provider priority string (e.g. ``"p0"``, ``"CRITICAL"``,
             ``"priority:p1"``, ``"Major"``).

    Returns:
        One of ``"critical"``, ``"high"``, ``"medium"``, ``"low"``.

    Examples::

        normalize_priority("p0")         # "critical"
        normalize_priority("CRITICAL")   # "critical"
        normalize_priority("priority:p2")# "medium"
        normalize_priority(None)         # "medium"
        normalize_priority("unknown")    # "medium"
    """
    if not raw:
        return "medium"
    return _PRIORITY_MAP.get(raw.strip().lower(), "medium")


# ---------------------------------------------------------------------------
# Status normalization
# ---------------------------------------------------------------------------

_STATUS_MAP: dict[str, str] = {
    # open
    "open": "open",
    "opened": "open",
    "todo": "open",
    "to do": "open",
    "backlog": "open",
    "new": "open",
    "created": "open",
    "pending": "open",
    "queued": "open",
    # in_progress
    "in_progress": "in_progress",
    "in progress": "in_progress",
    "active": "in_progress",
    "wip": "in_progress",
    "doing": "in_progress",
    "started": "in_progress",
    "running": "in_progress",
    "in review": "in_progress",
    "in_review": "in_progress",
    # closed
    "closed": "closed",
    "done": "closed",
    "completed": "closed",
    "complete": "closed",
    "resolved": "closed",
    "merged": "closed",
    "success": "closed",
    "succeeded": "closed",
    # failed
    "failed": "failed",
    "failure": "failed",
    "error": "failed",
    "errored": "failed",
    "cancelled": "failed",
    "canceled": "failed",
    "timed_out": "failed",
    "timedout": "failed",
}


def normalize_status(raw: str | None) -> str:
    """Map a provider-specific status string to a canonical value.

    Canonical values: ``"open"``, ``"in_progress"``, ``"closed"``, ``"failed"``.
    Unknown or absent values return ``"open"``.

    Args:
        raw: Provider status string (e.g. ``"Todo"``, ``"IN PROGRESS"``,
             ``"resolved"``, ``"cancelled"``).

    Returns:
        One of ``"open"``, ``"in_progress"``, ``"closed"``, ``"failed"``.

    Examples::

        normalize_status("Todo")       # "open"
        normalize_status("IN PROGRESS")# "in_progress"
        normalize_status("resolved")   # "closed"
        normalize_status("cancelled")  # "failed"
        normalize_status(None)         # "open"
    """
    if not raw:
        return "open"
    return _STATUS_MAP.get(raw.strip().lower(), "open")


# ---------------------------------------------------------------------------
# Label normalization
# ---------------------------------------------------------------------------


def normalize_labels(labels: list[str] | None) -> list[str]:
    """Lowercase, strip whitespace, and deduplicate a list of labels.

    Order is preserved (first occurrence wins on deduplication).

    Args:
        labels: Raw labels from a provider, or ``None``.

    Returns:
        Cleaned, deduplicated label list.

    Examples::

        normalize_labels(["Bug", "BUG", " enhancement "]) # ["bug", "enhancement"]
        normalize_labels(None)                             # []
    """
    if not labels:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for label in labels:
        cleaned = label.strip().lower()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


# ---------------------------------------------------------------------------
# Markdown task-list extraction
# ---------------------------------------------------------------------------

# Matches GitHub-style task-list items:  "- [ ] text"  "- [x] text"  "* [ ] text"
_TASK_LIST_RE = re.compile(
    r"^\s*[-*]\s*\[[xX ]\]\s*(.+)",
    re.MULTILINE,
)


def extract_task_list_items(body: str | None) -> list[str]:
    """Extract text from Markdown task-list items (``- [ ]`` / ``- [x]``).

    Handles both checked and unchecked items.  Commonly used to parse
    acceptance criteria from issue bodies.

    Args:
        body: Markdown text (e.g. a GitHub issue body).

    Returns:
        List of item texts, stripped of leading/trailing whitespace.

    Examples::

        extract_task_list_items("- [ ] Write tests\\n- [x] Add docs")
        # ["Write tests", "Add docs"]
    """
    if not body:
        return []
    return [m.group(1).strip() for m in _TASK_LIST_RE.finditer(body)]


# ---------------------------------------------------------------------------
# Markdown section extraction
# ---------------------------------------------------------------------------

_SECTION_HEADING_RE = re.compile(r"^#+\s+(.+)", re.MULTILINE)
_LIST_ITEM_RE = re.compile(r"^\s*[-*]\s+(.+)", re.MULTILINE)


def extract_section_items(body: str | None, section_names: set[str]) -> list[str]:
    """Extract bullet-list items from a named Markdown section.

    Finds the first heading whose text (lowercased) is in ``section_names``
    and collects bullet items until the next heading.

    Args:
        body: Markdown text to search.
        section_names: Lowercase heading names to match (e.g.
            ``{"acceptance criteria", "acceptance criterion"}``).

    Returns:
        Bullet item texts from the matched section, or ``[]`` if not found.

    Examples::

        extract_section_items(body, {"acceptance criteria"})
        # ["All tests pass", "No regressions"]
    """
    if not body:
        return []

    headings = list(_SECTION_HEADING_RE.finditer(body))
    for i, heading in enumerate(headings):
        if heading.group(1).strip().lower() not in section_names:
            continue
        section_start = heading.end()
        section_end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        section_text = body[section_start:section_end]
        return [m.group(1).strip() for m in _LIST_ITEM_RE.finditer(section_text)]

    return []


# ---------------------------------------------------------------------------
# CI step-name → validation command inference
# ---------------------------------------------------------------------------

_CI_STEP_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # More-specific patterns first so they are not shadowed by generic keywords.
    (re.compile(r"pytest|run tests?", re.IGNORECASE), "pytest"),
    (re.compile(r"\bcoverage\b", re.IGNORECASE), "pytest --cov"),
    (re.compile(r"mypy|type.?check", re.IGNORECASE), "mypy ."),
    (re.compile(r"\bflake8\b", re.IGNORECASE), "flake8 ."),
    (re.compile(r"\bblack\b", re.IGNORECASE), "black --check ."),
    (re.compile(r"\bruff\b|lint|format", re.IGNORECASE), "ruff check ."),
    (re.compile(r"\bnpm\s+test\b", re.IGNORECASE), "npm test"),
    (re.compile(r"\bgo\s+test\b", re.IGNORECASE), "go test ./..."),
    (re.compile(r"\bcargo\s+test\b", re.IGNORECASE), "cargo test"),
]


def infer_validation_commands(step_names: list[str] | None) -> list[str]:
    """Infer CLI validation commands from CI step names.

    Maps common step-name patterns to their canonical CLI equivalents,
    deduplicating the result.  Unrecognized step names are ignored.

    Args:
        step_names: List of CI job step names from any provider.

    Returns:
        Deduplicated list of inferred commands, in match order.

    Examples::

        infer_validation_commands(["Run pytest", "Lint with ruff", "Build"])
        # ["pytest", "ruff check ."]
    """
    if not step_names:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for name in step_names:
        for pattern, cmd in _CI_STEP_PATTERNS:
            if pattern.search(name) and cmd not in seen:
                seen.add(cmd)
                result.append(cmd)
                break
    return result


# ---------------------------------------------------------------------------
# Slug / ID helpers
# ---------------------------------------------------------------------------

_UNSAFE_ID_CHARS = re.compile(r"[^a-z0-9._-]+")


def slugify(text: str, max_length: int = 60) -> str:
    """Convert *text* to a safe, lowercase, hyphenated slug.

    Suitable for constructing entity IDs from arbitrary strings (repo names,
    project keys, user-supplied titles).

    Args:
        text: Input string.
        max_length: Maximum character length of the resulting slug.

    Returns:
        Lowercase slug with non-alphanumeric characters replaced by hyphens,
        truncated to ``max_length`` and stripped of leading/trailing hyphens.

    Examples::

        slugify("My Repo Name!")   # "my-repo-name"
        slugify("owner/repo")      # "owner-repo"
    """
    slug = _UNSAFE_ID_CHARS.sub("-", text.lower())
    slug = slug.strip("-._")[:max_length].rstrip("-._")
    return slug
