"""Pydantic v2 input models for all MCP tools.

These models are the authoritative Python representation of the JSON Schema
input definitions in ``docs/api_contract.md``.  Each model is strict
(``extra="forbid"``) to catch unexpected parameters early.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SeparateStemsInput(BaseModel):
    """Input for the ``separate_stems`` tool."""

    model_config = {"extra": "forbid"}

    audio_url: str = Field(
        description=(
            "Publicly accessible HTTPS URL of the source audio file. "
            "Supported formats: mp3, wav, aac, flac, ogg, m4a."
        )
    )
    quality: Literal["preview", "hqPreview", "download"] = Field(
        default="hqPreview",
        description=(
            "Download quality for stem files: "
            "'preview' = medium MP3, "
            "'hqPreview' = high-quality MP3 (default), "
            "'download' = lossless WAV."
        ),
    )


class ExtractMidiInput(BaseModel):
    """Input for the ``extract_midi`` tool."""

    model_config = {"extra": "forbid"}

    audio_url: str = Field(
        description=(
            "Publicly accessible HTTPS URL of the source audio file. "
            "Supported formats: mp3, wav, aac, flac, ogg, m4a."
        )
    )


class AnalyzeMusicInput(BaseModel):
    """Input for the ``analyze_music`` tool."""

    model_config = {"extra": "forbid"}

    audio_url: str = Field(
        description=(
            "Publicly accessible HTTPS URL of the source audio file. "
            "Supported formats: mp3, wav, aac, flac, ogg, m4a."
        )
    )
