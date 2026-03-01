"""Unit tests for the tools layer.

Each tool handler (separate_stems, extract_midi, analyze_music) is tested for:
- Successful execution → SuccessResponse envelope
- Input validation failure → INVALID_INPUT error envelope
- Service-level exception → typed error envelope
- Unexpected exception → INTERNAL_ERROR envelope

The StemService is replaced with an AsyncMock so no Fadr client is needed.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.exceptions import FadrApiError, TaskTimeoutError, UrlValidationError
from server.schemas.outputs import (
    AnalysisResult,
    ChordEntry,
    MidiFile,
    MidiResult,
    StemFile,
    StemsResult,
)
from server.tools.analyze_music import handle_analyze_music
from server.tools.extract_midi import handle_extract_midi
from server.tools.separate_stems import handle_separate_stems

# ---------------------------------------------------------------------------
# Fixtures: pre-built result objects
# ---------------------------------------------------------------------------

_VALID_URL = "https://example.com/song.mp3"

_STEMS_RESULT = StemsResult(
    job_id="job-stems",
    processing_time_ms=18000,
    stems=[
        StemFile(name="vocals", url="https://cdn.example.com/vocals.mp3"),
        StemFile(name="bass", url="https://cdn.example.com/bass.mp3"),
    ],
)

_MIDI_RESULT = MidiResult(
    job_id="job-midi",
    processing_time_ms=22000,
    midi_files=[
        MidiFile(name="vocals", url="https://cdn.example.com/vocals.mid"),
        MidiFile(name="chord_progression", url="https://cdn.example.com/chords.mid"),
    ],
)

_ANALYSIS_RESULT = AnalysisResult(
    job_id="job-analysis",
    processing_time_ms=19000,
    key="A minor",
    tempo_bpm=128.0,
    time_signature="4/4",
    chord_progression=[
        ChordEntry(chord="Am", start_beat=1.0, duration_beats=4.0),
        ChordEntry(chord="F", start_beat=5.0, duration_beats=4.0),
    ],
)


def _mock_service(
    *,
    separate_stems_result: StemsResult | Exception = _STEMS_RESULT,
    extract_midi_result: MidiResult | Exception = _MIDI_RESULT,
    analyze_music_result: AnalysisResult | Exception = _ANALYSIS_RESULT,
) -> MagicMock:
    """Return a MagicMock StemService that yields the given results."""
    svc = MagicMock()

    async def _separate_stems(*_a: object, **_kw: object) -> StemsResult:
        if isinstance(separate_stems_result, Exception):
            raise separate_stems_result
        return separate_stems_result

    async def _extract_midi(*_a: object, **_kw: object) -> MidiResult:
        if isinstance(extract_midi_result, Exception):
            raise extract_midi_result
        return extract_midi_result

    async def _analyze_music(*_a: object, **_kw: object) -> AnalysisResult:
        if isinstance(analyze_music_result, Exception):
            raise analyze_music_result
        return analyze_music_result

    svc.separate_stems = _separate_stems
    svc.extract_midi = _extract_midi
    svc.analyze_music = _analyze_music
    return svc


# ===========================================================================
# separate_stems tool handler
# ===========================================================================


class TestSeparateStemsHandler:
    async def test_success_returns_envelope(self) -> None:
        svc = _mock_service()
        result = await handle_separate_stems(_VALID_URL, "hqPreview", svc)
        assert result["success"] is True
        assert result["error"] is None
        data = result["data"]
        assert data["job_id"] == "job-stems"
        assert len(data["stems"]) == 2

    async def test_invalid_quality_returns_invalid_input(self) -> None:
        svc = _mock_service()
        result = await handle_separate_stems(_VALID_URL, "ultra", svc)
        assert result["success"] is False
        assert result["error"]["code"] == "INVALID_INPUT"
        assert result["data"] is None

    async def test_none_audio_url_returns_invalid_input(self) -> None:
        # None fails Pydantic str validation; empty string is caught by the URL validator layer
        svc = _mock_service()
        result = await handle_separate_stems(None, "hqPreview", svc)  # type: ignore[arg-type]
        assert result["success"] is False
        assert result["error"]["code"] == "INVALID_INPUT"

    async def test_url_validation_error_returns_error_envelope(self) -> None:
        svc = _mock_service(
            separate_stems_result=UrlValidationError("bad scheme", details={"issue": "scheme"})
        )
        result = await handle_separate_stems(_VALID_URL, "hqPreview", svc)
        assert result["success"] is False
        assert result["error"]["code"] == "INVALID_URL"

    async def test_task_timeout_returns_error_envelope(self) -> None:
        svc = _mock_service(
            separate_stems_result=TaskTimeoutError("task-123", timeout_s=300.0)
        )
        result = await handle_separate_stems(_VALID_URL, "hqPreview", svc)
        assert result["success"] is False
        assert result["error"]["code"] == "TASK_TIMEOUT"

    async def test_fadr_api_error_returns_error_envelope(self) -> None:
        svc = _mock_service(
            separate_stems_result=FadrApiError("api down", status_code=503)
        )
        result = await handle_separate_stems(_VALID_URL, "hqPreview", svc)
        assert result["success"] is False
        assert result["error"]["code"] == "DOWNSTREAM_ERROR"

    async def test_unexpected_exception_returns_internal_error(self) -> None:
        svc = _mock_service(separate_stems_result=RuntimeError("boom"))
        result = await handle_separate_stems(_VALID_URL, "hqPreview", svc)
        assert result["success"] is False
        assert result["error"]["code"] == "INTERNAL_ERROR"

    @pytest.mark.parametrize("quality", ["preview", "hqPreview", "download"])
    async def test_all_valid_qualities_succeed(self, quality: str) -> None:
        svc = _mock_service()
        result = await handle_separate_stems(_VALID_URL, quality, svc)
        assert result["success"] is True


# ===========================================================================
# extract_midi tool handler
# ===========================================================================


class TestExtractMidiHandler:
    async def test_success_returns_envelope(self) -> None:
        svc = _mock_service()
        result = await handle_extract_midi(_VALID_URL, svc)
        assert result["success"] is True
        data = result["data"]
        assert data["job_id"] == "job-midi"
        assert len(data["midi_files"]) == 2

    async def test_none_audio_url_returns_invalid_input(self) -> None:
        svc = _mock_service()
        result = await handle_extract_midi(None, svc)  # type: ignore[arg-type]
        assert result["success"] is False
        assert result["error"]["code"] == "INVALID_INPUT"

    async def test_url_validation_error_propagates(self) -> None:
        svc = _mock_service(
            extract_midi_result=UrlValidationError("private IP", details=None)
        )
        result = await handle_extract_midi(_VALID_URL, svc)
        assert result["error"]["code"] == "INVALID_URL"

    async def test_unexpected_exception_returns_internal_error(self) -> None:
        svc = _mock_service(extract_midi_result=ValueError("unexpected"))
        result = await handle_extract_midi(_VALID_URL, svc)
        assert result["error"]["code"] == "INTERNAL_ERROR"


# ===========================================================================
# analyze_music tool handler
# ===========================================================================


class TestAnalyzeMusicHandler:
    async def test_success_returns_envelope(self) -> None:
        svc = _mock_service()
        result = await handle_analyze_music(_VALID_URL, svc)
        assert result["success"] is True
        data = result["data"]
        assert data["key"] == "A minor"
        assert data["tempo_bpm"] == 128.0
        assert data["time_signature"] == "4/4"
        assert len(data["chord_progression"]) == 2

    async def test_none_audio_url_returns_invalid_input(self) -> None:
        svc = _mock_service()
        result = await handle_analyze_music(None, svc)  # type: ignore[arg-type]
        assert result["success"] is False
        assert result["error"]["code"] == "INVALID_INPUT"

    async def test_fadr_api_error_propagates(self) -> None:
        svc = _mock_service(
            analyze_music_result=FadrApiError("rate limited", status_code=429)
        )
        result = await handle_analyze_music(_VALID_URL, svc)
        assert result["error"]["code"] == "DOWNSTREAM_ERROR"

    async def test_unexpected_exception_returns_internal_error(self) -> None:
        svc = _mock_service(analyze_music_result=MemoryError("oom"))
        result = await handle_analyze_music(_VALID_URL, svc)
        assert result["error"]["code"] == "INTERNAL_ERROR"

    async def test_chord_progression_in_output(self) -> None:
        svc = _mock_service()
        result = await handle_analyze_music(_VALID_URL, svc)
        chords = result["data"]["chord_progression"]
        assert chords[0]["chord"] == "Am"
        assert chords[0]["start_beat"] == 1.0


# ===========================================================================
# Envelope is valid JSON when serialised
# ===========================================================================


class TestEnvelopeJsonSerialisation:
    async def test_success_envelope_is_valid_json(self) -> None:
        svc = _mock_service()
        result = await handle_separate_stems(_VALID_URL, "hqPreview", svc)
        json_str = json.dumps(result)
        parsed = json.loads(json_str)
        assert parsed["success"] is True

    async def test_error_envelope_is_valid_json(self) -> None:
        svc = _mock_service(separate_stems_result=FadrApiError("err", status_code=500))
        result = await handle_separate_stems(_VALID_URL, "hqPreview", svc)
        json_str = json.dumps(result)
        parsed = json.loads(json_str)
        assert parsed["success"] is False
