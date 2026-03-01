"""Structured JSON logger factory.

All log records are emitted as JSON objects.  Free-text ``%s``-style
interpolation is intentionally avoided to prevent accidental inclusion of
secrets in log output.

Usage::

    from server.utils.logging import get_logger

    logger = get_logger(__name__)
    logger.info("Stem task completed", extra={"job_id": task_id, "processing_time_ms": 420})
"""

from __future__ import annotations

import json
import logging
from typing import Any


class _JsonFormatter(logging.Formatter):
    """Formats every log record as a single-line JSON object."""

    _SKIP_KEYS: frozenset[str] = frozenset(
        {
            "args",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "message",
            "module",
            "msecs",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
            "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key not in self._SKIP_KEYS:
                data[key] = value

        return json.dumps(data, default=str)


def get_logger(name: str) -> logging.Logger:
    """Return a logger that writes structured JSON to stderr."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    return logger
