"""
Connector contract router — Must-Have #1.

Exposes ALL connector methods over HTTP at:
  POST /connector/v1/{connector_key}/{method}

This is the IncuBrix Connector Runtime interface. Every connector
must implement these methods so the runtime can call them.
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from connectors.registry import get_connector
from api.schemas.connector import (
    ValidateRequest, ValidateResponse,
    PublishRequest, PublishResponse,
    GetStatusRequest, GetStatusResponse,
    DeleteRequest, DeleteResponse,
    FetchMetricsRequest, FetchMetricsResponse,
    RefreshAuthRequest, RefreshAuthResponse,
    BuildAssistPackRequest, BuildAssistPackResponse,
)
from api.schemas.error import make_error
from api.middleware.logging_mw import get_logger

log = get_logger("routers.connector_runtime")

router = APIRouter(prefix="/connector/v1", tags=["Connector Contract"])


def _get_or_404(connector_key: str):
    """Get a connector by key or raise 404 with a clear error."""
    connector = get_connector(connector_key)
    if not connector:
        raise HTTPException(
            status_code=404,
            detail=make_error(
                "CONNECTOR_DISABLED",
                f"Connector '{connector_key}' is not registered. "
                "Is the connector package loaded?",
                retryable=False,
            ),
        )
    return connector


@router.post("/{connector_key}/validate", response_model=ValidateResponse)
async def validate(connector_key: str, body: ValidateRequest):
    """Check content against destination format limits before publishing."""
    connector = _get_or_404(connector_key)
    try:
        return await connector.validate(
            body.rendition, body.destination, body.connection
        )
    except Exception as exc:
        log.error("validate_error", connector=connector_key, error=str(exc))
        raise HTTPException(status_code=500, detail=make_error(
            "PLATFORM_UNAVAILABLE", str(exc), retryable=True
        ))


@router.post("/{connector_key}/publish", response_model=PublishResponse)
async def publish(connector_key: str, body: PublishRequest):
    """Publish content to the platform. Returns platform_post_id + live_url."""
    connector = _get_or_404(connector_key)
    try:
        return await connector.publish(
            body.rendition, body.destination, body.connection, body.idempotency_key
        )
    except Exception as exc:
        log.error("publish_error", connector=connector_key, error=str(exc))
        raise HTTPException(status_code=500, detail=make_error(
            "PLATFORM_UNAVAILABLE", str(exc), retryable=True
        ))


@router.post("/{connector_key}/get_status", response_model=GetStatusResponse)
async def get_status(connector_key: str, body: GetStatusRequest):
    """Check if a published post is still live."""
    connector = _get_or_404(connector_key)
    try:
        return await connector.get_status(body.platform_post_id, body.connection)
    except Exception as exc:
        log.error("get_status_error", connector=connector_key, error=str(exc))
        raise HTTPException(status_code=500, detail=make_error(
            "PLATFORM_UNAVAILABLE", str(exc), retryable=True
        ))


@router.post("/{connector_key}/delete", response_model=DeleteResponse)
async def delete(connector_key: str, body: DeleteRequest):
    """Delete a published post (used during certification cleanup)."""
    connector = _get_or_404(connector_key)
    try:
        return await connector.delete(body.platform_post_id, body.connection)
    except Exception as exc:
        log.error("delete_error", connector=connector_key, error=str(exc))
        raise HTTPException(status_code=500, detail=make_error(
            "PLATFORM_UNAVAILABLE", str(exc), retryable=True
        ))


@router.post("/{connector_key}/fetch_metrics", response_model=FetchMetricsResponse)
async def fetch_metrics(connector_key: str, body: FetchMetricsRequest):
    """Fetch engagement metrics (optional — not all connectors support this)."""
    connector = _get_or_404(connector_key)
    try:
        return await connector.fetch_metrics(
            body.platform_post_id, body.connection, body.since
        )
    except Exception as exc:
        log.error("fetch_metrics_error", connector=connector_key, error=str(exc))
        raise HTTPException(status_code=500, detail=make_error(
            "PLATFORM_UNAVAILABLE", str(exc), retryable=True
        ))


@router.post("/{connector_key}/refresh_auth", response_model=RefreshAuthResponse)
async def refresh_auth(connector_key: str, body: RefreshAuthRequest):
    """Refresh an expired auth token (optional)."""
    connector = _get_or_404(connector_key)
    try:
        return await connector.refresh_auth(body.connection)
    except Exception as exc:
        log.error("refresh_auth_error", connector=connector_key, error=str(exc))
        raise HTTPException(status_code=500, detail=make_error(
            "CONNECTION_AUTH_EXPIRED", str(exc), retryable=False
        ))


@router.post("/{connector_key}/build_assist_pack", response_model=BuildAssistPackResponse)
async def build_assist_pack(connector_key: str, body: BuildAssistPackRequest):
    """Build a ready-to-post pack for non-automatable destinations (assisted tier)."""
    connector = _get_or_404(connector_key)
    try:
        return await connector.build_assist_pack(body.rendition, body.destination)
    except Exception as exc:
        log.error("build_assist_pack_error", connector=connector_key, error=str(exc))
        raise HTTPException(status_code=500, detail=make_error(
            "PLATFORM_UNAVAILABLE", str(exc), retryable=True
        ))
