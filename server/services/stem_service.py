"""Stem service — orchestrates the full Fadr pipeline.

All three MCP tools (``separate_stems``, ``extract_midi``, ``analyze_music``)
share this single service.  Each tool calls the corresponding public method,
which runs the same underlying Fadr workflow and returns a different projection
of the task result.

Fadr pipeline (all three tools):
  1. Validate audio_url (SSRF + scheme + extension)
  2. Download audio bytes from audio_url
  3. Get presigned upload URL  → POST /assets/upload2
  4. Upload audio bytes        → PUT <presigned_url>
  5. Register Fadr asset       → POST /assets
  6. Start stem task           → POST /assets/analyze/stem  (model="main")
  7. Poll until ready          → GET /tasks/:_id  (every poll_interval_s)
  8. Fetch asset metadata      → GET /assets/:_id  (per stem/MIDI asset)
  9. Fetch download URLs       → GET /assets/download/:_id/:quality
 10. Return normalised result

Notes:
  - ``separate_stems`` polls until stems are populated (step 8 optional for MIDI).
  - ``extract_midi`` and ``analyze_music`` poll until MIDI + metaData are ready.
  - The audio_url download is handled by the injected ``AudioFetcherProtocol``.
  - All HTTP calls to api.fadr.com go through the injected ``FadrClientBase``.
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any, Protocol
from urllib.parse import urlparse

from server.clients.base import FadrClientBase
from server.exceptions import FadrServerError, TaskFailedError, TaskTimeoutError
from server.schemas.fadr_responses import FadrTask, FadrTaskAsset
from server.schemas.outputs import (
    AnalysisResult,
    ChordEntry,
    MidiFile,
    MidiResult,
    StemFile,
    StemsResult,
)
from server.utils.config import Settings
from server.utils.url_validator import UrlValidator


# ---------------------------------------------------------------------------
# Audio fetcher protocol (injectable for testing)
# ---------------------------------------------------------------------------


class AudioFetcherProtocol(Protocol):
    """Defines the interface for downloading audio from a URL."""

    async def fetch(self, url: str, max_bytes: int) -> tuple[bytes, str]:
        """Fetch audio from *url*.

        Args:
            url: Validated public HTTPS URL of the audio file.
            max_bytes: Maximum number of bytes to read; abort if exceeded.

        Returns:
            ``(audio_bytes, mime_type)`` where ``mime_type`` is the
            ``Content-Type`` of the response (e.g. ``"audio/mpeg"``).

        Raises:
            :class:`~server.exceptions.AudioDownloadError`: on any failure.
        """
        ...


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _ReadyCriteria(str, Enum):
    """Defines what task output to wait for before returning."""

    STEMS = "stems"
    MIDI = "midi"


def _extract_name_and_extension(url: str) -> tuple[str, str]:
    """Extract filename and extension from a URL path."""
    path = urlparse(url).path
    last_segment = path.split("/")[-1] or "audio"
    if "." in last_segment:
        name, ext = last_segment.rsplit(".", 1)
        return name, ext.lower()
    return last_segment, "mp3"


def _mime_type_for_extension(ext: str) -> str:
    _MAP = {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "aac": "audio/aac",
        "flac": "audio/flac",
        "ogg": "audio/ogg",
        "m4a": "audio/mp4",
    }
    return _MAP.get(ext.lower(), "audio/mpeg")


def _parse_chord_progression(raw: Any) -> list[ChordEntry]:
    """Parse Fadr's chord_progression field into a list of :class:`ChordEntry`.

    Handles the following formats observed in Fadr responses:
    * ``None`` → empty list
    * CSV string ``"Am,F,C,G"`` → list of chord-only entries
    * List of strings ``["Am", "F"]`` → same
    * List of dicts ``[{"chord": "Am", "beat": 1}]`` → with optional timing
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        chords = [c.strip() for c in raw.split(",") if c.strip()]
        return [ChordEntry(chord=c) for c in chords]
    if isinstance(raw, list):
        entries: list[ChordEntry] = []
        for item in raw:
            if isinstance(item, str):
                entries.append(ChordEntry(chord=item.strip()))
            elif isinstance(item, dict):
                chord_str = str(item.get("chord", ""))
                start = item.get("beat") or item.get("start_beat")
                dur = item.get("duration") or item.get("duration_beats")
                entries.append(
                    ChordEntry(
                        chord=chord_str,
                        start_beat=float(start) if start is not None else None,
                        duration_beats=float(dur) if dur is not None else None,
                    )
                )
        return entries
    return []


