"""TestRunner: runs a test suite in a subprocess and returns results."""

from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from autodev.core.schemas import (
    ValidationCommandResult,
    ValidationResult,
    ValidationStatus,
    utc_now,
)
from autodev.core.supervisor import Supervisor
from autodev.tools.base import Tool

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    passed: bool
    output: str
    error: str
    return_code: int


class TestRunner(Tool):
    """Executes a test suite and returns structured results."""

    __test__ = False

    DEFAULT_TIMEOUT = 120
    DEFAULT_PYTEST_COMMAND = "pytest -q"
    DEFAULT_VALIDATION_BREADTH = "targeted"
    BROADER_FALLBACK_BREADTH = "broader-fallback"

    def __init__(self, supervisor: Supervisor | None = None) -> None:
        self.supervisor = supervisor or Supervisor()

    def execute(self, input: dict[str, Any]) -> dict[str, Any]:
        result = self.run_validation(
            repo_path=input.get("repo_path", "."),
            task_id=input.get("task_id", "adhoc-validate"),
            changed_files=input.get("changed_files") or [],
            explicit_commands=input.get("validation_commands") or input.get("test_command"),
            validation_breadth=input.get("validation_breadth", self.DEFAULT_VALIDATION_BREADTH),
            stop_on_first_failure=not bool(input.get("continue_on_error", False)),
        )
        return {
            "passed": result.status == ValidationStatus.PASSED,
            "summary": result.summary,
            "commands": [command.model_dump(mode="json") for command in result.commands],
            "profiles": list(result.profiles),
        }

    def run(self, repo_path: str = ".", test_command: str = "pytest") -> TestResult:
        """Run *test_command* in *repo_path* and return a TestResult."""
        validation_result = self.run_validation(
            repo_path=repo_path,
            task_id="adhoc-validate",
            explicit_commands=[test_command],
        )
        if validation_result.commands:
            command_result = validation_result.commands[0]
            return TestResult(
                passed=validation_result.status == ValidationStatus.PASSED,
                output=command_result.stdout,
                error=command_result.stderr,
                return_code=command_result.exit_code,
            )
        return TestResult(
            passed=validation_result.status == ValidationStatus.PASSED,
            output=validation_result.summary,
            error="",
            return_code=0 if validation_result.status == ValidationStatus.PASSED else 1,
        )

    def run_validation(
        self,
        repo_path: str = ".",
        *,
        task_id: str,
        changed_files: list[str] | None = None,
        explicit_commands: list[str] | str | None = None,
        validation_breadth: str = DEFAULT_VALIDATION_BREADTH,
        stop_on_first_failure: bool = True,
    ) -> ValidationResult:
        changed = [str(path) for path in (changed_files or []) if str(path).strip()]
        commands, profiles, selection_reason = self.plan_validation(
            repo_path=repo_path,
            changed_files=changed,
            explicit_commands=explicit_commands,
            validation_breadth=validation_breadth,
        )
        normalized_breadth = self._normalize_validation_breadth(validation_breadth)
        started_at = utc_now()
        command_results: list[ValidationCommandResult] = []

        for command in commands:
            result = self._run_validation_command(repo_path=repo_path, command=command)
            command_results.append(result)
            if stop_on_first_failure and result.status == ValidationStatus.FAILED:
                break

        if not command_results:
            status = ValidationStatus.SKIPPED
            summary = "Validation skipped: no commands resolved."
        elif all(result.status == ValidationStatus.PASSED for result in command_results):
            status = ValidationStatus.PASSED
            summary = f"Validation passed for {len(command_results)} command(s)."
        else:
            status = ValidationStatus.FAILED
            if stop_on_first_failure:
                summary = f"Validation failed after {len(command_results)} command(s)."
            else:
                summary = f"Validation failed after executing {len(command_results)} command(s)."

        return ValidationResult(
            task_id=task_id,
            status=status,
            summary=summary,
            commands=command_results,
            changed_files=changed,
            profiles=profiles,
            metadata={
                "validation_breadth": normalized_breadth,
                "stop_on_first_failure": stop_on_first_failure,
                "selection_reason": selection_reason,
            },
            started_at=started_at,
            completed_at=utc_now(),
        )

    def plan_validation(
        self,
        *,
        repo_path: str,
        changed_files: list[str] | None = None,
        explicit_commands: list[str] | str | None = None,
        validation_breadth: str = DEFAULT_VALIDATION_BREADTH,
    ) -> tuple[list[str], list[str], str]:
        normalized_breadth = self._normalize_validation_breadth(validation_breadth)
        explicit = self._normalize_commands(explicit_commands)
        if explicit:
            return explicit, ["explicit"], "Explicit validation commands were provided."

        changed = [str(path) for path in (changed_files or []) if str(path).strip()]
        repo_root = Path(repo_path)
        targeted_tests = self._targeted_pytest_files(repo_root, changed)
        if targeted_tests:
            quoted = " ".join(shlex.quote(path) for path in targeted_tests)
            targeted_command = f"pytest {quoted} -v"
            if normalized_breadth == self.BROADER_FALLBACK_BREADTH:
                commands = [targeted_command]
                for fallback_command in self._default_validation_commands(repo_root, changed):
                    if fallback_command not in commands:
                        commands.append(fallback_command)
                return (
                    commands,
                    ["changed-file-targeted", self.BROADER_FALLBACK_BREADTH],
                    (
                        "Targeted tests were inferred from changed files and broader "
                        "fallback validation was added."
                    ),
                )
            return (
                [targeted_command],
                ["changed-file-targeted", normalized_breadth],
                "Strict targeted validation was inferred from changed files.",
            )

        commands, profile, reason = self._default_validation_plan(repo_root, changed)
        return commands, [profile, normalized_breadth], reason

    def _normalize_commands(self, commands: list[str] | str | None) -> list[str]:
        if commands is None:
            return []
        if isinstance(commands, str):
            command = commands.strip()
            return [command] if command else []
        normalized: list[str] = []
        for command in commands:
            candidate = str(command).strip()
            if candidate:
                normalized.append(candidate)
        return normalized

    def _normalize_validation_breadth(self, value: str | None) -> str:
        candidate = str(value or self.DEFAULT_VALIDATION_BREADTH).strip().lower()
        if candidate == self.BROADER_FALLBACK_BREADTH:
            return self.BROADER_FALLBACK_BREADTH
        return self.DEFAULT_VALIDATION_BREADTH

    def _default_validation_plan(
        self,
        repo_root: Path,
        changed_files: list[str],
    ) -> tuple[list[str], str, str]:
        if any(Path(path).suffix == ".py" for path in changed_files):
            return (
                [self.DEFAULT_PYTEST_COMMAND],
                "python-default",
                "No targeted test match was found, so Python default validation was selected.",
            )

        if (repo_root / "pyproject.toml").exists() or (repo_root / "tests").exists():
            return (
                [self.DEFAULT_PYTEST_COMMAND],
                "project-default",
                "No targeted test match was found, so project default validation was selected.",
            )

        return (
            [self.DEFAULT_PYTEST_COMMAND],
            "fallback-default",
            "No targeted validation hints were found, so fallback default validation was selected.",
        )

    def _default_validation_commands(self, repo_root: Path, changed_files: list[str]) -> list[str]:
        commands, _profile, _reason = self._default_validation_plan(repo_root, changed_files)
        return commands

    def _targeted_pytest_files(self, repo_root: Path, changed_files: list[str]) -> list[str]:
        targeted: list[str] = []
        for changed in changed_files:
            relative = Path(changed)
            relative_path = relative.as_posix()
            if relative.parts and relative.parts[0] == "tests" and relative.suffix == ".py":
                if relative_path not in targeted:
                    targeted.append(relative_path)
                continue
            if relative.suffix != ".py":
                continue

            candidate_paths = [
                repo_root / "tests" / f"test_{relative.stem}.py",
                repo_root / "tests" / f"{relative.stem}_test.py",
            ]
            for candidate in candidate_paths:
                if candidate.exists():
                    relative_candidate = candidate.relative_to(repo_root).as_posix()
                    if relative_candidate not in targeted:
                        targeted.append(relative_candidate)
        return targeted

    def _run_validation_command(self, *, repo_path: str, command: str) -> ValidationCommandResult:
        logger.info("Running tests in %r with command %r", repo_path, command)
        is_safe, reason = self.supervisor.validate_command(command)
        self.supervisor.record_decision(
            operation="test_command",
            target=command,
            allowed=is_safe,
            reason=reason,
            metadata={"repo_path": repo_path},
        )
        if not is_safe:
            return ValidationCommandResult(
                command=command,
                exit_code=1,
                status=ValidationStatus.FAILED,
                stdout="",
                stderr=f"Blocked: {reason}",
                duration_seconds=0.0,
            )
        started = perf_counter()
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=self.DEFAULT_TIMEOUT,
            )
            return ValidationCommandResult(
                command=command,
                exit_code=proc.returncode,
                status=(
                    ValidationStatus.PASSED if proc.returncode == 0 else ValidationStatus.FAILED
                ),
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration_seconds=perf_counter() - started,
            )
        except subprocess.TimeoutExpired:
            return ValidationCommandResult(
                command=command,
                exit_code=1,
                status=ValidationStatus.FAILED,
                stdout="",
                stderr="Test run timed out",
                duration_seconds=perf_counter() - started,
            )
        except Exception as exc:
            return ValidationCommandResult(
                command=command,
                exit_code=1,
                status=ValidationStatus.FAILED,
                stdout="",
                stderr=str(exc),
                duration_seconds=perf_counter() - started,
            )
