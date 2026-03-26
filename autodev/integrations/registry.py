"""IntegrationRegistry: config-driven provider loading and capability resolution.

Providers are registered as factories; the registry instantiates them from
``IntegrationsConfig`` and resolves them at runtime by capability.

Typical usage::

    # 1. At startup — register factories (one per supported provider ID)
    registry = IntegrationRegistry()
    registry.register_factory("github", build_github_provider, requires={"token"})
    registry.register_factory("slack",  build_slack_provider,  requires={"token"})

    # 2. Load from config (fails early if any provider_id is unknown
    #    or required settings are missing)
    registry.load(IntegrationsConfig.discover())

    # 3. At call sites — resolve by capability, no adapter construction needed
    git = registry.resolve(ProviderCapability.CREATE_PULL_REQUEST)
    git.create_pull_request(request)

    # Or resolve by integration type name
    ci = registry.get("ci")
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from autodev.core.config import ConfigError
from autodev.integrations.base import ProviderCapability
from autodev.integrations.config import IntegrationsConfig, ProviderConfig

logger = logging.getLogger(__name__)

# Maps integration-type slot → capabilities it owns.
# Runtime code uses this to route ``resolve(capability)`` to the right slot.
_INTEGRATION_TYPE_CAPABILITIES: dict[str, frozenset[ProviderCapability]] = {
    "git": frozenset(
        {
            ProviderCapability.FETCH_REPOSITORY,
            ProviderCapability.CREATE_BRANCH,
            ProviderCapability.CREATE_PULL_REQUEST,
            ProviderCapability.GET_DIFF,
            ProviderCapability.CLONE_REPOSITORY,
        }
    ),
    "issue_tracker": frozenset(
        {
            ProviderCapability.FETCH_ISSUE,
            ProviderCapability.CREATE_ISSUE,
            ProviderCapability.UPDATE_ISSUE,
            ProviderCapability.LIST_ISSUES,
        }
    ),
    "ci": frozenset(
        {
            ProviderCapability.FETCH_RUN,
            ProviderCapability.TRIGGER_RUN,
            ProviderCapability.LIST_RUNS,
        }
    ),
    "monitoring": frozenset(
        {
            ProviderCapability.FETCH_ALERTS,
            ProviderCapability.QUERY_METRICS,
        }
    ),
    "messaging": frozenset(
        {
            ProviderCapability.SEND_MESSAGE,
            ProviderCapability.FETCH_MESSAGES,
        }
    ),
    "docs": frozenset(
        {
            ProviderCapability.FETCH_DOCUMENT,
            ProviderCapability.UPDATE_DOCUMENT,
            ProviderCapability.SEARCH_DOCUMENTS,
        }
    ),
}

# Reverse index: capability → integration type
_CAPABILITY_TO_INTEGRATION_TYPE: dict[ProviderCapability, str] = {
    cap: itype
    for itype, caps in _INTEGRATION_TYPE_CAPABILITIES.items()
    for cap in caps
}

#: Callable signature for provider factories.
ProviderFactory = Callable[[dict[str, str]], Any]


class _FactoryEntry:
    __slots__ = ("factory", "requires")

    def __init__(self, factory: ProviderFactory, requires: frozenset[str]) -> None:
        self.factory = factory
        self.requires = requires


class IntegrationRegistry:
    """Loads and exposes integration providers from :class:`IntegrationsConfig`.

    The registry separates three concerns:

    - **Registration** — factories are declared up-front with their required
      settings, so the registry can validate config before any network calls.
    - **Loading** — ``load(config)`` instantiates providers, validates that
      all required settings are present, and fails fast with actionable errors.
    - **Resolution** — ``resolve(capability)`` and ``get(type)`` give runtime
      code access to providers without constructing adapters at the call site.
    """

    def __init__(self) -> None:
        self._factories: dict[str, _FactoryEntry] = {}
        self._providers: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_factory(
        self,
        provider_id: str,
        factory: ProviderFactory,
        *,
        requires: set[str] | frozenset[str] | None = None,
    ) -> None:
        """Register a provider factory.

        Args:
            provider_id: Identifier used in ``IntegrationsConfig.*.provider``
                (e.g. ``"github"``, ``"linear"``, ``"slack"``).
            factory: ``(settings: dict[str, str]) -> provider`` — called during
                :meth:`load` to construct the provider instance.
            requires: Setting keys that *must* be present in the provider's
                ``settings`` block.  Missing keys cause :meth:`load` to raise
                :class:`~autodev.core.config.ConfigError` with an actionable
                message before the factory is called.
        """
        self._factories[provider_id] = _FactoryEntry(
            factory=factory,
            requires=frozenset(requires or []),
        )
        logger.debug("Registered integration factory: %s", provider_id)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self, config: IntegrationsConfig) -> None:
        """Instantiate providers from ``config``.

        Iterates over every integration type.  For each configured slot:

        1. Checks that the ``provider`` ID is registered — fails with
           ``ConfigError`` naming the unknown ID and listing known ones.
        2. Checks that all ``requires`` settings are present — fails with
           ``ConfigError`` naming the missing keys.
        3. Calls the factory; wraps any exception in ``ConfigError``.

        Args:
            config: Parsed :class:`IntegrationsConfig`.

        Raises:
            ConfigError: on the first validation or initialization failure.
        """
        self._providers = {}
        for itype in ("git", "issue_tracker", "ci", "monitoring", "messaging", "docs"):
            slot: ProviderConfig | None = getattr(config, itype)
            if slot is None:
                continue
            self._providers[itype] = self._instantiate(itype, slot)
            logger.debug(
                "Loaded '%s' integration: provider=%s", itype, slot.provider
            )

    def _instantiate(self, itype: str, cfg: ProviderConfig) -> Any:
        pid = cfg.provider
        if pid not in self._factories:
            known = sorted(self._factories) or ["(none registered)"]
            raise ConfigError(
                f"Integration '{itype}': unknown provider '{pid}'. "
                f"Registered providers: {known}"
            )
        entry = self._factories[pid]
        missing = entry.requires - cfg.settings.keys()
        if missing:
            raise ConfigError(
                f"Integration '{itype}' provider '{pid}' is missing required "
                f"settings: {sorted(missing)}"
            )
        try:
            return entry.factory(cfg.settings)
        except ConfigError:
            raise
        except Exception as exc:
            raise ConfigError(
                f"Integration '{itype}' provider '{pid}' failed to initialize: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(self, capability: ProviderCapability) -> Any:
        """Return the provider instance that owns ``capability``.

        The returned object satisfies the Protocol for its integration type
        (e.g. :class:`~autodev.integrations.GitProvider` for any git capability).

        Args:
            capability: The :class:`~autodev.integrations.ProviderCapability`
                needed at the call site.

        Raises:
            LookupError: if no provider is configured for the integration type
                that owns ``capability``.
        """
        itype = _CAPABILITY_TO_INTEGRATION_TYPE.get(capability)
        if itype is None:
            # Should not happen unless ProviderCapability gains new members
            # without a corresponding entry in _INTEGRATION_TYPE_CAPABILITIES.
            raise LookupError(
                f"No integration type is mapped to capability '{capability.value}'"
            )
        return self.get(itype)

    def get(self, integration_type: str) -> Any:
        """Return the provider instance for an integration type by slot name.

        Args:
            integration_type: One of ``"git"``, ``"issue_tracker"``, ``"ci"``,
                ``"monitoring"``, ``"messaging"``, ``"docs"``.

        Raises:
            LookupError: if no provider is configured for ``integration_type``.
        """
        if integration_type not in self._providers:
            configured = sorted(self._providers) or ["(none)"]
            raise LookupError(
                f"No provider configured for integration type '{integration_type}'. "
                f"Configured types: {configured}"
            )
        return self._providers[integration_type]

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def is_configured(self, integration_type: str) -> bool:
        """Return ``True`` if a provider for ``integration_type`` is loaded."""
        return integration_type in self._providers

    def configured_types(self) -> list[str]:
        """Return sorted list of integration types that have a loaded provider."""
        return sorted(self._providers)

    def supports(self, capability: ProviderCapability) -> bool:
        """Return ``True`` if a provider supporting ``capability`` is loaded."""
        itype = _CAPABILITY_TO_INTEGRATION_TYPE.get(capability)
        return itype is not None and itype in self._providers

    def registered_provider_ids(self) -> list[str]:
        """Return sorted list of registered factory provider IDs."""
        return sorted(self._factories)
