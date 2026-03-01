"""Tool handler for ``analyze_music``."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from server.exceptions import FadrServerError
from server.schemas.envelope import make_error, make_success
from server.schemas.inputs import AnalyzeMusicInput
from server.services.stem_service import StemService
from server.utils.logging import get_logger

_logger = get_logger(__name__)


async def handle_analyze_music(
    audio_url: str,
    service: StemService,
) -> dict[str, Any]:
    """Validate inputs, call the service, and wrap the result in an envelope."""
    try:
        inp = AnalyzeMusicInput(audio_url=audio_url)
    except ValidationError as exc:
        return make_error(
            "INVALID_INPUT",
            "Input validation failed.",
            {"errors": exc.errors(include_url=False)},
        )

    try:
        result = await service.analyze_music(inp.audio_url)
        return make_success(result.model_dump())

    except FadrServerError as exc:
        _logger.warning(
            "analyze_music tool error.",
            extra={"error_code": exc.error_code},
        )
        return make_error(exc.error_code, exc.message, exc.details)

    except Exception:
        _logger.exception("Unexpected error in analyze_music tool.")
        return make_error("INTERNAL_ERROR", "An unexpected error occurred.")
