"""Integration provider interfaces for AutoDev.

Each integration type exposes a small ``typing.Protocol`` interface plus
typed request/response models.  Runtime code dispatches through
``CapabilitySet`` rather than branching on provider type:

    caps = provider.capabilities()
    if caps.supports(ProviderCapability.CREATE_PULL_REQUEST):
        pr = provider.create_pull_request(request)
"""

from __future__ import annotations

from autodev.integrations.base import (
    CapabilitySet,
    IntegrationProvider,
    ProviderCapability,
    ProviderInfo,
)
from autodev.integrations.config import IntegrationsConfig, ProviderConfig
from autodev.integrations.models import EntityRef, ErrorEvent
from autodev.integrations.registry import IntegrationRegistry, ProviderFactory
from autodev.integrations.ci_system import (
    CIJobInfo,
    CIRunInfo,
    CIStepInfo,
    CISystem,
    FetchRunRequest,
    ListRunsRequest,
    TriggerRunRequest,
)
from autodev.integrations.docs_provider import (
    DocumentInfo,
    DocumentSearchResult,
    DocsProvider,
    FetchDocumentRequest,
    SearchDocumentsRequest,
    UpdateDocumentRequest,
)
from autodev.integrations.git_provider import (
    BranchInfo,
    CloneRepositoryRequest,
    CloneResult,
    CreateBranchRequest,
    CreatePullRequestRequest,
    DiffResult,
    FetchRepositoryRequest,
    GetDiffRequest,
    GitProvider,
    PullRequestInfo,
    RepositoryInfo,
)
from autodev.integrations.issue_tracker import (
    CreateIssueRequest,
    FetchIssueRequest,
    IssueComment,
    IssueInfo,
    IssueTracker,
    ListIssuesRequest,
    UpdateIssueRequest,
)
from autodev.integrations.messaging import (
    FetchMessagesRequest,
    MessageInfo,
    MessageResult,
    MessagingSystem,
    SendMessageRequest,
)
from autodev.integrations.monitoring import (
    AlertInfo,
    FetchAlertsRequest,
    MetricSeries,
    MetricsResult,
    MonitoringSystem,
    QueryMetricsRequest,
)

__all__ = [
    # config + registry
    "IntegrationRegistry",
    "IntegrationsConfig",
    "ProviderConfig",
    "ProviderFactory",
    # shared domain models
    "EntityRef",
    "ErrorEvent",
    # base
    "CapabilitySet",
    "IntegrationProvider",
    "ProviderCapability",
    "ProviderInfo",
    # git
    "BranchInfo",
    "CloneRepositoryRequest",
    "CloneResult",
    "CreateBranchRequest",
    "CreatePullRequestRequest",
    "DiffResult",
    "FetchRepositoryRequest",
    "GetDiffRequest",
    "GitProvider",
    "PullRequestInfo",
    "RepositoryInfo",
    # issue tracker
    "CreateIssueRequest",
    "FetchIssueRequest",
    "IssueComment",
    "IssueInfo",
    "IssueTracker",
    "ListIssuesRequest",
    "UpdateIssueRequest",
    # CI
    "CIJobInfo",
    "CIRunInfo",
    "CIStepInfo",
    "CISystem",
    "FetchRunRequest",
    "ListRunsRequest",
    "TriggerRunRequest",
    # monitoring
    "AlertInfo",
    "FetchAlertsRequest",
    "MetricSeries",
    "MetricsResult",
    "MonitoringSystem",
    "QueryMetricsRequest",
    # messaging
    "FetchMessagesRequest",
    "MessageInfo",
    "MessageResult",
    "MessagingSystem",
    "SendMessageRequest",
    # docs
    "DocumentInfo",
    "DocumentSearchResult",
    "DocsProvider",
    "FetchDocumentRequest",
    "SearchDocumentsRequest",
    "UpdateDocumentRequest",
]
