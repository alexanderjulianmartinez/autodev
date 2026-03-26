"""RunReporter: write per-run summary artifacts and append to global history reports."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autodev.core.schemas import RunStatus, ValidationStatus
from autodev.core.state_store import FileStateStore

logger = logging.getLogger(__name__)

# Stable report names used across runs — these names are part of the public API.
VALIDATION_HISTORY_REPORT = "validation-history"
FAILURE_HISTORY_REPORT = "failure-history"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunReporter:
    """Collect run artifacts and write summary + history reports.

    Called once at the end of each pipeline run.  All writes are best-effort:
    individual failures are logged but never raised to the caller.
    """

    def __init__(self, state_store: FileStateStore) -> None:
        self.state_store = state_store

    def write(
        self,
        run_id: str,
        *,
        status: RunStatus,
        stage_outputs: dict[str, Any],
        context_metadata: dict[str, Any],
        files_modified: list[str],
    ) -> Path | None:
        """Write summary artifacts for *run_id* and return the summary JSON path."""
        try:
            run_meta = self.state_store.load_run(run_id)
        except Exception:
            logger.warning("RunReporter: could not load run %r; skipping report.", run_id)
            return None

        validation_results = self.state_store.list_validation_results(run_id)
        review_results = self.state_store.list_review_results(run_id)
        task_results = self.state_store.list_task_results(run_id)

        summary = self._build_summary(
            run_meta=run_meta,
            status=status,
            stage_outputs=stage_outputs,
            context_metadata=context_metadata,
            files_modified=files_modified,
            validation_results=validation_results,
            review_results=review_results,
            task_results=task_results,
        )

        run_dir = self.state_store.run_dir(run_id)
        summary_json_path = self._write_json_summary(run_dir, summary)
        self._write_md_summary(run_dir, summary)
        self._append_validation_history(run_id, run_meta.backlog_item_id, validation_results)
        if status == RunStatus.FAILED:
            self._append_failure_history(run_id, run_meta.backlog_item_id, stage_outputs)

        return summary_json_path

    # ------------------------------------------------------------------
    # Summary construction
    # ------------------------------------------------------------------

    def _build_summary(
        self,
        *,
        run_meta,
        status: RunStatus,
        stage_outputs: dict[str, Any],
        context_metadata: dict[str, Any],
        files_modified: list[str],
        validation_results,
        review_results,
        task_results,
    ) -> dict[str, Any]:
        run_dir = self.state_store.run_dir(run_meta.run_id)

        validation_summary = self._validation_summary(validation_results)
        review_summary = self._review_summary(review_results, context_metadata)
        promotion_summary = self._promotion_summary(context_metadata)
        failure_summary = self._failure_summary(stage_outputs)

        artifact_paths: dict[str, Any] = {
            "summary_json": str(run_dir / "summary.json"),
            "summary_md": str(run_dir / "summary.md"),
        }
        for key in (
            "planning_artifact_path",
            "implementation_diff_path",
            "changed_files_path",
            "validation_result_path",
            "review_result_path",
        ):
            value = str(context_metadata.get(key, "")).strip()
            if value:
                artifact_paths[key] = value

        summary: dict[str, Any] = {
            "run_id": run_meta.run_id,
            "backlog_item_id": run_meta.backlog_item_id,
            "status": status.value,
            "issue_url": context_metadata.get("issue_url", ""),
            "issue_title": context_metadata.get("issue_title", ""),
            "created_at": run_meta.created_at.isoformat(),
            "completed_at": _utc_now_iso(),
            "workspace_path": run_meta.workspace_path,
            "isolation_mode": run_meta.isolation_mode.value,
            "files_modified": files_modified,
            "stages": stage_outputs,
            "validation": validation_summary,
            "review": review_summary,
            "promotion": promotion_summary,
            "artifact_paths": artifact_paths,
        }
        if failure_summary:
            summary["failures"] = failure_summary
        return summary

    def _validation_summary(self, validation_results) -> dict[str, Any]:
        if not validation_results:
            return {"status": "not_run", "commands_run": 0, "commands_passed": 0}
        commands: list[dict[str, Any]] = []
        for vr in validation_results:
            for cmd_result in vr.commands:
                commands.append(
                    {
                        "command": cmd_result.command,
                        "exit_code": cmd_result.exit_code,
                        "passed": cmd_result.exit_code == 0,
                    }
                )
        passed = sum(1 for c in commands if c["passed"])
        overall = validation_results[-1].status if validation_results else ValidationStatus.SKIPPED
        return {
            "status": overall.value,
            "commands_run": len(commands),
            "commands_passed": passed,
            "commands": commands,
        }

    def _review_summary(self, review_results, context_metadata: dict[str, Any]) -> dict[str, Any]:
        decision = str(context_metadata.get("review_decision", "")).strip()
        review_text = str(
            context_metadata.get("review_summary", context_metadata.get("review", ""))
        ).strip()
        blocking = list(context_metadata.get("review_blocking_reasons", []))

        if review_results:
            latest = review_results[-1]
            decision = decision or latest.decision.value
            review_text = review_text or latest.summary

        result: dict[str, Any] = {"decision": decision or "not_run", "summary": review_text}
        if blocking:
            result["blocking_reasons"] = blocking
        return result

    def _promotion_summary(self, context_metadata: dict[str, Any]) -> dict[str, Any]:
        mode = str(context_metadata.get("promotion_mode", "")).strip()
        pr_url = str(context_metadata.get("pr_url", "")).strip()
        branch = str(context_metadata.get("promotion_branch", "")).strip()
        patch_path = str(context_metadata.get("promotion_patch_path", "")).strip()
        skipped_reason = str(context_metadata.get("promotion_skipped_reason", "")).strip()

        result: dict[str, Any] = {"mode": mode or "none"}
        if pr_url:
            result["pr_url"] = pr_url
        if branch:
            result["branch"] = branch
        if patch_path:
            result["patch_path"] = patch_path
        if skipped_reason:
            result["skipped_reason"] = skipped_reason
        return result

    def _failure_summary(self, stage_outputs: dict[str, Any]) -> list[dict[str, Any]]:
        failures = []
        for stage, output in stage_outputs.items():
            if isinstance(output, dict) and output.get("status") == "failed":
                entry: dict[str, Any] = {
                    "stage": stage,
                    "message": output.get("message", ""),
                }
                if "failure_class" in output:
                    entry["failure_class"] = output["failure_class"]
                failures.append(entry)
        return failures

    # ------------------------------------------------------------------
    # File writing
    # ------------------------------------------------------------------

    def _write_json_summary(self, run_dir: Path, summary: dict[str, Any]) -> Path:
        import json

        path = run_dir / "summary.json"
        try:
            path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
            logger.debug("Run summary JSON written to %s", path)
        except Exception:
            logger.warning("RunReporter: failed to write summary.json for %s", run_dir.name)
        return path

    def _write_md_summary(self, run_dir: Path, summary: dict[str, Any]) -> None:
        path = run_dir / "summary.md"
        try:
            path.write_text(self._render_md(summary), encoding="utf-8")
            logger.debug("Run summary Markdown written to %s", path)
        except Exception:
            logger.warning("RunReporter: failed to write summary.md for %s", run_dir.name)

    def _render_md(self, s: dict[str, Any]) -> str:
        status_icon = "✅" if s["status"] == "completed" else "❌"
        lines = [
            f"# Run Summary: {s['run_id']}",
            "",
            f"**Status:** {status_icon} {s['status']}  ",
            f"**Backlog item:** {s['backlog_item_id']}  ",
        ]
        if s.get("issue_title"):
            lines.append(f"**Issue title:** {s['issue_title']}  ")
        if s.get("issue_url"):
            lines.append(f"**Issue URL:** {s['issue_url']}  ")
        lines += [
            f"**Created:** {s['created_at']}  ",
            f"**Completed:** {s['completed_at']}  ",
            f"**Isolation:** {s['isolation_mode']}  ",
            "",
        ]

        # Stages
        lines.append("## Stages")
        lines.append("")
        for stage, output in s.get("stages", {}).items():
            if isinstance(output, dict):
                stage_status = output.get("status", "unknown")
                icon = (
                    "✅"
                    if stage_status == "completed"
                    else "⏭"
                    if stage_status == "skipped"
                    else "❌"
                )
                lines.append(f"- **{stage}**: {icon} {stage_status}")
                if output.get("failure_class"):
                    lines.append(f"  - failure class: `{output['failure_class']}`")
                if output.get("message") and stage_status not in {"completed", "skipped"}:
                    lines.append(f"  - message: {output['message']}")
        lines.append("")

        # Files
        if s.get("files_modified"):
            lines.append("## Files Modified")
            lines.append("")
            for f in s["files_modified"]:
                lines.append(f"- `{f}`")
            lines.append("")

        # Validation
        val = s.get("validation", {})
        lines.append("## Validation")
        lines.append("")
        lines.append(
            f"**Status:** {val.get('status', 'not_run')}  "
            f"({val.get('commands_passed', 0)}/{val.get('commands_run', 0)} commands passed)"
        )
        if val.get("commands"):
            lines.append("")
            for cmd in val["commands"]:
                icon = "✅" if cmd["passed"] else "❌"
                lines.append(f"- {icon} `{cmd['command']}` (exit {cmd['exit_code']})")
        lines.append("")

        # Review
        rev = s.get("review", {})
        lines.append("## Review")
        lines.append("")
        lines.append(f"**Decision:** {rev.get('decision', 'not_run')}  ")
        if rev.get("summary"):
            lines.append(f"**Summary:** {rev['summary']}  ")
        if rev.get("blocking_reasons"):
            lines.append("")
            lines.append("**Blocking reasons:**")
            for reason in rev["blocking_reasons"]:
                lines.append(f"- {reason}")
        lines.append("")

        # Promotion
        promo = s.get("promotion", {})
        if promo.get("mode") and promo["mode"] != "none":
            lines.append("## Promotion")
            lines.append("")
            lines.append(f"**Mode:** {promo['mode']}  ")
            if promo.get("pr_url"):
                lines.append(f"**PR:** {promo['pr_url']}  ")
            if promo.get("branch"):
                lines.append(f"**Branch:** {promo['branch']}  ")
            if promo.get("patch_path"):
                lines.append(f"**Patch:** {promo['patch_path']}  ")
            lines.append("")

        # Failures
        if s.get("failures"):
            lines.append("## Failures")
            lines.append("")
            for failure in s["failures"]:
                lines.append(f"- **{failure['stage']}**: {failure.get('message', '')}")
                if failure.get("failure_class"):
                    lines.append(f"  - class: `{failure['failure_class']}`")
            lines.append("")

        # Artifact paths
        paths = s.get("artifact_paths", {})
        if paths:
            lines.append("## Artifact Paths")
            lines.append("")
            for key, value in paths.items():
                lines.append(f"- `{key}`: `{value}`")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Global history reports
    # ------------------------------------------------------------------

    def _append_validation_history(
        self, run_id: str, backlog_item_id: str, validation_results
    ) -> None:
        if not validation_results:
            return
        for vr in validation_results:
            entry: dict[str, Any] = {
                "run_id": run_id,
                "backlog_item_id": backlog_item_id,
                "recorded_at": _utc_now_iso(),
                "task_id": vr.task_id,
                "status": vr.status.value,
                "commands_run": len(vr.commands),
                "commands_passed": sum(1 for c in vr.commands if c.exit_code == 0),
                "commands": [
                    {
                        "command": c.command,
                        "exit_code": c.exit_code,
                        "passed": c.exit_code == 0,
                    }
                    for c in vr.commands
                ],
            }
            try:
                self.state_store.append_report_entry(VALIDATION_HISTORY_REPORT, entry)
            except Exception:
                logger.warning(
                    "RunReporter: failed to append validation history for run %r", run_id
                )

    def _append_failure_history(
        self, run_id: str, backlog_item_id: str, stage_outputs: dict[str, Any]
    ) -> None:
        for stage, output in stage_outputs.items():
            if not isinstance(output, dict) or output.get("status") != "failed":
                continue
            entry: dict[str, Any] = {
                "run_id": run_id,
                "backlog_item_id": backlog_item_id,
                "failed_at": _utc_now_iso(),
                "stage": stage,
                "message": output.get("message", ""),
            }
            if "failure_class" in output:
                entry["failure_class"] = output["failure_class"]
            try:
                self.state_store.append_report_entry(FAILURE_HISTORY_REPORT, entry)
            except Exception:
                logger.warning("RunReporter: failed to append failure history for run %r", run_id)