def _task_meets_criteria(task: FadrTask, criteria: _ReadyCriteria) -> bool:
    if not task.status.complete:
        return False
    if not isinstance(task.asset, FadrTaskAsset):
        return False
    if criteria == _ReadyCriteria.STEMS:
        return bool(task.asset.stems)
    if criteria == _ReadyCriteria.MIDI:
        return bool(task.asset.midi)
    return False  # pragma: no cover


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class StemService:
    """Orchestrates the Fadr stem-separation pipeline.

    All dependencies are injected to keep the service fully testable
    without network access.
    """

    def __init__(
        self,
        fadr_client: FadrClientBase,
        audio_fetcher: AudioFetcherProtocol,
        url_validator: UrlValidator,
        config: Settings,
    ) -> None:
        self._fadr_client = fadr_client
        self._audio_fetcher = audio_fetcher
        self._url_validator = url_validator
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def separate_stems(
        self,
        audio_url: str,
        quality: str = "hqPreview",
    ) -> StemsResult:
        """Run the Fadr pipeline and return separated stem download URLs."""
        task, processing_time_ms = await self._run_pipeline(
            audio_url, criteria=_ReadyCriteria.STEMS
        )
        return await self._build_stems_result(task, quality, processing_time_ms)

    async def extract_midi(self, audio_url: str) -> MidiResult:
        """Run the Fadr pipeline and return MIDI file download URLs."""
        task, processing_time_ms = await self._run_pipeline(
            audio_url, criteria=_ReadyCriteria.MIDI
        )
        return await self._build_midi_result(task, processing_time_ms)

    async def analyze_music(self, audio_url: str) -> AnalysisResult:
        """Run the Fadr pipeline and return key, tempo, and chord analysis."""
        # Analysis metadata is available at the same time as MIDI.
        task, processing_time_ms = await self._run_pipeline(
            audio_url, criteria=_ReadyCriteria.MIDI
        )
        return self._build_analysis_result(task, processing_time_ms)

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    async def _run_pipeline(
        self,
        audio_url: str,
        criteria: _ReadyCriteria,
    ) -> tuple[FadrTask, int]:
        """Execute the full Fadr upload-analyze-poll pipeline.

        Returns:
            ``(final_task, processing_time_ms)`` where ``processing_time_ms``
            is the wall-clock duration of the polling phase.

        Raises:
            :class:`~server.exceptions.UrlValidationError`: invalid URL.
            :class:`~server.exceptions.AudioDownloadError`: download failure.
            :class:`~server.exceptions.FadrApiError`: Fadr HTTP error.
            :class:`~server.exceptions.TaskFailedError`: task ended as failed.
            :class:`~server.exceptions.TaskTimeoutError`: polling timed out.
        """
        # 1. Validate URL (raises UrlValidationError on failure)
        self._url_validator.validate(audio_url)

        # 2. Download audio (raises AudioDownloadError on failure)
        audio_bytes, mime_type = await self._audio_fetcher.fetch(
            audio_url,
            max_bytes=self._config.max_audio_size_bytes,
        )

        name, extension = _extract_name_and_extension(audio_url)
        if not mime_type:
            mime_type = _mime_type_for_extension(extension)

        # 3. Get presigned upload URL
        upload_resp = await self._fadr_client.get_upload_url(name, extension)

        # 4. Upload audio
        await self._fadr_client.upload_audio(upload_resp.url, audio_bytes, mime_type)

        # 5. Create asset record
        asset = await self._fadr_client.create_asset(name, extension, upload_resp.s3_path)

        # 6. Start stem task
        task_ref = await self._fadr_client.create_stem_task(asset.asset_id)

        # 7. Poll until complete
        poll_start = time.monotonic()
        final_task = await self._poll_until_ready(task_ref.task_id, criteria)
        processing_time_ms = int((time.monotonic() - poll_start) * 1000)

        return final_task, processing_time_ms

    async def _poll_until_ready(
        self,
        task_id: str,
        criteria: _ReadyCriteria,
    ) -> FadrTask:
        """Poll ``GET /tasks/:_id`` until the task meets *criteria* or times out."""
        deadline = time.monotonic() + self._config.fadr_poll_timeout_s

        while True:
            task = await self._fadr_client.get_task(task_id)

            if task.status.complete:
                if _task_meets_criteria(task, criteria):
                    return task
                # Completed but expected output is missing → task failed
                raise TaskFailedError(task_id, details={"msg": task.status.msg})

            if time.monotonic() >= deadline:
                raise TaskTimeoutError(task_id, self._config.fadr_poll_timeout_s)

            await asyncio.sleep(self._config.fadr_poll_interval_s)

    # ------------------------------------------------------------------
    # Result builders
    # ------------------------------------------------------------------

    async def _build_stems_result(
        self,
        task: FadrTask,
        quality: str,
        processing_time_ms: int,
    ) -> StemsResult:
        if not isinstance(task.asset, FadrTaskAsset) or not task.asset.stems:
            raise TaskFailedError(
                task.task_id,
                details={"reason": "task completed with no stems"},
            )

        async def _resolve_stem(stem_id: str) -> StemFile:
            asset, url = await asyncio.gather(
                self._fadr_client.get_asset(stem_id),
                self._fadr_client.get_download_url(stem_id, quality),
            )
            return StemFile(name=asset.name, url=url)

        stems = list(
            await asyncio.gather(*[_resolve_stem(sid) for sid in task.asset.stems])
        )
        return StemsResult(
            job_id=task.task_id,
            processing_time_ms=processing_time_ms,
            stems=stems,
        )

    async def _build_midi_result(
        self,
        task: FadrTask,
        processing_time_ms: int,
    ) -> MidiResult:
        if not isinstance(task.asset, FadrTaskAsset) or not task.asset.midi:
            raise TaskFailedError(
                task.task_id,
                details={"reason": "task completed with no MIDI assets"},
            )

        # MIDI files use the "download" quality (lossless)
        async def _resolve_midi(midi_id: str) -> MidiFile:
            asset, url = await asyncio.gather(
                self._fadr_client.get_asset(midi_id),
                self._fadr_client.get_download_url(midi_id, "download"),
            )
            return MidiFile(name=asset.name, url=url)

        midi_files = list(
            await asyncio.gather(*[_resolve_midi(mid) for mid in task.asset.midi])
        )

        # Include any extra metadata (sample_rate, beat_grid) if present
        extra_meta: dict[str, Any] | None = None
        if task.asset.meta_data:
            meta = task.asset.meta_data
            extra_meta = {}
            if meta.sample_rate is not None:
                extra_meta["sample_rate"] = meta.sample_rate
            if meta.beat_grid is not None:
                extra_meta["beat_grid"] = meta.beat_grid
            if not extra_meta:
                extra_meta = None

        return MidiResult(
            job_id=task.task_id,
            processing_time_ms=processing_time_ms,
            midi_files=midi_files,
            metadata=extra_meta,
        )

    def _build_analysis_result(
        self,
        task: FadrTask,
        processing_time_ms: int,
    ) -> AnalysisResult:
        if not isinstance(task.asset, FadrTaskAsset) or not task.asset.meta_data:
            raise TaskFailedError(
                task.task_id,
                details={"reason": "task completed with no metadata"},
            )

        meta = task.asset.meta_data

        if meta.tempo is None or meta.key is None:
            raise TaskFailedError(
                task.task_id,
                details={"reason": "incomplete metadata: missing key or tempo"},
            )

        return AnalysisResult(
            job_id=task.task_id,
            processing_time_ms=processing_time_ms,
            key=meta.key,
            tempo_bpm=meta.tempo,
            time_signature=meta.time_signature,
            chord_progression=_parse_chord_progression(meta.chord_progression),
        )


# ---------------------------------------------------------------------------
# Re-export for convenience
# ---------------------------------------------------------------------------

__all__ = ["StemService", "AudioFetcherProtocol"]


# Suppress F401 (imported but unused) — FadrServerError is a legitimate
# side-effect import that documents the exceptions the service may raise.
_ = FadrServerError
