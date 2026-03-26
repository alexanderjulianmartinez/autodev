"""Tests for IntegrationsConfig and IntegrationRegistry (AD-029)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from autodev.core.config import ConfigError
from autodev.integrations import (
    CapabilitySet,
    IntegrationRegistry,
    IntegrationsConfig,
    ProviderCapability,
    ProviderConfig,
    ProviderFactory,
    ProviderInfo,
)


# ---------------------------------------------------------------------------
# Stub providers used across tests
# ---------------------------------------------------------------------------


class _StubGitProvider:
    def __init__(self, settings: dict[str, str]) -> None:
        self.settings = settings

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(provider_id="stub-git", display_name="Stub Git")

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            operations=frozenset(
                {
                    ProviderCapability.FETCH_REPOSITORY,
                    ProviderCapability.CREATE_BRANCH,
                    ProviderCapability.CREATE_PULL_REQUEST,
                    ProviderCapability.GET_DIFF,
                    ProviderCapability.CLONE_REPOSITORY,
                }
            )
        )


class _StubCIProvider:
    def __init__(self, settings: dict[str, str]) -> None:
        self.settings = settings

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(provider_id="stub-ci", display_name="Stub CI")

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            operations=frozenset(
                {
                    ProviderCapability.FETCH_RUN,
                    ProviderCapability.TRIGGER_RUN,
                    ProviderCapability.LIST_RUNS,
                }
            )
        )


def _git_factory(settings: dict[str, str]) -> _StubGitProvider:
    return _StubGitProvider(settings)


def _ci_factory(settings: dict[str, str]) -> _StubCIProvider:
    return _StubCIProvider(settings)


def _make_registry(**extra_factories: ProviderFactory) -> IntegrationRegistry:
    """Return a registry pre-loaded with stub factories."""
    registry = IntegrationRegistry()
    registry.register_factory("stub-git", _git_factory, requires={"token"})
    registry.register_factory("stub-ci", _ci_factory, requires={"token"})
    for pid, factory in extra_factories.items():
        registry.register_factory(pid, factory)
    return registry


# ---------------------------------------------------------------------------
# ProviderConfig
# ---------------------------------------------------------------------------


class TestProviderConfig:
    def test_minimal(self):
        cfg = ProviderConfig(provider="github")
        assert cfg.provider == "github"
        assert cfg.settings == {}

    def test_with_settings(self):
        cfg = ProviderConfig(provider="github", settings={"token": "abc"})
        assert cfg.settings["token"] == "abc"

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ProviderConfig(provider="github", unknown="x")


# ---------------------------------------------------------------------------
# IntegrationsConfig — construction
# ---------------------------------------------------------------------------


class TestIntegrationsConfig:
    def test_empty_config_all_disabled(self):
        cfg = IntegrationsConfig()
        assert cfg.git is None
        assert cfg.issue_tracker is None
        assert cfg.ci is None
        assert cfg.monitoring is None
        assert cfg.messaging is None
        assert cfg.docs is None

    def test_partial_config(self):
        cfg = IntegrationsConfig(
            git=ProviderConfig(provider="github", settings={"token": "t"}),
        )
        assert cfg.git is not None
        assert cfg.git.provider == "github"
        assert cfg.issue_tracker is None

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            IntegrationsConfig(unknown_type=ProviderConfig(provider="x"))


# ---------------------------------------------------------------------------
# IntegrationsConfig — from_yaml_str
# ---------------------------------------------------------------------------


class TestIntegrationsConfigFromYaml:
    def test_empty_yaml_all_disabled(self):
        cfg = IntegrationsConfig.from_yaml_str("")
        assert cfg.git is None

    def test_direct_mapping(self):
        yaml = "git:\n  provider: github\n  settings:\n    token: abc\n"
        cfg = IntegrationsConfig.from_yaml_str(yaml)
        assert cfg.git is not None
        assert cfg.git.provider == "github"
        assert cfg.git.settings["token"] == "abc"

    def test_embedded_integrations_key(self):
        yaml = "integrations:\n  git:\n    provider: github\n    settings:\n      token: abc\n"
        cfg = IntegrationsConfig.from_yaml_str(yaml)
        assert cfg.git is not None
        assert cfg.git.provider == "github"

    def test_multiple_types(self):
        yaml = (
            "git:\n  provider: github\n  settings:\n    token: t1\n"
            "ci:\n  provider: stub-ci\n  settings:\n    token: t2\n"
        )
        cfg = IntegrationsConfig.from_yaml_str(yaml)
        assert cfg.git is not None
        assert cfg.ci is not None
        assert cfg.monitoring is None

    def test_invalid_yaml_raises_config_error(self):
        with pytest.raises(ConfigError, match="Invalid YAML"):
            IntegrationsConfig.from_yaml_str("key: [unclosed")

    def test_non_mapping_yaml_raises_config_error(self):
        with pytest.raises(ConfigError, match="must be a YAML mapping"):
            IntegrationsConfig.from_yaml_str("- item\n")

    def test_unknown_integration_type_raises_config_error(self):
        with pytest.raises(ConfigError, match="Invalid integration config"):
            IntegrationsConfig.from_yaml_str("unknown_type:\n  provider: x\n")

    def test_source_appears_in_error_message(self):
        with pytest.raises(ConfigError, match="myfile.yaml"):
            IntegrationsConfig.from_yaml_str(
                "unknown_type:\n  provider: x\n", source="myfile.yaml"
            )

    def test_missing_provider_key_raises_config_error(self):
        with pytest.raises(ConfigError, match="Invalid integration config"):
            IntegrationsConfig.from_yaml_str("git:\n  settings:\n    token: abc\n")


# ---------------------------------------------------------------------------
# IntegrationsConfig — load (file)
# ---------------------------------------------------------------------------


class TestIntegrationsConfigLoad:
    def test_load_valid_file(self, tmp_path: Path):
        f = tmp_path / "integrations.yaml"
        f.write_text("git:\n  provider: github\n  settings:\n    token: abc\n")
        cfg = IntegrationsConfig.load(f)
        assert cfg.git is not None
        assert cfg.git.provider == "github"

    def test_load_missing_file_raises_config_error(self, tmp_path: Path):
        with pytest.raises(ConfigError, match="Cannot read"):
            IntegrationsConfig.load(tmp_path / "missing.yaml")

    def test_load_invalid_yaml_raises_config_error(self, tmp_path: Path):
        f = tmp_path / "bad.yaml"
        f.write_text("key: [unclosed")
        with pytest.raises(ConfigError, match="Invalid YAML"):
            IntegrationsConfig.load(f)

    def test_load_accepts_string_path(self, tmp_path: Path):
        f = tmp_path / "integrations.yaml"
        f.write_text("ci:\n  provider: stub-ci\n  settings:\n    token: t\n")
        cfg = IntegrationsConfig.load(str(f))
        assert cfg.ci is not None


# ---------------------------------------------------------------------------
# IntegrationsConfig — discover
# ---------------------------------------------------------------------------


class TestIntegrationsConfigDiscover:
    def test_no_files_returns_defaults(self, tmp_path: Path):
        cfg = IntegrationsConfig.discover(search_paths=[tmp_path / "none.yaml"])
        assert cfg.git is None

    def test_first_match_wins(self, tmp_path: Path):
        first = tmp_path / "first.yaml"
        second = tmp_path / "second.yaml"
        first.write_text("git:\n  provider: first-git\n  settings:\n    token: t\n")
        second.write_text("git:\n  provider: second-git\n  settings:\n    token: t\n")
        cfg = IntegrationsConfig.discover(search_paths=[first, second])
        assert cfg.git is not None
        assert cfg.git.provider == "first-git"

    def test_skips_missing_finds_next(self, tmp_path: Path):
        missing = tmp_path / "missing.yaml"
        found = tmp_path / "found.yaml"
        found.write_text("ci:\n  provider: stub-ci\n  settings:\n    token: t\n")
        cfg = IntegrationsConfig.discover(search_paths=[missing, found])
        assert cfg.ci is not None

    def test_invalid_file_raises(self, tmp_path: Path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("unknown_type:\n  provider: x\n")
        with pytest.raises(ConfigError):
            IntegrationsConfig.discover(search_paths=[bad])


# ---------------------------------------------------------------------------
# IntegrationRegistry — factory registration
# ---------------------------------------------------------------------------


class TestRegistryFactoryRegistration:
    def test_register_factory_appears_in_registered_ids(self):
        registry = IntegrationRegistry()
        registry.register_factory("github", _git_factory)
        assert "github" in registry.registered_provider_ids()

    def test_register_multiple_factories(self):
        registry = IntegrationRegistry()
        registry.register_factory("github", _git_factory)
        registry.register_factory("gitlab", _git_factory)
        assert sorted(registry.registered_provider_ids()) == ["github", "gitlab"]

    def test_overwrite_factory_allowed(self):
        registry = IntegrationRegistry()
        registry.register_factory("github", _git_factory)
        registry.register_factory("github", _git_factory)  # overwrite
        assert registry.registered_provider_ids().count("github") == 1


# ---------------------------------------------------------------------------
# IntegrationRegistry — load: happy paths
# ---------------------------------------------------------------------------


class TestRegistryLoad:
    def test_load_single_provider(self):
        registry = _make_registry()
        cfg = IntegrationsConfig(
            git=ProviderConfig(provider="stub-git", settings={"token": "t"})
        )
        registry.load(cfg)
        assert registry.is_configured("git")
        assert not registry.is_configured("ci")

    def test_load_multiple_providers(self):
        registry = _make_registry()
        cfg = IntegrationsConfig(
            git=ProviderConfig(provider="stub-git", settings={"token": "t1"}),
            ci=ProviderConfig(provider="stub-ci", settings={"token": "t2"}),
        )
        registry.load(cfg)
        assert registry.is_configured("git")
        assert registry.is_configured("ci")

    def test_load_empty_config_clears_previous(self):
        registry = _make_registry()
        registry.load(
            IntegrationsConfig(
                git=ProviderConfig(provider="stub-git", settings={"token": "t"})
            )
        )
        registry.load(IntegrationsConfig())  # reload with nothing
        assert not registry.is_configured("git")

    def test_load_passes_settings_to_factory(self):
        registry = _make_registry()
        cfg = IntegrationsConfig(
            git=ProviderConfig(provider="stub-git", settings={"token": "my-token"})
        )
        registry.load(cfg)
        provider = registry.get("git")
        assert provider.settings["token"] == "my-token"

    def test_configured_types_returns_sorted(self):
        registry = _make_registry()
        registry.load(
            IntegrationsConfig(
                ci=ProviderConfig(provider="stub-ci", settings={"token": "t"}),
                git=ProviderConfig(provider="stub-git", settings={"token": "t"}),
            )
        )
        assert registry.configured_types() == ["ci", "git"]


# ---------------------------------------------------------------------------
# IntegrationRegistry — load: failure cases
# ---------------------------------------------------------------------------


class TestRegistryLoadFailures:
    def test_unknown_provider_raises_config_error(self):
        registry = IntegrationRegistry()
        # No factories registered
        cfg = IntegrationsConfig(
            git=ProviderConfig(provider="github", settings={"token": "t"})
        )
        with pytest.raises(ConfigError, match="unknown provider 'github'"):
            registry.load(cfg)

    def test_error_message_lists_registered_providers(self):
        registry = IntegrationRegistry()
        registry.register_factory("gitlab", _git_factory)
        cfg = IntegrationsConfig(
            git=ProviderConfig(provider="github", settings={"token": "t"})
        )
        with pytest.raises(ConfigError, match="gitlab"):
            registry.load(cfg)

    def test_missing_required_setting_raises_config_error(self):
        registry = _make_registry()
        # stub-git requires "token" — omit it
        cfg = IntegrationsConfig(
            git=ProviderConfig(provider="stub-git", settings={})
        )
        with pytest.raises(ConfigError, match="missing required settings"):
            registry.load(cfg)

    def test_error_message_names_missing_keys(self):
        registry = _make_registry()
        cfg = IntegrationsConfig(
            git=ProviderConfig(provider="stub-git", settings={})
        )
        with pytest.raises(ConfigError, match="token"):
            registry.load(cfg)

    def test_error_message_names_integration_type(self):
        registry = _make_registry()
        cfg = IntegrationsConfig(
            git=ProviderConfig(provider="stub-git", settings={})
        )
        with pytest.raises(ConfigError, match="'git'"):
            registry.load(cfg)

    def test_factory_exception_wrapped_in_config_error(self):
        registry = IntegrationRegistry()

        def boom(settings: dict[str, str]) -> None:
            raise RuntimeError("network unreachable")

        registry.register_factory("exploding-git", boom)
        cfg = IntegrationsConfig(
            git=ProviderConfig(provider="exploding-git", settings={})
        )
        with pytest.raises(ConfigError, match="failed to initialize"):
            registry.load(cfg)

    def test_factory_config_error_propagates_unchanged(self):
        """ConfigError raised inside a factory is not double-wrapped."""
        registry = IntegrationRegistry()

        def raises_config_error(settings: dict[str, str]) -> None:
            raise ConfigError("bad token format")

        registry.register_factory("bad-git", raises_config_error)
        cfg = IntegrationsConfig(
            git=ProviderConfig(provider="bad-git", settings={})
        )
        with pytest.raises(ConfigError, match="bad token format"):
            registry.load(cfg)


# ---------------------------------------------------------------------------
# IntegrationRegistry — resolve and get
# ---------------------------------------------------------------------------


class TestRegistryResolve:
    def _loaded_registry(self) -> IntegrationRegistry:
        registry = _make_registry()
        registry.load(
            IntegrationsConfig(
                git=ProviderConfig(provider="stub-git", settings={"token": "t"}),
                ci=ProviderConfig(provider="stub-ci", settings={"token": "t"}),
            )
        )
        return registry

    def test_resolve_git_capability_returns_git_provider(self):
        registry = self._loaded_registry()
        provider = registry.resolve(ProviderCapability.CREATE_PULL_REQUEST)
        assert isinstance(provider, _StubGitProvider)

    def test_resolve_another_git_capability(self):
        registry = self._loaded_registry()
        provider = registry.resolve(ProviderCapability.FETCH_REPOSITORY)
        assert isinstance(provider, _StubGitProvider)

    def test_resolve_ci_capability_returns_ci_provider(self):
        registry = self._loaded_registry()
        provider = registry.resolve(ProviderCapability.FETCH_RUN)
        assert isinstance(provider, _StubCIProvider)

    def test_resolve_unconfigured_type_raises_lookup_error(self):
        registry = self._loaded_registry()
        # monitoring is not configured
        with pytest.raises(LookupError, match="monitoring"):
            registry.resolve(ProviderCapability.FETCH_ALERTS)

    def test_get_configured_type(self):
        registry = self._loaded_registry()
        provider = registry.get("git")
        assert isinstance(provider, _StubGitProvider)

    def test_get_unconfigured_type_raises_lookup_error(self):
        registry = self._loaded_registry()
        with pytest.raises(LookupError, match="messaging"):
            registry.get("messaging")

    def test_lookup_error_lists_configured_types(self):
        registry = self._loaded_registry()
        with pytest.raises(LookupError, match="git"):
            registry.get("messaging")


# ---------------------------------------------------------------------------
# IntegrationRegistry — introspection
# ---------------------------------------------------------------------------


class TestRegistryIntrospection:
    def test_supports_configured_capability(self):
        registry = _make_registry()
        registry.load(
            IntegrationsConfig(
                git=ProviderConfig(provider="stub-git", settings={"token": "t"})
            )
        )
        assert registry.supports(ProviderCapability.CREATE_PULL_REQUEST)

    def test_supports_unconfigured_capability_is_false(self):
        registry = _make_registry()
        registry.load(IntegrationsConfig())
        assert not registry.supports(ProviderCapability.CREATE_PULL_REQUEST)

    def test_is_configured_true(self):
        registry = _make_registry()
        registry.load(
            IntegrationsConfig(
                git=ProviderConfig(provider="stub-git", settings={"token": "t"})
            )
        )
        assert registry.is_configured("git")

    def test_is_configured_false(self):
        registry = _make_registry()
        registry.load(IntegrationsConfig())
        assert not registry.is_configured("git")

    def test_configured_types_empty_after_empty_load(self):
        registry = _make_registry()
        registry.load(IntegrationsConfig())
        assert registry.configured_types() == []


# ---------------------------------------------------------------------------
# End-to-end: capability-based dispatch without adapter construction
# ---------------------------------------------------------------------------


class TestCapabilityBasedDispatch:
    def test_runtime_can_route_by_capability_not_type(self):
        """Demonstrate the pattern: runtime resolves capability, no isinstance needed."""
        registry = _make_registry()
        registry.load(
            IntegrationsConfig(
                git=ProviderConfig(provider="stub-git", settings={"token": "tok"}),
                ci=ProviderConfig(provider="stub-ci", settings={"token": "tok"}),
            )
        )

        # Runtime code: check, resolve, act — no provider-specific branching
        for cap in [ProviderCapability.CREATE_PULL_REQUEST, ProviderCapability.CLONE_REPOSITORY]:
            assert registry.supports(cap)
            provider = registry.resolve(cap)
            caps = provider.capabilities()
            assert caps.supports(cap)

    def test_swapping_provider_id_changes_resolved_instance(self):
        """Changing the provider in config swaps the instance without touching runtime code."""
        registry = IntegrationRegistry()

        class ProviderA:
            name = "A"

            def __init__(self, settings: dict[str, str]) -> None:
                pass

            def provider_info(self) -> ProviderInfo:
                return ProviderInfo(provider_id="a", display_name="A")

            def capabilities(self) -> CapabilitySet:
                return CapabilitySet(
                    operations=frozenset({ProviderCapability.FETCH_REPOSITORY})
                )

        class ProviderB:
            name = "B"

            def __init__(self, settings: dict[str, str]) -> None:
                pass

            def provider_info(self) -> ProviderInfo:
                return ProviderInfo(provider_id="b", display_name="B")

            def capabilities(self) -> CapabilitySet:
                return CapabilitySet(
                    operations=frozenset({ProviderCapability.FETCH_REPOSITORY})
                )

        registry.register_factory("provider-a", ProviderA)
        registry.register_factory("provider-b", ProviderB)

        registry.load(
            IntegrationsConfig(git=ProviderConfig(provider="provider-a", settings={}))
        )
        assert registry.resolve(ProviderCapability.FETCH_REPOSITORY).name == "A"

        # Reload with provider-b — same runtime resolution code, different instance
        registry.load(
            IntegrationsConfig(git=ProviderConfig(provider="provider-b", settings={}))
        )
        assert registry.resolve(ProviderCapability.FETCH_REPOSITORY).name == "B"
