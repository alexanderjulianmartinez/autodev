#!/usr/bin/env python3
"""Generate and optionally publish GitHub issues from backlog_v2.md."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib import error, request

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKLOG_PATH = REPO_ROOT / "backlog_v2.md"
DEFAULT_DRAFT_DIR = REPO_ROOT / "docs" / "github_issue_drafts" / "backlog_v2"
DEFAULT_JSON_PATH = DEFAULT_DRAFT_DIR / "issues.json"

ISSUE_HEADER_RE = re.compile(r"^###\s+(AD-\d+)\s+(.+)$")
METADATA_RE = re.compile(r"^- \*\*(?P<name>[^*]+):\*\*\s*(?P<value>.+)$")
MILESTONE_RE = re.compile(r"^##\s+Milestone\s+\d+:\s+(.+)$")
REMOTE_RE = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?$")


@dataclass
class IssueDraft:
    identifier: str
    title: str
    milestone: str
    priority: str
    issue_type: str
    problem: str
    scope: str
    acceptance_criteria: list[str]

    @property
    def github_title(self) -> str:
        return f"{self.identifier} {self.title}"

    @property
    def suggested_labels(self) -> list[str]:
        return [self.priority, self.issue_type]

    def to_body(self) -> str:
        acceptance = "\n".join(f"- {item}" for item in self.acceptance_criteria)
        labels = ", ".join(self.suggested_labels)
        return (
            f"## Backlog Metadata\n\n"
            f"- Source: `backlog_v2.md`\n"
            f"- Backlog item: `{self.identifier}`\n"
            f"- Milestone: {self.milestone}\n"
            f"- Suggested labels: {labels}\n\n"
            f"## Problem\n\n{self.problem}\n\n"
            f"## Scope\n\n{self.scope}\n\n"
            f"## Acceptance Criteria\n\n{acceptance}\n"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backlog", type=Path, default=DEFAULT_BACKLOG_PATH, help="Path to backlog markdown file"
    )
    parser.add_argument(
        "--write-drafts",
        type=Path,
        default=DEFAULT_DRAFT_DIR,
        help="Directory for generated draft markdown files",
    )
    parser.add_argument(
        "--write-json",
        type=Path,
        default=DEFAULT_JSON_PATH,
        help="Path for generated JSON payloads",
    )
    parser.add_argument("--publish", action="store_true", help="Create issues via GitHub REST API")
    parser.add_argument("--owner", help="GitHub repository owner; defaults to origin remote")
    parser.add_argument("--repo", help="GitHub repository name; defaults to origin remote")
    parser.add_argument("--token", help="GitHub token; defaults to GITHUB_TOKEN env var")
    parser.add_argument(
        "--apply-labels", action="store_true", help="Send suggested labels in the API request"
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip publishing issues whose title already exists",
    )
    return parser.parse_args()


def parse_backlog(path: Path) -> list[IssueDraft]:
    lines = path.read_text(encoding="utf-8").splitlines()
    drafts: list[IssueDraft] = []
    current_milestone: Optional[str] = None
    index = 0

    while index < len(lines):
        line = lines[index]
        milestone_match = MILESTONE_RE.match(line)
        if milestone_match:
            current_milestone = milestone_match.group(1).strip()
            index += 1
            continue

        issue_match = ISSUE_HEADER_RE.match(line)
        if not issue_match:
            index += 1
            continue

        if not current_milestone:
            raise ValueError(f"Issue {issue_match.group(1)} found before any milestone heading")

        identifier = issue_match.group(1).strip()
        title = issue_match.group(2).strip()
        metadata: dict[str, str] = {}
        acceptance_criteria: list[str] = []
        index += 1

        while index < len(lines):
            current_line = lines[index]
            if current_line.startswith("### ") or current_line.startswith("## "):
                break

            metadata_match = METADATA_RE.match(current_line)
            if metadata_match:
                value = metadata_match.group("value").strip()
                if len(value) >= 2 and value[0] == "`" and value[-1] == "`":
                    value = value[1:-1]
                metadata[metadata_match.group("name").strip().lower()] = value
                index += 1
                continue

            if current_line.strip() == "- **Acceptance criteria:**":
                index += 1
                while index < len(lines) and lines[index].startswith("  - "):
                    acceptance_criteria.append(lines[index][4:].strip())
                    index += 1
                continue

            index += 1

        drafts.append(
            IssueDraft(
                identifier=identifier,
                title=title,
                milestone=current_milestone,
                priority=required_metadata(metadata, "priority", identifier),
                issue_type=required_metadata(metadata, "type", identifier),
                problem=required_metadata(metadata, "problem", identifier),
                scope=required_metadata(metadata, "scope", identifier),
                acceptance_criteria=acceptance_criteria,
            )
        )

    return drafts


def required_metadata(metadata: dict[str, str], key: str, identifier: str) -> str:
    value = metadata.get(key)
    if not value:
        raise ValueError(f"Missing '{key}' metadata for {identifier}")
    return value


def write_drafts(drafts: Iterable[IssueDraft], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for draft in drafts:
        safe_title = slugify(draft.title)
        draft_path = directory / f"{draft.identifier.lower()}-{safe_title}.md"
        draft_path.write_text(f"# {draft.github_title}\n\n{draft.to_body()}", encoding="utf-8")


def write_json(drafts: Iterable[IssueDraft], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            **asdict(draft),
            "github_title": draft.github_title,
            "suggested_labels": draft.suggested_labels,
            "body": draft.to_body(),
        }
        for draft in drafts
    ]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "issue"


def infer_repo_from_git() -> tuple[str, str]:
    completed = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    remote = completed.stdout.strip()
    match = REMOTE_RE.search(remote)
    if not match:
        raise ValueError(f"Could not infer GitHub owner/repo from origin remote: {remote}")
    return match.group("owner"), match.group("repo")


def fetch_existing_titles(owner: str, repo: str, token: str) -> set[str]:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues?state=all&per_page=100"
    payload = github_request(url, token=token, method="GET")
    data = json.loads(payload)
    return {item["title"] for item in data if "pull_request" not in item}


def publish_issues(
    drafts: Iterable[IssueDraft],
    owner: str,
    repo: str,
    token: str,
    apply_labels: bool,
    skip_existing: bool,
) -> list[dict[str, object]]:
    existing_titles = fetch_existing_titles(owner, repo, token) if skip_existing else set()
    published: list[dict[str, object]] = []

    for draft in drafts:
        if draft.github_title in existing_titles:
            published.append({"title": draft.github_title, "status": "skipped-existing"})
            continue

        request_payload: dict[str, object] = {
            "title": draft.github_title,
            "body": draft.to_body(),
        }
        if apply_labels:
            request_payload["labels"] = draft.suggested_labels

        response = github_request(
            f"https://api.github.com/repos/{owner}/{repo}/issues",
            token=token,
            method="POST",
            json_payload=request_payload,
        )
        data = json.loads(response)
        published.append(
            {"title": draft.github_title, "status": "created", "url": data.get("html_url")}
        )

    return published


def github_request(
    url: str,
    *,
    token: str,
    method: str,
    json_payload: Optional[dict[str, object]] = None,
) -> str:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "autodev-backlog-publisher",
    }
    if json_payload is not None:
        data = json.dumps(json_payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req) as response:
            return response.read().decode("utf-8")
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API request failed ({exc.code} {exc.reason}): {details}"
        ) from exc


def main() -> int:
    args = parse_args()
    drafts = parse_backlog(args.backlog)
    write_drafts(drafts, args.write_drafts)
    write_json(drafts, args.write_json)

    print(f"Generated {len(drafts)} draft issues in {args.write_drafts}")
    print(f"Wrote JSON payloads to {args.write_json}")

    if not args.publish:
        return 0

    token = args.token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("Publishing requires --token or GITHUB_TOKEN")

    owner = args.owner
    repo = args.repo
    if not owner or not repo:
        inferred_owner, inferred_repo = infer_repo_from_git()
        owner = owner or inferred_owner
        repo = repo or inferred_repo

    results = publish_issues(
        drafts,
        owner=owner,
        repo=repo,
        token=token,
        apply_labels=args.apply_labels,
        skip_existing=args.skip_existing,
    )
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - script entrypoint
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
