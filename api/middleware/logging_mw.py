"""
Structured JSON logging — Integration Standard #8.

Every log line is a JSON object with: timestamp, level, message,
correlation_id (from request), and job_id (when applicable).
Uses structlog for clean, parseable output.
"""
import structlog
import logging
import sys

from api.config import settings


def setup_logging():
    """Configure structlog for JSON output. Call once at startup."""
    # Set root log level from config
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Configure structlog processors
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging to use structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )


def get_logger(name: str = __name__):
    """Get a structured logger instance."""
    return structlog.get_logger(name)
