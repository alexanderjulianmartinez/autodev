"""Monitoring / observability system interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import Field

from autodev.core.schemas import AutoDevModel
from autodev.integrations.base import CapabilitySet, ProviderInfo

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class FetchAlertsRequest(AutoDevModel):
    """Fetch active or recent alerts."""

    namespace: str = ""
    severity: str = ""
    limit: int = 50


class QueryMetricsRequest(AutoDevModel):
    """Execute a metrics query (e.g. PromQL or a provider-specific expression)."""

    query: str
    namespace: str = ""
    start_time: str = ""
    end_time: str = ""
    step: str = ""


# ---------------------------------------------------------------------------
# Response / info models
# ---------------------------------------------------------------------------


class AlertInfo(AutoDevModel):
    """A single monitoring alert."""

    alert_id: str
    name: str
    severity: str
    status: str
    summary: str = ""
    runbook_url: str = ""
    labels: dict[str, str] = Field(default_factory=dict)
    started_at: str = ""


class MetricSeries(AutoDevModel):
    """One time series in a metrics query result."""

    labels: dict[str, str] = Field(default_factory=dict)
    values: list[tuple[float, float]] = Field(default_factory=list)


class MetricsResult(AutoDevModel):
    """Result of a metrics query."""

    query: str
    series: list[MetricSeries] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class MonitoringSystem(Protocol):
    """Structural interface for observability systems (Prometheus, Datadog, Grafana…)."""

    def provider_info(self) -> ProviderInfo: ...
    def capabilities(self) -> CapabilitySet: ...

    def fetch_alerts(self, request: FetchAlertsRequest) -> list[AlertInfo]: ...
    def query_metrics(self, request: QueryMetricsRequest) -> MetricsResult: ...
