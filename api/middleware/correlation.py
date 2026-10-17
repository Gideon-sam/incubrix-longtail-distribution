"""
Correlation ID middleware — Integration Standard #8.

Reads X-Correlation-Id from the incoming request. If absent, generates
a new UUID. Attaches it to the request state and includes it in every
structured log entry and the response header.
"""
from __future__ import annotations
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Propagate or generate X-Correlation-Id on every request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Use the caller's correlation ID or create one
        correlation_id = request.headers.get(
            "X-Correlation-Id", str(uuid.uuid4())
        )
        # Store on request state so handlers and loggers can read it
        request.state.correlation_id = correlation_id

        response = await call_next(request)

        # Echo it back in the response
        response.headers["X-Correlation-Id"] = correlation_id
        return response
