"""Tests for PipelineConfig: loading, validation, defaults, and CLI integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from autodev.core.config import (
    ConfigError,
    PipelineConfig,
    RetryConfig,
    ValidationConfig,
    _CONFIG_SEARCH_PATHS,
)
from autodev.core.schemas import IsolationMode


# ---------------------------------------------------------------------------
# ValidationConfig
# ---------------------------------------------------------------------------


class TestValidationConfig:
    def test_defaults_are_safe(self):
        cfg = ValidationConfig()
        assert cfg.breadth == "targeted"
        assert cfg.stop_on_first_failure is True
        assert cfg.commands == []

    def test_valid_breadth_broader_fallback(self):
        cfg = ValidationConfig(breadth="broader-fallback")
        assert cfg.breadth == "broader-fallback"

    def test_invalid_breadth_raises(self):
        with pytest.raises(Exception, match="breadth"):
            ValidationConfig(breadth="full")

    def test_explicit_commands(self):
        cfg = ValidationConfig(commands=["pytest -q", "ruff check ."])
        assert cfg.commands == ["pytest -q", "ruff check ."]

    def test_extra_key_forbidden(self):
        with pytest.raises(Exception):
            ValidationConfig(**{"breadth": "targeted", "unknown_key": True})


# ---------------------------------------------------------------------------
# RetryConfig
# ---------------------------------------------------------------------------


class TestRetryConfig:
    def test_defaults_are_safe(self):
        cfg = RetryConfig()
        assert cfg.max_retries == 0
        assert cfg.backoff_base == 2.0

    def test_positive_max_retries(self):
        assert RetryConfig(max_retries=3).max_retries == 3

    def test_negative_max_retries_raises(self):
        with pytest.raises(Exception):
            RetryConfig(max_retries=-1)

    def test_zero_backoff_base_raises(self):
        with pytest.raises(Exception):
            RetryConfig(backoff_base=0)

    def test_extra_key_forbidden(self):
        with pytest.raises(Exception):
            RetryConfig(**{"max_retries": 0, "jitter": True})


# ---------------------------------------------------------------------------
# PipelineConfig — defaults
# ---------------------------------------------------------------------------


class TestPipelineConfigDefaults:
    def test_all_safe_defaults(self):
        cfg = PipelineConfig()
        assert cfg.isolation_mode == IsolationMode.SNAPSHOT
        assert cfg.max_iterations == 3
        assert cfg.dry_run is False
        assert isinstance(cfg.validation, ValidationConfig)
        assert isinstance(cfg.retry, RetryConfig)

    def test_max_iterations_ge_1(self):
        with pytest.raises(Exception):
            PipelineConfig(max_iterations=0)

    def test_extra_key_forbidden(self):
        with pytest.raises(Exception):
            PipelineConfig(**{"isolation_mode": "snapshot", "unknown": "x"})


# ---------------------------------------------------------------------------
# PipelineConfig — from_yaml_str
# ---------------------------------------------------------------------------


class TestPipelineConfigFromYamlStr:
    def test_empty_yaml_uses_defaults(self):
        cfg = PipelineConfig.from_yaml_str("")
        assert cfg.isolation_mode == IsolationMode.SNAPSHOT
        assert cfg.max_iterations == 3

    def test_partial_override(self):
        yaml = "max_iterations: 5\ndry_run: true\n"
        cfg = PipelineConfig.from_yaml_str(yaml)
        assert cfg.max_iterations == 5
        assert cfg.dry_run is True
        assert cfg.isolation_mode == IsolationMode.SNAPSHOT  # default preserved

    def test_isolation_mode_branch(self):
        cfg = PipelineConfig.from_yaml_str("isolation_mode: branch\n")
        assert cfg.isolation_mode == IsolationMode.BRANCH

    def test_isolation_mode_worktree(self):
        cfg = PipelineConfig.from_yaml_str("isolation_mode: worktree\n")
        assert cfg.isolation_mode == IsolationMode.WORKTREE

    def test_nested_validation_section(self):
        yaml = "validation:\n  breadth: broader-fallback\n  stop_on_first_failure: false\n"
        cfg = PipelineConfig.from_yaml_str(yaml)
        assert cfg.validation.breadth == "broader-fallback"
        assert cfg.validation.stop_on_first_failure is False

    def test_validation_commands(self):
        yaml = "validation:\n  commands:\n    - pytest -q\n    - ruff check .\n"
        cfg = PipelineConfig.from_yaml_str(yaml)
        assert cfg.validation.commands == ["pytest -q", "ruff check ."]

    def test_retry_section(self):
        yaml = "retry:\n  max_retries: 2\n  backoff_base: 1.5\n"
        cfg = PipelineConfig.from_yaml_str(yaml)
        assert cfg.retry.max_retries == 2
        assert cfg.retry.backoff_base == 1.5

    def test_invalid_yaml_raises_config_error(self):
        with pytest.raises(ConfigError, match="Invalid YAML"):
            PipelineConfig.from_yaml_str("key: [unclosed")

    def test_non_mapping_yaml_raises_config_error(self):
        with pytest.raises(ConfigError, match="must be a YAML mapping"):
            PipelineConfig.from_yaml_str("- item1\n- item2\n")

    def test_unknown_top_level_key_raises_config_error(self):
        with pytest.raises(ConfigError, match="Invalid pipeline config"):
            PipelineConfig.from_yaml_str("bogus_key: true\n")

    def test_invalid_field_value_raises_config_error(self):
        with pytest.raises(ConfigError, match="Invalid pipeline config"):
            PipelineConfig.from_yaml_str("max_iterations: 0\n")

    def test_invalid_nested_field_raises_config_error(self):
        with pytest.raises(ConfigError, match="Invalid pipeline config"):
            PipelineConfig.from_yaml_str("validation:\n  breadth: everything\n")

    def test_source_appears_in_error_message(self):
        with pytest.raises(ConfigError, match="myfile.yaml"):
            PipelineConfig.from_yaml_str("bogus: x\n", source="myfile.yaml")


# ---------------------------------------------------------------------------
# PipelineConfig — load (file)
# ---------------------------------------------------------------------------


class TestPipelineConfigLoad:
    def test_load_valid_file(self, tmp_path: Path):
        cfg_file = tmp_path / "pipeline.yaml"
        cfg_file.write_text("max_iterations: 5\ndry_run: true\n")
        cfg = PipelineConfig.load(cfg_file)
        assert cfg.max_iterations == 5
        assert cfg.dry_run is True

    def test_load_missing_file_raises_config_error(self, tmp_path: Path):
        with pytest.raises(ConfigError, match="Cannot read config file"):
            PipelineConfig.load(tmp_path / "missing.yaml")

    def test_load_invalid_yaml_raises_config_error(self, tmp_path: Path):
        cfg_file = tmp_path / "bad.yaml"
        cfg_file.write_text("key: [unclosed")
        with pytest.raises(ConfigError, match="Invalid YAML"):
            PipelineConfig.load(cfg_file)

    def test_load_unknown_key_raises_config_error(self, tmp_path: Path):
        cfg_file = tmp_path / "extra.yaml"
        cfg_file.write_text("totally_unknown: yes\n")
        with pytest.raises(ConfigError, match="Invalid pipeline config"):
            PipelineConfig.load(cfg_file)

    def test_load_accepts_string_path(self, tmp_path: Path):
        cfg_file = tmp_path / "pipeline.yaml"
        cfg_file.write_text("dry_run: true\n")
        cfg = PipelineConfig.load(str(cfg_file))
        assert cfg.dry_run is True


# ---------------------------------------------------------------------------
# PipelineConfig — discover
# ---------------------------------------------------------------------------


class TestPipelineConfigDiscover:
    def test_no_files_returns_defaults(self, tmp_path: Path):
        cfg = PipelineConfig.discover(search_paths=[tmp_path / "none.yaml"])
        assert cfg.isolation_mode == IsolationMode.SNAPSHOT
        assert cfg.max_iterations == 3

    def test_first_match_wins(self, tmp_path: Path):
        first = tmp_path / "first.yaml"
        second = tmp_path / "second.yaml"
        first.write_text("max_iterations: 7\n")
        second.write_text("max_iterations: 9\n")
        cfg = PipelineConfig.discover(search_paths=[first, second])
        assert cfg.max_iterations == 7

    def test_skips_missing_finds_next(self, tmp_path: Path):
        missing = tmp_path / "missing.yaml"
        found = tmp_path / "found.yaml"
        found.write_text("dry_run: true\n")
        cfg = PipelineConfig.discover(search_paths=[missing, found])
        assert cfg.dry_run is True

    def test_invalid_file_raises_config_error(self, tmp_path: Path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("nope: true\n")
        with pytest.raises(ConfigError):
            PipelineConfig.discover(search_paths=[bad])


# ---------------------------------------------------------------------------
# PipelineConfig — as_context_metadata
# ---------------------------------------------------------------------------


class TestAsContextMetadata:
    def test_default_config_includes_breadth_and_stop(self):
        meta = PipelineConfig().as_context_metadata()
        assert meta["validation_breadth"] == "targeted"
        assert meta["validation_stop_on_first_failure"] is True

    def test_commands_omitted_when_empty(self):
        meta = PipelineConfig().as_context_metadata()
        assert "validation_commands" not in meta

    def test_commands_included_when_non_empty(self):
        cfg = PipelineConfig.from_yaml_str(
            "validation:\n  commands:\n    - pytest\n    - ruff check .\n"
        )
        meta = cfg.as_context_metadata()
        assert meta["validation_commands"] == ["pytest", "ruff check ."]

    def test_non_default_breadth_reflected(self):
        cfg = PipelineConfig.from_yaml_str("validation:\n  breadth: broader-fallback\n")
        assert cfg.as_context_metadata()["validation_breadth"] == "broader-fallback"

    def test_stop_on_first_failure_false(self):
        cfg = PipelineConfig.from_yaml_str(
            "validation:\n  stop_on_first_failure: false\n"
        )
        assert cfg.as_context_metadata()["validation_stop_on_first_failure"] is False


# ---------------------------------------------------------------------------
# Orchestrator integration: pipeline_config wired in
# ---------------------------------------------------------------------------


class TestOrchestratorPipelineConfigIntegration:
    def test_orchestrator_stores_pipeline_config(self, tmp_path: Path):
        from autodev.core.runtime import Orchestrator

        cfg = PipelineConfig.from_yaml_str("max_iterations: 7\n")
        orch = Orchestrator(max_iterations=7, work_dir=str(tmp_path), pipeline_config=cfg)
        assert orch.pipeline_config is cfg

    def test_orchestrator_uses_default_config_when_none_given(self, tmp_path: Path):
        from autodev.core.runtime import Orchestrator

        orch = Orchestrator(work_dir=str(tmp_path))
        assert isinstance(orch.pipeline_config, PipelineConfig)

    def test_pipeline_config_seeds_context_metadata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Validation config from PipelineConfig appears in the context by plan time."""
        from typing import Any

        from autodev.agents.base import AgentContext
        from autodev.core.runtime import Orchestrator
        from autodev.core.schemas import (
            ReviewDecision,
            ValidationCommandResult,
            ValidationResult,
            ValidationStatus,
        )

        cfg = PipelineConfig.from_yaml_str(
            "validation:\n  breadth: broader-fallback\n  stop_on_first_failure: false\n"
        )
        orch = Orchestrator(work_dir=str(tmp_path), dry_run=True, pipeline_config=cfg)

        captured: dict[str, Any] = {}

        def _stub_plan(self: Any, task: str, ctx: AgentContext) -> AgentContext:
            captured.update(ctx.metadata)
            return ctx.model_copy(update={"plan": ["step 1"]})

        def _stub_implement(self: Any, task: str, ctx: AgentContext) -> AgentContext:
            return ctx.model_copy(
                update={"files_modified": [], "metadata": {**ctx.metadata}}
            )

        def _stub_validate(
            self: Any,
            repo_path: str = ".",
            *,
            task_id: str,
            changed_files: Any = None,
            explicit_commands: Any = None,
            validation_breadth: str = "targeted",
            stop_on_first_failure: bool = True,
        ) -> ValidationResult:
            return ValidationResult(
                task_id=task_id,
                status=ValidationStatus.PASSED,
                commands=[
                    ValidationCommandResult(
                        command="pytest",
                        exit_code=0,
                        status=ValidationStatus.PASSED,
                    )
                ],
            )

        def _stub_review(self: Any, task: str, ctx: AgentContext) -> AgentContext:
            return ctx.model_copy(
                update={
                    "metadata": {
                        **ctx.metadata,
                        "review_decision": ReviewDecision.APPROVED.value,
                        "review_summary": "ok",
                        "review_blocking_reasons": [],
                    }
                }
            )

        monkeypatch.setattr("autodev.agents.planner.PlannerAgent.run", _stub_plan)
        monkeypatch.setattr("autodev.agents.coder.CoderAgent.run", _stub_implement)
        monkeypatch.setattr(
            "autodev.tools.test_runner.TestRunner.run_validation", _stub_validate
        )
        monkeypatch.setattr("autodev.agents.reviewer.ReviewerAgent.run", _stub_review)
        monkeypatch.setattr(orch, "_read_issue", lambda ctx: ctx)

        orch.run_pipeline("https://github.com/octocat/Hello-World/issues/1")

        assert captured.get("validation_breadth") == "broader-fallback"
        assert captured.get("validation_stop_on_first_failure") is False
