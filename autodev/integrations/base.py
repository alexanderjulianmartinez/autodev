"""Base types for AutoDev integration providers.

All integration providers share a common capability-discovery contract:
``provider.capabilities()`` returns a ``CapabilitySet`` that runtime code
can query instead of branching on provider type.

    caps = provider.capabilities()
    if caps.supports(ProviderCapability.CREATE_PULL_REQUEST):
        pr = provider.create_pull_request(request)
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable

from pydantic import Field

from autodev.core.schemas import AutoDevModel


class ProviderCapability(str, Enum):
    """All operations that any integration provider may support."""

    # Git provider
    FETCH_REPOSITORY = "fetch_repository"
    CREATE_BRANCH = "create_branch"
    CREATE_PULL_REQUEST = "create_pull_request"
    GET_DIFF = "get_diff"
    CLONE_REPOSITORY = "clone_repository"
    # Issue tracker
    FETCH_ISSUE = "fetch_issue"
    CREATE_ISSUE = "create_issue"
    UPDATE_ISSUE = "update_issue"
    LIST_ISSUES = "list_issues"
    # CI system
    FETCH_RUN = "fetch_run"
    TRIGGER_RUN = "trigger_run"
    LIST_RUNS = "list_runs"
    # Monitoring
    FETCH_ALERTS = "fetch_alerts"
    QUERY_METRICS = "query_metrics"
    # Messaging
    SEND_MESSAGE = "send_message"
    FETCH_MESSAGES = "fetch_messages"
    # Documentation
    FETCH_DOCUMENT = "fetch_document"
    UPDATE_DOCUMENT = "update_document"
    SEARCH_DOCUMENTS = "search_documents"


class CapabilitySet(AutoDevModel):
    """Immutable record of operations a provider supports.

    Runtime code uses ``capabilities.supports(op)`` instead of
    ``isinstance(provider, GitHubProvider)`` to avoid provider-specific
    branching.
    """

    operations: frozenset[ProviderCapability] = Field(default_factory=frozenset)
    metadata: dict[str, str] = Field(default_factory=dict)

    def supports(self, operation: ProviderCapability) -> bool:
        """Return True if the provider supports ``operation``."""
        return operation in self.operations

    def require(self, operation: ProviderCapability) -> None:
        """Raise ``NotImplementedError`` if ``operation`` is not supported."""
        if not self.supports(operation):
            raise NotImplementedError(
                f"Provider does not support '{operation.value}'. "
                f"Supported: {sorted(op.value for op in self.operations)}"
            )


class ProviderInfo(AutoDevModel):
    """Static metadata about a provider instance."""

    provider_id: str
    display_name: str
    version: str = ""
    base_url: str = ""
    capabilities: CapabilitySet = Field(default_factory=CapabilitySet)


@runtime_checkable
class IntegrationProvider(Protocol):
    """Structural base interface shared by all integration providers.

    Every concrete provider must implement these two methods so that runtime
    code can discover what the provider supports without importing
    provider-specific types.
    """

    def provider_info(self) -> ProviderInfo:
        """Return static metadata about this provider."""
        ...

    def capabilities(self) -> CapabilitySet:
        """Return the set of operations this provider supports."""
        ...
