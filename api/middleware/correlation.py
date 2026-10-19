"""
Correlation ID middleware — Integration Standard #8.

Reads X-Correlation-Id from the incoming request. If absent, generates
a new UUID. Binds it to structlog contextvars so every structured log entry
includes it automatically, and echoes it in response headers.
"""
from __future__ import annotations
import uuid
import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Propagate or generate X-Correlation-Id on every request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        correlation_id = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
        request.state.correlation_id = correlation_id

        # Bind to structlog contextvars
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        response = await call_next(request)
        response.headers["X-Correlation-Id"] = correlation_id
        return response
