"""Standard response envelope shared by all MCP tools.

Every tool returns either a :class:`SuccessResponse` or builds an
:class:`ErrorDetail` and returns a :class:`ErrorResponse`.  The two types are
unified under :class:`ToolResponse` (a union alias) for type-checker
compatibility.

Wire format (success)::

    {"success": true, "data": {...}, "error": null}

Wire format (failure)::

    {"success": false, "data": null, "error": {"code": "...", "message": "...", "details": null}}
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator


class ErrorDetail(BaseModel):
    """Structured error object embedded in a failed response."""

    code: str
    message: str
    details: dict[str, Any] | None = None

    model_config = {"extra": "forbid"}


class SuccessResponse(BaseModel):
    """Response envelope returned on successful tool execution."""

    success: bool = True
    data: dict[str, Any]
    error: None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _success_must_be_true(self) -> "SuccessResponse":
        if not self.success:
            raise ValueError("SuccessResponse.success must be True")
        return self


class ErrorResponse(BaseModel):
    """Response envelope returned when a tool fails."""

    success: bool = False
    data: None = None
    error: ErrorDetail

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _success_must_be_false(self) -> "ErrorResponse":
        if self.success:
            raise ValueError("ErrorResponse.success must be False")
        return self


def make_success(data: dict[str, Any]) -> dict[str, Any]:
    """Return a serialised success envelope."""
    return SuccessResponse(data=data).model_dump()


def make_error(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a serialised error envelope."""
    return ErrorResponse(error=ErrorDetail(code=code, message=message, details=details)).model_dump()
