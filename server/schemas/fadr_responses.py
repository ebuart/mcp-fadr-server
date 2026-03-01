"""Pydantic v2 models for raw Fadr API responses.

These models are used exclusively by the client layer to parse and validate
responses from ``api.fadr.com``.  They are deliberately lenient (``extra="allow"``)
because the Fadr API may include fields not covered by public docs.

Fadr uses MongoDB-style ``_id`` fields.  We alias them to ``asset_id`` /
``task_id`` in Python code via ``Field(alias="_id")`` and
``model_config = ConfigDict(populate_by_name=True)``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


class FadrUploadUrlResponse(BaseModel):
    """Response from ``POST /assets/upload2``."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    url: str = Field(description="Presigned PUT URL for uploading the audio file.")
    s3_path: str = Field(alias="s3Path", description="S3 path to pass to /assets.")


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


class FadrAsset(BaseModel):
    """Represents any Fadr asset (source audio, stem, or MIDI)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    asset_id: str = Field(alias="_id")
    name: str = Field(default="", description="Asset file name or label.")
    extension: str = Field(default="", description="File extension without leading dot.")
    group: str | None = Field(default=None)
    s3_path: str | None = Field(default=None, alias="s3Path")
    asset_type: str | None = Field(default=None, alias="assetType")


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


class FadrMetaData(BaseModel):
    """Musical metadata embedded in the task asset once analysis completes."""

    model_config = ConfigDict(extra="allow")

    tempo: float | None = None
    key: str | None = None
    # chordProgression format varies: may be a CSV string, list of strings,
    # or list of chord dicts.  Parsed defensively in the service layer.
    chord_progression: Any = Field(default=None, alias="chordProgression")
    time_signature: str | None = Field(default=None, alias="timeSignature")
    sample_rate: int | None = Field(default=None, alias="sampleRate")
    beat_grid: Any = Field(default=None, alias="beatGrid")


class FadrTaskAsset(BaseModel):
    """The source asset embedded in a task response, augmented with results."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    asset_id: str = Field(alias="_id")
    name: str = Field(default="")
    extension: str = Field(default="")
    # Populated once stem separation completes:
    stems: list[str] | None = Field(default=None, description="List of stem asset _ids.")
    # Populated once MIDI extraction completes:
    midi: list[str] | None = Field(default=None, description="List of MIDI asset _ids.")
    meta_data: FadrMetaData | None = Field(default=None, alias="metaData")


class FadrTaskStatus(BaseModel):
    """Status object embedded in every Fadr task response."""

    model_config = ConfigDict(extra="allow")

    msg: str = ""
    progress: int = 0
    complete: bool = False


class FadrTask(BaseModel):
    """Represents a Fadr processing task as returned by ``GET /tasks/:_id``."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    task_id: str = Field(alias="_id")
    # status is a nested object {msg, progress, complete}
    status: FadrTaskStatus = Field(default_factory=FadrTaskStatus)
    # asset starts as a string ID when pending; becomes a full object once done
    asset: FadrTaskAsset | str | None = None
