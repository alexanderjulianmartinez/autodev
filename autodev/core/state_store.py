"""File-backed durable state store for AutoDev runtime records."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

from pydantic import BaseModel

from autodev.core.schemas import (
    BacklogItem,
    ReviewResult,
    RunMetadata,
    TaskRecord,
    TaskResult,
    ValidationResult,
)

ModelType = TypeVar("ModelType", bound=BaseModel)


class FileStateStore:
    """Persist runtime state to predictable JSON files with atomic writes."""

    def __init__(self, root_path: str) -> None:
        self.root_path = Path(root_path).expanduser().resolve()
        self.root_path.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    @property
    def backlog_dir(self) -> Path:
        return self._ensure_dir("backlog")

    @property
    def tasks_dir(self) -> Path:
        return self._ensure_dir("tasks")

    @property
    def runs_dir(self) -> Path:
        return self._ensure_dir("runs")

    @property
    def reports_dir(self) -> Path:
        return self._ensure_dir("reports")

    @property
    def scheduler_dir(self) -> Path:
        return self._ensure_dir("scheduler")

    def _ensure_dir(self, relative_path: str) -> Path:
        directory = self.root_path / relative_path
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _backlog_path(self, item_id: str) -> Path:
        return self.backlog_dir / f"{item_id}.json"

    def _task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.json"

    def _run_dir(self, run_id: str) -> Path:
        return self._ensure_dir(f"runs/{run_id}")

    def _run_metadata_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "metadata.json"

    def _run_task_result_path(self, run_id: str, task_id: str) -> Path:
        task_results_dir = self._run_dir(run_id) / "task_results"
        task_results_dir.mkdir(parents=True, exist_ok=True)
        return task_results_dir / f"{task_id}.json"

    def _run_validation_path(self, run_id: str, task_id: str) -> Path:
        validation_dir = self._run_dir(run_id) / "validation"
        validation_dir.mkdir(parents=True, exist_ok=True)
        return validation_dir / f"{task_id}.json"

    def _run_review_path(self, run_id: str, task_id: str) -> Path:
        review_dir = self._run_dir(run_id) / "reviews"
        review_dir.mkdir(parents=True, exist_ok=True)
        return review_dir / f"{task_id}.json"

    def _report_path(self, report_name: str) -> Path:
        return self.reports_dir / f"{report_name}.json"

    def _scheduler_state_path(self) -> Path:
        return self.scheduler_dir / "state.json"

    def _scheduler_history_path(self) -> Path:
        return self.scheduler_dir / "history.json"

    # ------------------------------------------------------------------
    # Backlog items
    # ------------------------------------------------------------------

    def save_backlog_item(self, item: BacklogItem) -> Path:
        path = self._backlog_path(item.item_id)
        self._write_model(path, item)
        return path

    def load_backlog_item(self, item_id: str) -> BacklogItem:
        return self._read_model(self._backlog_path(item_id), BacklogItem)

    def list_backlog_items(self) -> list[BacklogItem]:
        return self._list_models(self.backlog_dir, BacklogItem)

    def update_backlog_item(
        self,
        item_id: str,
        updater: Callable[[BacklogItem], BacklogItem],
    ) -> BacklogItem:
        updated = updater(self.load_backlog_item(item_id))
        self.save_backlog_item(updated)
        return updated

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def save_task(self, task: TaskRecord) -> Path:
        path = self._task_path(task.task_id)
        self._write_model(path, task)
        return path

    def load_task(self, task_id: str) -> TaskRecord:
        return self._read_model(self._task_path(task_id), TaskRecord)

    def list_tasks(self) -> list[TaskRecord]:
        return self._list_models(self.tasks_dir, TaskRecord)

    def update_task(
        self,
        task_id: str,
        updater: Callable[[TaskRecord], TaskRecord],
    ) -> TaskRecord:
        updated = updater(self.load_task(task_id))
        self.save_task(updated)
        return updated

    # ------------------------------------------------------------------
    # Runs and per-run artifacts
    # ------------------------------------------------------------------

    def save_run(self, run: RunMetadata) -> Path:
        path = self._run_metadata_path(run.run_id)
        self._write_model(path, run)
        return path

    def load_run(self, run_id: str) -> RunMetadata:
        return self._read_model(self._run_metadata_path(run_id), RunMetadata)

    def list_runs(self) -> list[RunMetadata]:
        run_paths = sorted(self.runs_dir.glob("*/metadata.json"))
        return [self._read_model(path, RunMetadata) for path in run_paths]

    def update_run(
        self,
        run_id: str,
        updater: Callable[[RunMetadata], RunMetadata],
    ) -> RunMetadata:
        updated = updater(self.load_run(run_id))
        self.save_run(updated)
        return updated

    def save_task_result(self, run_id: str, result: TaskResult) -> Path:
        path = self._run_task_result_path(run_id, result.task_id)
        self._write_model(path, result)
        return path

    def load_task_result(self, run_id: str, task_id: str) -> TaskResult:
        return self._read_model(self._run_task_result_path(run_id, task_id), TaskResult)

    def list_task_results(self, run_id: str) -> list[TaskResult]:
        directory = self._run_dir(run_id) / "task_results"
        return self._list_models(directory, TaskResult)

    def save_validation_result(self, run_id: str, result: ValidationResult) -> Path:
        path = self._run_validation_path(run_id, result.task_id)
        self._write_model(path, result)
        return path

    def load_validation_result(self, run_id: str, task_id: str) -> ValidationResult:
        return self._read_model(self._run_validation_path(run_id, task_id), ValidationResult)

    def list_validation_results(self, run_id: str) -> list[ValidationResult]:
        directory = self._run_dir(run_id) / "validation"
        return self._list_models(directory, ValidationResult)

    def save_review_result(self, run_id: str, result: ReviewResult) -> Path:
        path = self._run_review_path(run_id, result.task_id)
        self._write_model(path, result)
        return path

    def load_review_result(self, run_id: str, task_id: str) -> ReviewResult:
        return self._read_model(self._run_review_path(run_id, task_id), ReviewResult)

    def list_review_results(self, run_id: str) -> list[ReviewResult]:
        directory = self._run_dir(run_id) / "reviews"
        return self._list_models(directory, ReviewResult)

    # ------------------------------------------------------------------
    # Reports and scheduler state
    # ------------------------------------------------------------------

    def save_report(self, report_name: str, payload: dict[str, Any]) -> Path:
        path = self._report_path(report_name)
        self._write_json(path, payload)
        return path

    def load_report(self, report_name: str) -> dict[str, Any]:
        return self._read_json(self._report_path(report_name))

    def list_reports(self) -> list[str]:
        return sorted(path.stem for path in self.reports_dir.glob("*.json"))

    def save_scheduler_state(self, payload: dict[str, Any]) -> Path:
        path = self._scheduler_state_path()
        self._write_json(path, payload)
        return path

    def load_scheduler_state(self) -> dict[str, Any]:
        return self._read_json(self._scheduler_state_path())

    def append_scheduler_history(self, event: dict[str, Any]) -> Path:
        history = self.load_scheduler_history()
        history.append(event)
        path = self._scheduler_history_path()
        self._write_json(path, history)
        return path

    def load_scheduler_history(self) -> list[dict[str, Any]]:
        path = self._scheduler_history_path()
        if not path.exists():
            return []
        payload = self._read_json(path)
        if not isinstance(payload, list):
            raise ValueError("Scheduler history must be a JSON list")
        return payload

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_model(self, path: Path, model: BaseModel) -> None:
        self._write_json(path, model.model_dump(mode="json"))

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path_str = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temp_path = Path(temp_path_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def _read_json(self, path: Path) -> Any:
        if not path.exists():
            raise FileNotFoundError(path)
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_model(self, path: Path, model_type: type[ModelType]) -> ModelType:
        if not path.exists():
            raise FileNotFoundError(path)
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))

    def _list_models(self, directory: Path, model_type: type[ModelType]) -> list[ModelType]:
        if not directory.exists():
            return []
        paths: Iterable[Path] = sorted(directory.glob("*.json"))
        return [self._read_model(path, model_type) for path in paths]
