"""Routers package."""
from api.routers import (
    health,
    jobs,
    connector_runtime,
    publish,
    destinations,
    certify,
    catalogue,
    recommend,
)

__all__ = [
    "health",
    "jobs",
    "connector_runtime",
    "publish",
    "destinations",
    "certify",
    "catalogue",
    "recommend",
]
