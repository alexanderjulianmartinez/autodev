"""CoderAgent: executes the implementation plan by modifying files."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from autodev.agents.base import Agent, AgentContext
from autodev.core.supervisor import Supervisor
from autodev.tools.filesystem_tool import FilesystemTool

logger = logging.getLogger(__name__)
PLAN_FILE_PATTERN = re.compile(r"(?P<path>[A-Za-z0-9_./-]+\.[A-Za-z0-9_-]+)")
SUPPORTED_TEXT_SUFFIXES = {".py", ".md", ".rst", ".txt", ".yaml", ".yml", ".json", ".toml"}


class CoderAgent(Agent):
    """Translates a plan into file modifications."""

    def __init__(
        self,
        model_router: Any = None,
        *,
        workspace_manager: Any = None,
        supervisor: Supervisor | None = None,
    ) -> None:
        super().__init__(model_router=model_router)
        self.workspace_manager = workspace_manager
        self.supervisor = supervisor or Supervisor()

    def run(self, task: str, context: AgentContext) -> AgentContext:
        logger.info("CoderAgent running task: %s", task)

        if not context.plan:
            logger.warning("No plan available; CoderAgent has nothing to do.")
            return context

        metadata = dict(context.metadata)
        files_modified: list[str] = list(context.files_modified)

        if context.repo_path:
            files_modified, implementation_metadata = self._apply_controlled_edits(
                context,
                files_modified,
            )
            metadata.update(implementation_metadata)
        elif self.model_router and context.repo_path:
            files_modified = self._apply_plan_with_model(context, files_modified)
        else:
            files_modified = self._apply_plan_stub(context, files_modified)

        logger.info("CoderAgent modified %d file(s)", len(files_modified))
        return context.model_copy(
            update={
                "files_modified": files_modified,
                "metadata": metadata,
            }
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _apply_controlled_edits(
        self,
        context: AgentContext,
        existing: list[str],
    ) -> tuple[list[str], dict[str, object]]:
        repo_root = Path(context.repo_path).expanduser().resolve()
        if not repo_root.exists() or not repo_root.is_dir():
            logger.warning(
                "Repository path %s is unavailable; falling back to stub tracking.",
                repo_root,
            )
            return self._apply_plan_stub(context, existing), {
                "implementation_status": "noop",
                "implementation_error": f"Repository path is unavailable: {repo_root}",
            }

        tool = FilesystemTool(base_path=str(repo_root), supervisor=self.supervisor)
        target_files = self._select_target_files(context)
        if not target_files:
            return existing, {
                "implementation_status": "noop",
                "implementation_edit_summaries": [],
            }

        applied_edits: list[dict[str, object]] = []
        for relative_path in target_files[:3]:
            try:
                applied_edits.append(
                    self._apply_single_edit(context, tool, repo_root, relative_path)
                )
            except Exception as exc:
                rollback_summary = self._rollback_edits(tool, repo_root, applied_edits)
                status = "partial" if rollback_summary["rollback_failed_files"] else "rolled_back"
                return list(existing), {
                    "implementation_status": status,
                    "implementation_error": str(exc),
                    "implementation_edit_summaries": applied_edits,
                    **rollback_summary,
                }

        updated_files = list(existing)
        for edit in applied_edits:
            path = str(edit["path"])
            if path not in updated_files:
                updated_files.append(path)

        return updated_files, {
            "implementation_status": "applied",
            "implementation_edit_summaries": applied_edits,
            "implementation_edited_files": [str(edit["path"]) for edit in applied_edits],
        }

    def _apply_plan_stub(self, context: AgentContext, existing: list[str]) -> list[str]:
        """Record planned file targets without actually writing."""
        targets: list[str] = list(existing)
        for step in context.plan:
            # Heuristic: pick out file references from the plan text
            for token in step.split():
                if "." in token and "/" not in token and token not in targets:
                    targets.append(token.strip(".,;:"))
        return targets

    def _apply_single_edit(
        self,
        context: AgentContext,
        tool: FilesystemTool,
        repo_root: Path,
        relative_path: str,
    ) -> dict[str, object]:
        target = (repo_root / relative_path).resolve()
        try:
            target.relative_to(repo_root)
        except ValueError as exc:
            raise ValueError(f"Target path escaped repository root: {relative_path!r}") from exc

        existed_before = target.exists()
        snapshot_path = ""
        original_content = ""
        if existed_before:
            original_content = tool.read_file(relative_path)
            snapshot_path = self._snapshot_existing_file(context, target)

        updated_content = self._build_updated_content(
            relative_path=relative_path,
            current_content=original_content,
            context=context,
        )
        tool.write_file(relative_path, updated_content)

        return {
            "path": relative_path,
            "action": "updated" if existed_before else "created",
            "snapshot_path": snapshot_path,
            "content_length": len(updated_content),
        }

    def _snapshot_existing_file(self, context: AgentContext, target: Path) -> str:
        run_id = str(context.metadata.get("run_id", "")).strip()
        if not run_id or self.workspace_manager is None:
            return ""
        snapshot = self.workspace_manager.snapshot_file(
            run_id, str(target), label="before-implement"
        )
        return str(snapshot)

    def _rollback_edits(
        self,
        tool: FilesystemTool,
        repo_root: Path,
        applied_edits: list[dict[str, object]],
    ) -> dict[str, object]:
        restored_files: list[str] = []
        rollback_failed_files: list[str] = []

        for edit in reversed(applied_edits):
            relative_path = str(edit["path"])
            target = (repo_root / relative_path).resolve()
            try:
                target.relative_to(repo_root)
                snapshot_path = str(edit.get("snapshot_path", "")).strip()
                if snapshot_path:
                    content = Path(snapshot_path).read_text(encoding="utf-8")
                    tool.write_file(relative_path, content)
                elif target.exists():
                    target.unlink()
                restored_files.append(relative_path)
            except Exception:
                rollback_failed_files.append(relative_path)

        return {
            "rolled_back_files": restored_files,
            "rollback_failed_files": rollback_failed_files,
        }

    def _select_target_files(self, context: AgentContext) -> list[str]:
        targets: list[str] = []
        for candidate in context.metadata.get("likely_target_files", []):
            normalized = self._normalize_target_path(str(candidate))
            if normalized and normalized not in targets:
                targets.append(normalized)

        for step in context.plan:
            for match in PLAN_FILE_PATTERN.finditer(step):
                normalized = self._normalize_target_path(match.group("path"))
                if normalized and normalized not in targets:
                    targets.append(normalized)

        return targets

    def _normalize_target_path(self, value: str) -> str:
        candidate = value.strip().strip("`'\".,;:()[]{}")
        if not candidate:
            return ""
        path = Path(candidate)
        if path.is_absolute():
            return ""
        if any(part in {".", "..", ""} for part in path.parts):
            return ""
        if path.suffix.lower() not in SUPPORTED_TEXT_SUFFIXES:
            return ""
        return path.as_posix()

    def _build_updated_content(
        self,
        *,
        relative_path: str,
        current_content: str,
        context: AgentContext,
    ) -> str:
        suffix = Path(relative_path).suffix.lower()
        note = self._implementation_note(context)

        if suffix == ".json":
            return self._update_json_content(current_content, note)
        if suffix == ".toml":
            return self._append_line_based_content(
                current_content,
                f'autodev_note = "{note}"\n',
            )
        if suffix in {".yaml", ".yml"}:
            return self._append_line_based_content(
                current_content,
                f'autodev_note: "{note}"\n',
            )
        if suffix in {".md", ".rst", ".txt"}:
            return self._append_line_based_content(
                current_content,
                f"\nAutoDev implementation note: {note}\n",
            )
        return self._append_line_based_content(
            current_content, f"\n# AutoDev implementation note: {note}\n"
        )

    def _append_line_based_content(self, current_content: str, addition: str) -> str:
        if current_content and not current_content.endswith("\n"):
            current_content = f"{current_content}\n"
        if addition.lstrip("\n") in current_content:
            return current_content
        return f"{current_content}{addition.lstrip() if not current_content else addition}"

    def _update_json_content(self, current_content: str, note: str) -> str:
        payload: dict[str, object]
        if current_content.strip():
            data = json.loads(current_content)
            if isinstance(data, dict):
                payload = dict(data)
            else:
                payload = {"autodev_note": note, "existing_value": data}
        else:
            payload = {}
        payload["autodev_note"] = note
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    def _implementation_note(self, context: AgentContext) -> str:
        issue_title = str(context.metadata.get("issue_title", "")).strip()
        if issue_title:
            return issue_title
        first_step = next((step for step in context.plan if step.strip()), "implementation update")
        return first_step[:120]

    def _apply_plan_with_model(self, context: AgentContext, existing: list[str]) -> list[str]:
        """Use model to generate file content, then write to disk."""
        targets: list[str] = list(existing)
        for step in context.plan:
            prompt = (
                f"Given this implementation step, identify the single most relevant "
                f"file path relative to the repository root: '{step}'. "
                f"Reply with ONLY the file path, nothing else."
            )
            try:
                file_path = self.model_router.generate(prompt, model_key="coder").strip()
                if file_path and context.repo_path:
                    full_path = os.path.join(context.repo_path, file_path)
                    if full_path not in targets:
                        targets.append(full_path)
            except Exception as exc:
                logger.debug("Model call failed for step %r: %s", step, exc)
        return targets
