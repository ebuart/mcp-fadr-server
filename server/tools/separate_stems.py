"""Tool handler for ``separate_stems``.

Responsibility:
- Validate input parameters against :class:`SeparateStemsInput`.
- Call :meth:`StemService.separate_stems`.
- Return a structured response envelope (success or error).

No business logic, no HTTP calls.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from server.exceptions import FadrServerError
from server.schemas.envelope import make_error, make_success
from server.schemas.inputs import SeparateStemsInput
from server.services.stem_service import StemService
from server.utils.logging import get_logger

_logger = get_logger(__name__)


async def handle_separate_stems(
    audio_url: str,
    quality: str,
    service: StemService,
) -> dict[str, Any]:
    """Validate inputs, call the service, and wrap the result in an envelope.

    Args:
        audio_url: Raw ``audio_url`` string from the MCP call arguments.
        quality: Raw ``quality`` string from the MCP call arguments.
        service: Injected :class:`~server.services.stem_service.StemService`.

    Returns:
        A serialised :func:`~server.schemas.envelope.make_success` or
        :func:`~server.schemas.envelope.make_error` dict.
    """
    # --- Input validation -------------------------------------------------
    try:
        inp = SeparateStemsInput(audio_url=audio_url, quality=quality)  # type: ignore[arg-type]
    except ValidationError as exc:
        return make_error(
            "INVALID_INPUT",
            "Input validation failed.",
            {"errors": exc.errors(include_url=False)},
        )

    # --- Service call ------------------------------------------------------
    try:
        result = await service.separate_stems(inp.audio_url, inp.quality)
        return make_success(result.model_dump())

    except FadrServerError as exc:
        _logger.warning(
            "separate_stems tool error.",
            extra={"error_code": exc.error_code},
        )
        return make_error(exc.error_code, exc.message, exc.details)

    except Exception:
        _logger.exception("Unexpected error in separate_stems tool.")
        return make_error("INTERNAL_ERROR", "An unexpected error occurred.")
