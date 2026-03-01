"""Pydantic v2 output models for all MCP tools.

These are the normalised, schema-validated result types returned by the
service layer.  The tools layer serialises them into the standard response
envelope via ``model.model_dump()``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Tool 1: separate_stems
# ---------------------------------------------------------------------------


class StemFile(BaseModel):
    """A single separated audio stem."""

    model_config = {"extra": "forbid"}

    name: str = Field(description="Stem label, e.g. 'vocals', 'bass', 'drums'.")
    url: str = Field(description="Presigned download URL for this stem.")


class StemsResult(BaseModel):
    """Output data for the ``separate_stems`` tool."""

    model_config = {"extra": "forbid"}

    job_id: str = Field(description="Fadr task _id for auditability.")
    processing_time_ms: int | None = Field(
        default=None,
        description="Wall-clock time from task submission to completion (ms).",
    )
    stems: list[StemFile] = Field(
        min_length=1,
        description="Separated stem files.",
    )


# ---------------------------------------------------------------------------
# Tool 2: extract_midi
# ---------------------------------------------------------------------------


class MidiFile(BaseModel):
    """A single MIDI output file."""

    model_config = {"extra": "forbid"}

    name: str = Field(description="MIDI track label, e.g. 'vocals', 'chord_progression'.")
    url: str = Field(description="Presigned download URL for this MIDI file.")


class MidiResult(BaseModel):
    """Output data for the ``extract_midi`` tool."""

    model_config = {"extra": "forbid"}

    job_id: str
    processing_time_ms: int | None = None
    midi_files: list[MidiFile] = Field(min_length=1)
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Tool 3: analyze_music
# ---------------------------------------------------------------------------


class ChordEntry(BaseModel):
    """A single chord in the detected progression."""

    model_config = {"extra": "forbid"}

    chord: str = Field(description="Chord symbol, e.g. 'Am', 'Fmaj7'.")
    start_beat: float | None = Field(
        default=None,
        description="Beat position where this chord begins (if provided by Fadr).",
    )
    duration_beats: float | None = Field(
        default=None,
        description="Duration in beats (if provided by Fadr).",
    )


class AnalysisResult(BaseModel):
    """Output data for the ``analyze_music`` tool."""

    model_config = {"extra": "forbid"}

    job_id: str
    processing_time_ms: int | None = None
    key: str = Field(description="Detected musical key, e.g. 'C major', 'A minor'.")
    tempo_bpm: float = Field(ge=20, le=300, description="Tempo in beats per minute.")
    time_signature: str | None = Field(
        default=None,
        description="Time signature if available, e.g. '4/4'.",
    )
    chord_progression: list[ChordEntry] = Field(
        description="Ordered list of detected chords.",
    )
