"""
API dependencies package.
"""
from api.dependencies.idempotency import require_idempotency_key

__all__ = ["require_idempotency_key"]
