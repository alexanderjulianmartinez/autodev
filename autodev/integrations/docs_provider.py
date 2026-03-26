"""Documentation provider interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import Field

from autodev.core.schemas import AutoDevModel
from autodev.integrations.base import CapabilitySet, ProviderInfo


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class FetchDocumentRequest(AutoDevModel):
    """Fetch a document by ID or path."""

    document_id: str
    space_id: str = ""


class UpdateDocumentRequest(AutoDevModel):
    """Create or update a document."""

    document_id: str
    body: str
    space_id: str = ""
    title: str = ""
    content_type: str = "markdown"


class SearchDocumentsRequest(AutoDevModel):
    """Full-text search within a documentation space."""

    query: str
    space_id: str = ""
    limit: int = 20


# ---------------------------------------------------------------------------
# Response / info models
# ---------------------------------------------------------------------------


class DocumentInfo(AutoDevModel):
    """A single document from a documentation provider."""

    document_id: str
    title: str
    body: str = ""
    space_id: str = ""
    content_type: str = "markdown"
    url: str = ""
    last_modified: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)


class DocumentSearchResult(AutoDevModel):
    """One hit in a document search."""

    document_id: str
    title: str
    excerpt: str = ""
    url: str = ""
    score: float = 0.0


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class DocsProvider(Protocol):
    """Structural interface for documentation systems (Confluence, Notion, Read the Docs…)."""

    def provider_info(self) -> ProviderInfo: ...
    def capabilities(self) -> CapabilitySet: ...

    def fetch_document(self, request: FetchDocumentRequest) -> DocumentInfo: ...
    def update_document(self, request: UpdateDocumentRequest) -> DocumentInfo: ...
    def search_documents(self, request: SearchDocumentsRequest) -> list[DocumentSearchResult]: ...
