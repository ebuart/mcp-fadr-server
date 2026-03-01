"""MCP server initialisation and tool registration.

This module is the only place that knows about the MCP protocol.  It:
- Creates the :class:`~mcp.server.fastmcp.FastMCP` application instance.
- Registers exactly three tools (``separate_stems``, ``extract_midi``,
  ``analyze_music``) with descriptions and typed signatures so FastMCP
  auto-generates valid JSON Schema inputs.
- Delegates all business logic to the tools layer, which calls the service.

Architecture rule: no business logic here.  This layer only routes MCP
tool calls to the appropriate handler function and serialises the result.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP

from server.services.stem_service import StemService
from server.tools.analyze_music import handle_analyze_music
from server.tools.extract_midi import handle_extract_midi
from server.tools.separate_stems import handle_separate_stems

_AUDIO_URL_DESCRIPTION = (
    "Publicly accessible HTTPS URL of the source audio file. "
    "Supported formats: mp3, wav, aac, flac, ogg, m4a."
)


def create_mcp_app(service: StemService) -> FastMCP:
    """Build and return the configured FastMCP application.

    Args:
        service: Fully-wired :class:`~server.services.stem_service.StemService`
            instance to be shared across all tool handlers.

    Returns:
        A :class:`~mcp.server.fastmcp.FastMCP` ready to call
        :meth:`~mcp.server.fastmcp.FastMCP.run_stdio_async`.
    """
    mcp = FastMCP(
        "mcp-fadr-server",
        instructions=(
            "This server integrates the Fadr API to provide audio AI tools: "
            "stem separation, MIDI extraction, and musical analysis (key, tempo, chords). "
            "All tools accept a publicly accessible HTTPS audio URL and return structured JSON."
        ),
    )

    # -----------------------------------------------------------------------
    # Tool 1: separate_stems
    # -----------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Separate an audio track into individual stems (vocals, bass, drums, "
            "melodies, instrumental) using the Fadr AI. Returns presigned download "
            "URLs for each stem. Processing typically takes 2–4 minutes."
        ),
    )
    async def separate_stems(
        audio_url: Annotated[str, _AUDIO_URL_DESCRIPTION],
        quality: Annotated[
            Literal["preview", "hqPreview", "download"],
            "Download quality: 'preview'=medium MP3, 'hqPreview'=high-quality MP3 (default), 'download'=lossless WAV.",
        ] = "hqPreview",
    ) -> str:
        result = await handle_separate_stems(audio_url, quality, service)
        return json.dumps(result)

    # -----------------------------------------------------------------------
    # Tool 2: extract_midi
    # -----------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Extract MIDI files from an audio track using the Fadr AI. "
            "Returns MIDI files for each stem (vocals, bass, melodies) and the "
            "full chord progression as a separate MIDI file. Processing typically "
            "takes 25–45 seconds."
        ),
    )
    async def extract_midi(
        audio_url: Annotated[str, _AUDIO_URL_DESCRIPTION],
    ) -> str:
        result = await handle_extract_midi(audio_url, service)
        return json.dumps(result)

    # -----------------------------------------------------------------------
    # Tool 3: analyze_music
    # -----------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Analyse the musical characteristics of an audio track using the Fadr AI. "
            "Returns the detected key (e.g. 'A minor'), tempo in BPM, time signature, "
            "and chord progression. Processing typically takes 25–45 seconds."
        ),
    )
    async def analyze_music(
        audio_url: Annotated[str, _AUDIO_URL_DESCRIPTION],
    ) -> str:
        result = await handle_analyze_music(audio_url, service)
        return json.dumps(result)

    return mcp
