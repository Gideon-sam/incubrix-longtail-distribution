"""Connectors package — extensible long-tail destination network."""
from connectors.base import BaseConnector
from connectors.registry import (
    register,
    get_connector,
    list_connectors,
    get_manifest,
    discover_connectors,
)

__all__ = [
    "BaseConnector",
    "register",
    "get_connector",
    "list_connectors",
    "get_manifest",
    "discover_connectors",
]
