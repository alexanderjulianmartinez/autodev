"""Messaging / notification system interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import Field

from autodev.core.schemas import AutoDevModel
from autodev.integrations.base import CapabilitySet, ProviderInfo

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class SendMessageRequest(AutoDevModel):
    """Send a message to a channel or recipient."""

    destination: str
    body: str
    subject: str = ""
    attachments: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class FetchMessagesRequest(AutoDevModel):
    """Retrieve recent messages from a channel or thread."""

    source: str
    limit: int = 50
    before: str = ""


# ---------------------------------------------------------------------------
# Response / info models
# ---------------------------------------------------------------------------


class MessageInfo(AutoDevModel):
    """A single message from a messaging system."""

    message_id: str
    author: str
    body: str
    destination: str
    sent_at: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)


class MessageResult(AutoDevModel):
    """Outcome of sending a message."""

    message_id: str
    destination: str
    delivered: bool
    metadata: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class MessagingSystem(Protocol):
    """Structural interface for messaging systems (Slack, Teams, PagerDuty…)."""

    def provider_info(self) -> ProviderInfo: ...
    def capabilities(self) -> CapabilitySet: ...

    def send_message(self, request: SendMessageRequest) -> MessageResult: ...
    def fetch_messages(self, request: FetchMessagesRequest) -> list[MessageInfo]: ...
