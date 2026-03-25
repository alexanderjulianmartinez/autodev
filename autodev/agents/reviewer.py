"""ReviewerAgent: reviews code changes and produces an assessment."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from autodev.agents.base import Agent, AgentContext
from autodev.core.schemas import ReviewDecision

logger = logging.getLogger(__name__)

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    ),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{12,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{12,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"""(?ix)
    \b(
        api(?:_|-)?key
        |access(?:_|-)?token
        |auth(?:_|-)?token
        |client(?:_|-)?secret
        |password
        |passwd
        |secret
        |token
    )\b
    \s*[:=]\s*
    ([\"'])
    ([^\"'\n]{8,})
    \2
    """
)
PLACEHOLDER_SECRET_FRAGMENTS = (
    "changeme",
    "dummy",
    "example",
    "fake",
    "fixture",
    "placeholder",
    "redacted",
    "replace-me",
    "replace_me",
    "sample",
    "test",
    "your-",
    "your_",
)


class ReviewerAgent(Agent):
    """Assesses the quality of changes made during the pipeline."""

    def run(self, task: str, context: AgentContext) -> AgentContext:
        logger.info("ReviewerAgent running task: %s", task)

        meta = dict(context.metadata)

        checks = self._review_checks(context)
        decision = self._decide_review(checks)
        policy_gate_failures = self._policy_gate_failures(context)
        secret_exposure_findings = self._secret_exposure_findings(context)
        blocking_reasons = self._blocking_reasons(
            checks,
            decision,
            policy_gate_failures,
            secret_exposure_findings,
        )
        assessment = self._build_review_summary(context, checks, decision, blocking_reasons)

        meta["review"] = assessment
        meta["review_summary"] = assessment
        meta["review_decision"] = decision.value
        meta["review_checks"] = checks
        meta["review_blocking_reasons"] = blocking_reasons
        meta["policy_gate_failures"] = policy_gate_failures
        meta["secret_exposure_findings"] = secret_exposure_findings
        meta["review_passed"] = decision == ReviewDecision.APPROVED
        logger.info("ReviewerAgent decision: %s", decision.value)
        return context.model_copy(update={"metadata": meta})

    def _review_checks(self, context: AgentContext) -> dict[str, bool]:
        metadata = context.metadata
        requires_human_approval = self._metadata_flag(metadata, "requires_human_approval")
        human_approval_recorded = self._metadata_flag(metadata, "human_approval_recorded")
        policy_gate_failures = self._policy_gate_failures(context)
        secret_exposure_findings = self._secret_exposure_findings(context)
        return {
            "diff_present": self._diff_present(context),
            "validation_passed": self._validation_passed(context),
            "acceptance_criteria_present": bool(metadata.get("acceptance_criteria", [])),
            "policy_checks_passed": not policy_gate_failures,
            "secret_exposure_clear": not secret_exposure_findings,
            "human_approval_required": requires_human_approval,
            "human_approval_recorded": human_approval_recorded,
        }

    def _decide_review(self, checks: dict[str, bool]) -> ReviewDecision:
        if checks["human_approval_required"] and not checks["human_approval_recorded"]:
            return ReviewDecision.AWAITING_HUMAN_APPROVAL
        if not checks["diff_present"] or not checks["acceptance_criteria_present"]:
            return ReviewDecision.BLOCKED
        if not checks["policy_checks_passed"] or not checks["secret_exposure_clear"]:
            return ReviewDecision.BLOCKED
        if not checks["validation_passed"]:
            return ReviewDecision.CHANGES_REQUESTED
        return ReviewDecision.APPROVED

    def _blocking_reasons(
        self,
        checks: dict[str, bool],
        decision: ReviewDecision,
        policy_gate_failures: list[str],
        secret_exposure_findings: list[dict[str, Any]],
    ) -> list[str]:
        reasons: list[str] = []
        if not checks["diff_present"]:
            reasons.append("diff missing or empty")
        if not checks["acceptance_criteria_present"]:
            reasons.append("acceptance criteria missing")
        if not checks["validation_passed"]:
            reasons.append("validation did not pass")
        if not checks["policy_checks_passed"]:
            reasons.extend(policy_gate_failures or ["policy checks failed"])
        if not checks["secret_exposure_clear"]:
            reasons.append(
                f"secret-like content detected in {len(secret_exposure_findings)} location(s)"
            )
        if decision == ReviewDecision.AWAITING_HUMAN_APPROVAL:
            reasons.append("human approval required")
        return reasons

    def _build_review_summary(
        self,
        context: AgentContext,
        checks: dict[str, bool],
        decision: ReviewDecision,
        blocking_reasons: list[str],
    ) -> str:
        if self.model_router:
            return self._model_review(context, decision, checks, blocking_reasons).strip()
        return self._stub_review(context, decision, blocking_reasons).strip()

    def _stub_review(
        self,
        context: AgentContext,
        decision: ReviewDecision,
        blocking_reasons: list[str],
    ) -> str:
        if decision == ReviewDecision.APPROVED:
            return (
                f"Review approved. {len(context.files_modified)} file(s) changed, "
                "validation passed, acceptance criteria are present, and policy gates cleared."
            )
        if decision == ReviewDecision.CHANGES_REQUESTED:
            return "Review requested changes: validation did not pass."
        if decision == ReviewDecision.AWAITING_HUMAN_APPROVAL:
            return "Review is awaiting human approval before promotion."
        return f"Review blocked: {'; '.join(blocking_reasons) or 'required checks failed'}."

    def _diff_present(self, context: AgentContext) -> bool:
        if context.files_modified:
            return True
        diff_path = str(context.metadata.get("implementation_diff_path", "")).strip()
        if not diff_path:
            return False
        try:
            return bool(Path(diff_path).read_text(encoding="utf-8").strip())
        except OSError:
            return False

    def _validation_passed(self, context: AgentContext) -> bool:
        return context.validation_results.startswith("PASSED")

    def _policy_gate_failures(self, context: AgentContext) -> list[str]:
        metadata = context.metadata
        raw_failures = metadata.get(
            "policy_gate_failures",
            metadata.get("policy_check_failures", []),
        )
        failures: list[str] = []
        if isinstance(raw_failures, str):
            candidate = raw_failures.strip()
            if candidate:
                failures.append(candidate)
        else:
            for raw_failure in raw_failures or []:
                candidate = str(raw_failure).strip()
                if candidate:
                    failures.append(candidate)

        if (
            not self._metadata_flag(
                metadata,
                "policy_checks_passed",
                default=True,
            )
            and not failures
        ):
            failures.append("configured policy checks failed")
        return failures

    def _secret_exposure_findings(self, context: AgentContext) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        seen: set[tuple[str, int, str]] = set()

        repo_root = Path(context.repo_path) if context.repo_path else None
        for relative_path in context.files_modified:
            display_path = str(relative_path).strip()
            if not display_path:
                continue
            candidate = Path(display_path)
            if not candidate.is_absolute() and repo_root is not None:
                candidate = repo_root / candidate
            if not candidate.is_file():
                continue
            findings.extend(self._findings_from_file(candidate, display_path, seen))

        if findings:
            return findings

        diff_path = str(context.metadata.get("implementation_diff_path", "")).strip()
        if not diff_path:
            return findings
        try:
            diff_text = Path(diff_path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return findings
        findings.extend(self._findings_from_diff(diff_text, seen))
        return findings

    def _findings_from_file(
        self,
        path: Path,
        display_path: str,
        seen: set[tuple[str, int, str]],
    ) -> list[dict[str, Any]]:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []
        return self._findings_from_text(text, display_path, seen)

    def _findings_from_diff(
        self,
        diff_text: str,
        seen: set[tuple[str, int, str]],
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        current_path = "<diff>"
        line_number = 0
        for line in diff_text.splitlines():
            if line.startswith("+++ b/"):
                current_path = line[6:].strip() or current_path
                line_number = 0
                continue
            if line.startswith("@@"):
                match = re.search(r"\+(\d+)", line)
                line_number = int(match.group(1)) - 1 if match else line_number
                continue
            if line.startswith("+") and not line.startswith("+++"):
                line_number += 1
                findings.extend(
                    self._findings_from_text(line[1:], current_path, seen, start_line=line_number)
                )
                continue
            if not line.startswith("-"):
                line_number += 1
        return findings

    def _findings_from_text(
        self,
        text: str,
        display_path: str,
        seen: set[tuple[str, int, str]],
        *,
        start_line: int = 1,
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), start=start_line):
            for detector, pattern in SECRET_PATTERNS:
                if not pattern.search(line):
                    continue
                fingerprint = (display_path, line_number, detector)
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                findings.append(self._build_finding(display_path, line_number, detector, line))
            assignment_match = SECRET_ASSIGNMENT_PATTERN.search(line)
            if assignment_match is None:
                continue
            detector = f"{assignment_match.group(1).lower()}_assignment"
            secret_value = assignment_match.group(3).strip()
            if self._looks_like_placeholder(secret_value):
                continue
            fingerprint = (display_path, line_number, detector)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            findings.append(self._build_finding(display_path, line_number, detector, line))
        return findings

    def _build_finding(
        self,
        display_path: str,
        line_number: int,
        detector: str,
        line: str,
    ) -> dict[str, Any]:
        return {
            "path": display_path,
            "line": line_number,
            "detector": detector,
            "preview": self._redact_secret_line(line),
        }

    def _redact_secret_line(self, line: str) -> str:
        redacted = line.strip()
        for _, pattern in SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)
        redacted = SECRET_ASSIGNMENT_PATTERN.sub(
            lambda match: f"{match.group(1)}={match.group(2)}[REDACTED_SECRET]{match.group(2)}",
            redacted,
        )
        return redacted[:160]

    def _looks_like_placeholder(self, value: str) -> bool:
        normalized = value.strip().lower()
        if len(normalized) < 8:
            return True
        return any(fragment in normalized for fragment in PLACEHOLDER_SECRET_FRAGMENTS)

    def _metadata_flag(
        self,
        metadata: dict[str, Any],
        key: str,
        *,
        default: bool = False,
    ) -> bool:
        value = metadata.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off", ""}:
                return False
        return bool(value)

    def _model_review(
        self,
        context: AgentContext,
        decision: ReviewDecision,
        checks: dict[str, bool],
        blocking_reasons: list[str],
    ) -> str:
        prompt = (
            f"You are a senior engineer reviewing code changes.\n"
            f"Files modified: {context.files_modified}\n"
            f"Validation results: {context.validation_results or 'not available'}\n"
            f"Decision: {decision.value}\n"
            f"Checks: {checks}\n"
            f"Blocking reasons: {blocking_reasons}\n"
            "Provide a brief 1-2 sentence review summary aligned with the decision."
        )
        try:
            return self.model_router.generate(prompt, model_key="reviewer")
        except Exception as exc:
            logger.debug("Model review failed: %s", exc)
            return self._stub_review(context, decision, blocking_reasons)
