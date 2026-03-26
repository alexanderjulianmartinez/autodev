"""PlannerAgent: generates a structured implementation plan."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from autodev.agents.base import Agent, AgentContext

logger = logging.getLogger(__name__)
ISSUE_TOKEN_PATTERN = re.compile(r"[a-z0-9_]{3,}")
MARKDOWN_HEADING_PATTERN = re.compile(r"^#+\s*")
PLANNER_STOP_WORDS = {
    "about",
    "acceptance",
    "add",
    "after",
    "against",
    "and",
    "criteria",
    "feature",
    "files",
    "flow",
    "for",
    "from",
    "implement",
    "into",
    "issue",
    "mode",
    "plan",
    "planner",
    "repository",
    "request",
    "should",
    "tests",
    "that",
    "the",
    "this",
    "validation",
    "with",
}
TEXT_FILE_SUFFIXES = {".py", ".md", ".rst", ".toml", ".yaml", ".yml", ".json", ".txt"}
TEXT_UPDATE_SUFFIXES = {".md", ".rst", ".txt"}
CODE_UPDATE_SUFFIXES = {".py"}
IGNORED_PATH_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
MAX_SCORING_FILE_BYTES = 64 * 1024
MAX_SCORING_SAMPLE_CHARS = 4000
KNOWN_SECTION_HEADINGS = {
    "acceptance criteria",
    "acceptance criterion",
    "target files",
    "target file",
    "file paths",
    "files",
    "requested changes",
    "changes",
    "instructions",
    "implementation notes",
    "validation commands",
    "validation command",
}


class PlannerAgent(Agent):
    """Produces a structured, step-by-step implementation plan."""

    def run(self, task: str, context: AgentContext) -> AgentContext:
        logger.info("PlannerAgent running task: %s", task)
        planning_context = self._build_planning_context(context)
        fallback_plan = self._default_plan(context, planning_context)

        if self.model_router:
            prompt = self._build_prompt(context, planning_context)
            try:
                response = self.model_router.generate(prompt, model_key="planner")
                plan = self._parse_plan(response, fallback_plan)
            except Exception as exc:
                logger.warning("Model call failed (%s); using default plan.", exc)
                plan = fallback_plan
        else:
            plan = fallback_plan

        logger.info("Plan generated with %d step(s)", len(plan))
        metadata = dict(context.metadata)
        metadata.update(planning_context)
        return context.model_copy(update={"plan": plan, "metadata": metadata})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, context: AgentContext, planning_context: dict[str, object]) -> str:
        issue_title = context.metadata.get("issue_title", "the issue")
        issue_body = context.metadata.get("issue_body", "")
        likely_target_files = planning_context.get("likely_target_files", [])
        acceptance_criteria = planning_context.get("acceptance_criteria", [])
        requested_changes = planning_context.get("requested_changes", [])
        validation_hints = planning_context.get("validation_hints", [])
        return (
            f"You are an expert software engineer. Generate a concise, numbered "
            f"implementation plan for the following GitHub issue.\n\n"
            f"Title: {issue_title}\n\nDescription:\n{issue_body}\n\n"
            f"Likely target files: {', '.join(likely_target_files) or 'unknown'}\n"
            f"Requested changes: {', '.join(requested_changes) or 'none supplied'}\n"
            f"Acceptance criteria: {', '.join(acceptance_criteria) or 'none supplied'}\n"
            f"Validation hints: {', '.join(validation_hints) or 'run the relevant tests'}\n\n"
            f"Return ONLY a numbered list of steps, one per line."
        )

    def _parse_plan(self, response: str, fallback_plan: list[str]) -> list[str]:
        if self._looks_like_placeholder_response(response):
            return fallback_plan
        lines = [line.strip() for line in response.splitlines() if line.strip()]
        return lines if lines else fallback_plan

    def _looks_like_placeholder_response(self, response: str) -> bool:
        normalized = response.strip()
        return normalized.startswith("[local:")

    def _default_plan(
        self, context: AgentContext, planning_context: dict[str, object]
    ) -> list[str]:
        issue_title = context.metadata.get("issue_title", "the feature")
        target_files = list(planning_context.get("likely_target_files", []))
        acceptance_criteria = list(planning_context.get("acceptance_criteria", []))
        requested_changes = list(planning_context.get("requested_changes", []))
        validation_commands = list(planning_context.get("validation_commands", []))
        validation_hints = list(planning_context.get("validation_hints", []))
        execution_strategy = str(planning_context.get("execution_strategy", "generic"))

        file_summary = ", ".join(target_files[:3])
        if not file_summary:
            file_summary = "the most relevant repository areas"
        validation_summary = (
            "; ".join(validation_hints[:2])
            if validation_hints
            else "run the relevant test coverage"
        )
        acceptance_summary = (
            "; ".join(acceptance_criteria[:2])
            if acceptance_criteria
            else f"the requested behavior for {issue_title}"
        )

        if execution_strategy == "text_update" and requested_changes:
            requested_summary = "; ".join(requested_changes[:2])
            return [
                f"1. Confirm the issue scope and acceptance criteria for: {issue_title}",
                f"2. Update the requested text files: {file_summary}",
                f"3. Apply the requested documentation or text changes: {requested_summary}",
                f"4. Verify the updated text satisfies: {acceptance_summary}",
                f"5. Validate the change set using: {validation_summary}",
            ]

        if execution_strategy == "code_scaffold" and requested_changes:
            requested_summary = "; ".join(requested_changes[:2])
            validation_summary = (
                "; ".join(validation_commands[:2]) if validation_commands else validation_summary
            )
            return [
                f"1. Confirm the issue scope and acceptance criteria for: {issue_title}",
                f"2. Update the declared code targets: {file_summary}",
                f"3. Scaffold the requested code constructs: {requested_summary}",
                "4. Verify the generated symbols and imports are syntactically valid",
                f"5. Validate the change set using: {validation_summary}",
            ]

        return [
            f"1. Confirm the issue scope and acceptance criteria for: {issue_title}",
            f"2. Inspect likely target files: {file_summary}",
            f"3. Implement the required changes while satisfying: {acceptance_summary}",
            "4. Add or update tests to cover the affected behavior",
            f"5. Validate the change set using: {validation_summary}",
        ]

    def _build_planning_context(self, context: AgentContext) -> dict[str, object]:
        issue_title = str(context.metadata.get("issue_title", "")).strip()
        issue_body = str(context.metadata.get("issue_body", "")).strip()
        acceptance_criteria = self._extract_acceptance_criteria(issue_body)
        explicit_target_files = self._extract_explicit_target_files(issue_body)
        requested_changes = self._extract_requested_changes(issue_body)
        validation_commands = self._extract_validation_commands(issue_body)
        likely_target_files = self._identify_likely_target_files(
            context,
            issue_title,
            issue_body,
            explicit_target_files=explicit_target_files,
        )
        validation_hints = self._build_validation_hints(
            context,
            likely_target_files,
            acceptance_criteria,
            validation_commands=validation_commands,
        )
        execution_strategy = self._execution_strategy(likely_target_files, requested_changes)
        planning_mode = "repository-aware" if likely_target_files else "fallback"
        return {
            "planning_mode": planning_mode,
            "execution_strategy": execution_strategy,
            "explicit_target_files": explicit_target_files,
            "likely_target_files": likely_target_files,
            "requested_changes": requested_changes,
            "validation_commands": validation_commands,
            "acceptance_criteria": acceptance_criteria,
            "validation_hints": validation_hints,
        }

    def _extract_acceptance_criteria(self, issue_body: str) -> list[str]:
        return self._extract_section_list(
            issue_body, {"acceptance criteria", "acceptance criterion"}
        )

    def _extract_explicit_target_files(self, issue_body: str) -> list[str]:
        candidates = self._extract_section_list(
            issue_body,
            {"target files", "target file", "file paths", "files"},
        )
        explicit: list[str] = []
        for candidate in candidates:
            normalized = self._normalize_explicit_path(candidate)
            if normalized and normalized not in explicit:
                explicit.append(normalized)
        return explicit

    def _extract_requested_changes(self, issue_body: str) -> list[str]:
        return self._extract_section_list(
            issue_body,
            {"requested changes", "changes", "instructions", "implementation notes"},
        )

    def _extract_validation_commands(self, issue_body: str) -> list[str]:
        return self._extract_section_list(
            issue_body,
            {"validation commands", "validation command"},
        )

    def _extract_section_list(self, issue_body: str, headings: set[str]) -> list[str]:
        if not issue_body:
            return []

        items: list[str] = []
        capture = False
        for raw_line in issue_body.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            normalized_heading = self._normalize_section_heading(line)
            if normalized_heading in headings:
                capture = True
                continue
            if capture and self._looks_like_section_heading(line):
                break
            if not capture:
                continue

            bullet_match = re.match(r"(?:[-*]|\d+[.)])\s+(.*)", line)
            if bullet_match:
                items.append(bullet_match.group(1).strip())
                continue

            if items:
                items[-1] = f"{items[-1]} {line}".strip()
            else:
                items.append(line)

        return items

    def _normalize_section_heading(self, line: str) -> str:
        stripped = MARKDOWN_HEADING_PATTERN.sub("", line.strip())
        return stripped.rstrip(":").strip().lower()

    def _looks_like_section_heading(self, line: str) -> bool:
        normalized = self._normalize_section_heading(line)
        return line.lstrip().startswith("#") or normalized in KNOWN_SECTION_HEADINGS

    def _normalize_explicit_path(self, value: str) -> str:
        candidate = value.strip().strip("`'\".,;:()[]{}")
        if not candidate:
            return ""
        path = Path(candidate)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            return ""
        if path.suffix.lower() not in TEXT_FILE_SUFFIXES:
            return ""
        return path.as_posix()

    def _execution_strategy(
        self,
        likely_target_files: list[str],
        requested_changes: list[str],
    ) -> str:
        if requested_changes and likely_target_files:
            if all(
                Path(path).suffix.lower() in TEXT_UPDATE_SUFFIXES for path in likely_target_files
            ):
                return "text_update"
            if all(
                Path(path).suffix.lower() in CODE_UPDATE_SUFFIXES for path in likely_target_files
            ):
                if self._supports_code_scaffold(requested_changes):
                    return "code_scaffold"
        return "generic"

    def _supports_code_scaffold(self, requested_changes: list[str]) -> bool:
        return any(self._extract_symbol_specs(change) for change in requested_changes)

    def _extract_symbol_specs(self, change: str) -> list[tuple[str, str]]:
        patterns = [
            (
                "protocol",
                r"\b(?:add|create|define|introduce)\b.*\b(?:protocol|interface)\s+([A-Z][A-Za-z0-9_]*)",
            ),
            (
                "dataclass",
                r"\b(?:add|create|define|introduce)\b.*\bdataclass\s+([A-Z][A-Za-z0-9_]*)",
            ),
            ("class", r"\b(?:add|create|define|introduce)\b.*\bclass\s+([A-Z][A-Za-z0-9_]*)"),
            (
                "function",
                r"\b(?:add|create|define|introduce)\b.*\bfunction\s+([a-z_][A-Za-z0-9_]*)",
            ),
        ]
        matches: list[tuple[str, str]] = []
        for kind, pattern in patterns:
            for match in re.finditer(pattern, change, flags=re.IGNORECASE):
                symbol = match.group(1)
                entry = (kind, symbol)
                if entry not in matches:
                    matches.append(entry)
        return matches

    def _identify_likely_target_files(
        self,
        context: AgentContext,
        issue_title: str,
        issue_body: str,
        *,
        explicit_target_files: list[str] | None = None,
    ) -> list[str]:
        repo_path = str(context.repo_path or "").strip()
        if not repo_path:
            return list(explicit_target_files or [])

        repo_root = Path(repo_path).expanduser()
        if not repo_root.exists() or not repo_root.is_dir():
            return list(explicit_target_files or [])

        explicit_matches: list[str] = []
        for candidate in explicit_target_files or []:
            normalized = self._normalize_explicit_path(candidate)
            if not normalized:
                continue
            target = repo_root / normalized
            if target.exists() or target.parent.exists():
                explicit_matches.append(normalized)
        if explicit_matches:
            return explicit_matches

        tokens = self._issue_tokens(issue_title, issue_body)
        if not tokens:
            return []

        candidates: list[tuple[int, str]] = []
        for candidate in repo_root.rglob("*"):
            if not candidate.is_file():
                continue
            if any(part in IGNORED_PATH_PARTS for part in candidate.parts):
                continue
            if candidate.suffix.lower() not in TEXT_FILE_SUFFIXES:
                continue

            relative_path = candidate.relative_to(repo_root).as_posix()
            score = self._score_candidate_file(candidate, relative_path, tokens)
            if score > 0:
                candidates.append((score, relative_path))

        candidates.sort(key=lambda item: (-item[0], item[1]))
        return [path for _score, path in candidates[:5]]

    def _score_candidate_file(self, candidate: Path, relative_path: str, tokens: list[str]) -> int:
        path_text = relative_path.lower()
        score = 0

        for token in tokens:
            if token in path_text:
                score += 4
            if candidate.stem.lower() == token:
                score += 3

        sample = self._read_candidate_sample(candidate)

        for token in tokens[:8]:
            if token in sample:
                score += 1

        return score

    def _read_candidate_sample(self, candidate: Path) -> str:
        try:
            if candidate.stat().st_size > MAX_SCORING_FILE_BYTES:
                return ""
        except OSError:
            return ""

        try:
            with candidate.open("r", encoding="utf-8") as handle:
                return handle.read(MAX_SCORING_SAMPLE_CHARS).lower()
        except (OSError, UnicodeDecodeError):
            return ""

    def _build_validation_hints(
        self,
        context: AgentContext,
        likely_target_files: list[str],
        acceptance_criteria: list[str],
        *,
        validation_commands: list[str] | None = None,
    ) -> list[str]:
        hints: list[str] = []
        explicit_commands = [
            str(command).strip() for command in (validation_commands or []) if str(command).strip()
        ]
        if explicit_commands:
            hints.append(f"Run explicit validation commands: {'; '.join(explicit_commands[:2])}")
        repo_path = Path(context.repo_path).expanduser() if context.repo_path else None
        targeted_tests: list[str] = []

        if repo_path and repo_path.exists():
            for relative_path in likely_target_files:
                relative = Path(relative_path)
                if relative.parts and relative.parts[0] == "tests":
                    targeted_tests.append(relative.as_posix())
                    continue
                if relative.suffix != ".py":
                    continue

                direct_test = repo_path / "tests" / f"test_{relative.stem}.py"
                alt_test = repo_path / "tests" / f"{relative.stem}_test.py"
                for candidate in (direct_test, alt_test):
                    if candidate.exists():
                        targeted_tests.append(candidate.relative_to(repo_path).as_posix())

        if targeted_tests:
            unique_tests = sorted(dict.fromkeys(targeted_tests))
            hints.append(f"Run targeted pytest coverage for: {', '.join(unique_tests[:3])}")
        elif likely_target_files and not explicit_commands:
            hints.append("Run the most relevant pytest coverage for the affected files")
        elif not explicit_commands:
            hints.append("Run the relevant test coverage for the requested behavior")

        if acceptance_criteria:
            hints.append(f"Verify acceptance criteria: {'; '.join(acceptance_criteria[:2])}")

        return hints

    def _issue_tokens(self, issue_title: str, issue_body: str) -> list[str]:
        raw_tokens = ISSUE_TOKEN_PATTERN.findall(f"{issue_title} {issue_body}".lower())
        ordered_tokens: list[str] = []
        for token in raw_tokens:
            if token in PLANNER_STOP_WORDS or token.isdigit() or token in ordered_tokens:
                continue
            ordered_tokens.append(token)
        return ordered_tokens
