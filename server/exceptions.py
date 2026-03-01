"""Typed exceptions for the MCP Fadr server.

All exceptions carry an ``error_code`` string that maps directly to the
``error.code`` field in the standard response envelope.  They are raised by
clients and services, and caught by the tools layer which converts them into
structured error envelopes.
"""

from __future__ import annotations


class FadrServerError(Exception):
    """Base class for all typed server exceptions."""

    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class UrlValidationError(FadrServerError):
    """Raised when ``audio_url`` fails scheme, SSRF, or extension validation."""

    error_code = "INVALID_URL"


class AudioDownloadError(FadrServerError):
    """Raised when downloading the source audio from ``audio_url`` fails."""

    error_code = "UPLOAD_FAILED"


class FadrApiError(FadrServerError):
    """Raised when the Fadr HTTP client receives an unexpected API error."""

    error_code = "DOWNSTREAM_ERROR"

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.status_code = status_code


class TaskFailedError(FadrServerError):
    """Raised when the Fadr async task ends with a ``failed`` status."""

    error_code = "TASK_FAILED"

    def __init__(self, task_id: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(f"Fadr task '{task_id}' failed.", details=details)
        self.task_id = task_id


class TaskTimeoutError(FadrServerError):
    """Raised when polling exceeds the configured timeout."""

    error_code = "TASK_TIMEOUT"

    def __init__(self, task_id: str, timeout_s: float) -> None:
        super().__init__(
            f"Fadr task '{task_id}' did not complete within {timeout_s}s.",
            details={"task_id": task_id, "timeout_s": timeout_s},
        )
        self.task_id = task_id
        self.timeout_s = timeout_s
