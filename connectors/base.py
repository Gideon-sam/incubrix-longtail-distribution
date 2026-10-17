"""
Abstract base connector — the contract every connector must follow.

Each connector implements these methods from Appendix A:
  validate, publish, get_status, delete, fetch_metrics (optional),
  refresh_auth (optional), build_assist_pack (assisted tier only).

Connectors are pure logic — they never write to IncuBrix's database.
Our runtime does that.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Optional

from api.schemas.connector import (
    Rendition,
    DestinationRef,
    Connection,
    ValidateResponse,
    PublishResponse,
    GetStatusResponse,
    DeleteResponse,
    FetchMetricsResponse,
    RefreshAuthResponse,
    BuildAssistPackResponse,
)

class HTTPException(Exception):
    """
    Standard HTTP exception for connectors.
    Carries status_code and detail dictionary matching the IncuBrix error spec.
    """
    def __init__(self, status_code: int, detail: Any = None):
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))

__all__ = ["BaseConnector", "HTTPException"]



class BaseConnector(ABC):
    """
    Abstract base for all connectors. Subclass and implement
    the required methods. Optional methods have default
    implementations that return sensible defaults.
    """

    @property
    @abstractmethod
    def key(self) -> str:
        """Unique connector key, e.g. 'discourse', 'lemmy'."""
        ...

    @property
    @abstractmethod
    def manifest_path(self) -> str:
        """Path to the connector's manifest.yaml file."""
        ...

    @abstractmethod
    async def validate(
        self,
        rendition: Rendition,
        destination: DestinationRef,
        connection: Connection,
    ) -> ValidateResponse:
        """Check content against destination's format limits."""
        ...

    @abstractmethod
    async def publish(
        self,
        rendition: Rendition,
        destination: DestinationRef,
        connection: Connection,
        idempotency_key: str,
    ) -> PublishResponse:
        """Publish content to the platform. Returns platform_post_id + live_url."""
        ...

    @abstractmethod
    async def get_status(
        self,
        platform_post_id: str,
        connection: Connection,
    ) -> GetStatusResponse:
        """Check if a published post is still live."""
        ...

    @abstractmethod
    async def delete(
        self,
        platform_post_id: str,
        connection: Connection,
    ) -> DeleteResponse:
        """Delete a published post (for certification cleanup)."""
        ...

    # ── Optional methods ────────────────────────────────────

    async def fetch_metrics(
        self,
        platform_post_id: str,
        connection: Connection,
        since: Optional[str] = None,
    ) -> FetchMetricsResponse:
        """Fetch engagement metrics. Optional — not all connectors support this."""
        return FetchMetricsResponse()

    async def refresh_auth(
        self,
        connection: Connection,
    ) -> RefreshAuthResponse:
        """Refresh an expired auth token. Optional."""
        return RefreshAuthResponse()

    async def build_assist_pack(
        self,
        rendition: Rendition,
        destination: DestinationRef,
    ) -> BuildAssistPackResponse:
        """Build a ready-to-post pack for non-automatable destinations. Assisted tier only."""
        return BuildAssistPackResponse()
