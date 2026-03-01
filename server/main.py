"""MCP Fadr Server — entrypoint.

Wires together all layers and runs the MCP server over stdio:

    Transport (FastMCP)
        └─> Tools (validate + envelope)
            └─> StemService (orchestration)
                ├─> FadrHttpClient (Fadr API calls)
                ├─> HttpxAudioFetcher (audio URL download)
                └─> UrlValidator (SSRF prevention)
"""

from __future__ import annotations

import asyncio
import logging
import sys


def main() -> None:
    """Launch the MCP Fadr server (stdio transport)."""
    # Deferred imports keep startup fast and make circular-import errors easier to diagnose
    from server.clients.fadr_client import FadrHttpClient
    from server.clients.http_audio_fetcher import HttpxAudioFetcher
    from server.services.stem_service import StemService
    from server.transport.mcp_server import create_mcp_app
    from server.utils.config import get_settings
    from server.utils.logging import get_logger
    from server.utils.url_validator import UrlValidator

    settings = get_settings()

    # Configure root log level from settings
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    logger = get_logger(__name__)
    logger.info("Starting MCP Fadr server.", extra={"version": "0.1.0"})

    # Wire up dependencies
    fadr_client = FadrHttpClient(settings)
    audio_fetcher = HttpxAudioFetcher(timeout_s=settings.fadr_timeout_s)
    url_validator = UrlValidator(allowed_schemes=settings.allowed_schemes_set)

    service = StemService(
        fadr_client=fadr_client,
        audio_fetcher=audio_fetcher,
        url_validator=url_validator,
        config=settings,
    )

    mcp = create_mcp_app(service)

    try:
        asyncio.run(mcp.run_stdio_async())
    except KeyboardInterrupt:
        logger.info("MCP Fadr server shutting down.")
        sys.exit(0)


if __name__ == "__main__":
    main()
