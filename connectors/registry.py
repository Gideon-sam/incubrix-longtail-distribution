"""
Connector registry — auto-discovers and loads connector packages.

Each connector is a Python package under connectors/ with:
  - manifest.yaml (parsed at load time)
  - connector.py  (subclass of BaseConnector)

Adding a new connector = one folder, one manifest, one class.
"""
from __future__ import annotations
import importlib
from pathlib import Path
from typing import Optional

import yaml

from connectors.base import BaseConnector
from api.middleware.logging_mw import get_logger

log = get_logger("connectors.registry")

# Global registry: connector_key → connector instance
_registry: dict[str, BaseConnector] = {}
# Manifest data: connector_key → parsed manifest dict
_manifests: dict[str, dict] = {}


def register(connector: BaseConnector):
    """Manually register a connector instance."""
    _registry[connector.key] = connector
    log.info("connector_registered", connector_key=connector.key)


def get_connector(key: str) -> Optional[BaseConnector]:
    """Look up a connector by key. Returns None if not found."""
    return _registry.get(key)


def get_manifest(key: str) -> Optional[dict]:
    """Look up a connector's manifest by key."""
    return _manifests.get(key)


def list_connectors() -> list[dict]:
    """Return summary info for all registered connectors."""
    result = []
    for key, connector in _registry.items():
        manifest = _manifests.get(key, {})
        result.append({
            "key": key,
            "version": manifest.get("version", "unknown"),
            "tier": manifest.get("tier", "unknown"),
            "auth": manifest.get("auth", "unknown"),
            "surfaces": manifest.get("surfaces", []),
            "capabilities": manifest.get("capabilities", []),
        })
    return result


def discover_connectors():
    """
    Auto-discover all connector packages under connectors/.

    Each subdirectory with a manifest.yaml and connector.py is loaded.
    The connector module must define a class that extends BaseConnector.
    """
    connectors_dir = Path(__file__).parent

    for entry in sorted(connectors_dir.iterdir()):
        # Skip non-directories and __pycache__
        if not entry.is_dir() or entry.name.startswith("_"):
            continue

        manifest_path = entry / "manifest.yaml"
        connector_module = entry / "connector.py"

        # Both files must exist
        if not manifest_path.exists() or not connector_module.exists():
            continue

        try:
            # Parse the YAML manifest
            with open(manifest_path, "r") as f:
                manifest = yaml.safe_load(f)

            key = manifest.get("key", entry.name)
            _manifests[key] = manifest

            # Import the connector module dynamically
            module_name = f"connectors.{entry.name}.connector"
            module = importlib.import_module(module_name)

            # Find the BaseConnector subclass in the module
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseConnector)
                    and attr is not BaseConnector
                ):
                    instance = attr()
                    _registry[key] = instance
                    log.info(
                        "connector_discovered",
                        connector_key=key,
                        tier=manifest.get("tier"),
                        version=manifest.get("version"),
                    )
                    break
            else:
                log.warning(
                    "connector_no_class_found",
                    directory=entry.name,
                )

        except Exception as exc:
            log.error(
                "connector_load_error",
                directory=entry.name,
                error=str(exc),
            )
