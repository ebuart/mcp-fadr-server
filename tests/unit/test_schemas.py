"""Unit tests for Pydantic schema models.

Covers input validation, output serialisation, envelope construction, and
chord-progression parsing.  No network calls, no Fadr client.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.schemas.envelope import ErrorDetail, ErrorResponse, SuccessResponse, make_error, make_success
from server.schemas.fadr_responses import FadrAsset, FadrMetaData, FadrTask, FadrTaskAsset
from server.schemas.inputs import AnalyzeMusicInput, ExtractMidiInput, SeparateStemsInput
from server.schemas.outputs import AnalysisResult, ChordEntry, MidiFile, MidiResult, StemFile, StemsResult
from server.services.stem_service import _parse_chord_progression


# ===========================================================================
# SeparateStemsInput
# ===========================================================================


class TestSeparateStemsInput:
    def test_valid_with_all_fields(self) -> None:
        inp = SeparateStemsInput(
            audio_url="https://example.com/song.mp3",
            quality="download",
        )
        assert inp.audio_url == "https://example.com/song.mp3"
        assert inp.quality == "download"

    def test_valid_defaults_quality_to_hqpreview(self) -> None:
        inp = SeparateStemsInput(audio_url="https://example.com/song.mp3")
        assert inp.quality == "hqPreview"

    def test_missing_audio_url_raises(self) -> None:
        with pytest.raises(ValidationError, match="audio_url"):
            SeparateStemsInput()  # type: ignore[call-arg]

    def test_invalid_quality_raises(self) -> None:
        with pytest.raises(ValidationError):
            SeparateStemsInput(
                audio_url="https://example.com/song.mp3",
                quality="ultra",  # type: ignore[arg-type]
            )

    def test_extra_fields_raise(self) -> None:
        with pytest.raises(ValidationError):
            SeparateStemsInput(
                audio_url="https://example.com/song.mp3",
                unknown_field="value",  # type: ignore[call-arg]
            )

    @pytest.mark.parametrize("quality", ["preview", "hqPreview", "download"])
    def test_all_valid_qualities(self, quality: str) -> None:
        inp = SeparateStemsInput(audio_url="https://example.com/song.mp3", quality=quality)  # type: ignore[arg-type]
        assert inp.quality == quality


# ===========================================================================
# ExtractMidiInput
# ===========================================================================


class TestExtractMidiInput:
    def test_valid(self) -> None:
        inp = ExtractMidiInput(audio_url="https://example.com/track.wav")
        assert inp.audio_url == "https://example.com/track.wav"

    def test_missing_audio_url_raises(self) -> None:
        with pytest.raises(ValidationError):
            ExtractMidiInput()  # type: ignore[call-arg]

    def test_extra_fields_raise(self) -> None:
        with pytest.raises(ValidationError):
            ExtractMidiInput(audio_url="https://example.com/track.wav", extra="x")  # type: ignore[call-arg]


# ===========================================================================
# AnalyzeMusicInput
# ===========================================================================


class TestAnalyzeMusicInput:
    def test_valid(self) -> None:
        inp = AnalyzeMusicInput(audio_url="https://cdn.example.com/audio/track.flac")
        assert inp.audio_url == "https://cdn.example.com/audio/track.flac"


# ===========================================================================
# Envelope
# ===========================================================================


class TestEnvelope:
    def test_success_response_serialises(self) -> None:
        result = make_success({"job_id": "abc", "stems": []})
        assert result["success"] is True
        assert result["data"]["job_id"] == "abc"
        assert result["error"] is None

    def test_error_response_serialises(self) -> None:
        result = make_error("INVALID_URL", "Bad scheme.", {"field": "audio_url"})
        assert result["success"] is False
        assert result["data"] is None
        assert result["error"]["code"] == "INVALID_URL"
        assert result["error"]["message"] == "Bad scheme."
        assert result["error"]["details"]["field"] == "audio_url"

    def test_error_response_without_details(self) -> None:
        result = make_error("TASK_FAILED", "Task failed.")
        assert result["error"]["details"] is None

    def test_success_response_success_must_be_true(self) -> None:
        with pytest.raises(ValidationError):
            SuccessResponse(success=False, data={})  # type: ignore[arg-type]

    def test_error_response_success_must_be_false(self) -> None:
        with pytest.raises(ValidationError):
            ErrorResponse(
                success=True,  # type: ignore[arg-type]
                error=ErrorDetail(code="X", message="y"),
            )


# ===========================================================================
# Output models
# ===========================================================================


class TestStemsResult:
    def test_valid(self) -> None:
        result = StemsResult(
            job_id="abc",
            stems=[StemFile(name="vocals", url="https://cdn.example.com/vocals.mp3")],
        )
        assert len(result.stems) == 1
        assert result.stems[0].name == "vocals"

    def test_empty_stems_raises(self) -> None:
        with pytest.raises(ValidationError):
            StemsResult(job_id="abc", stems=[])

    def test_processing_time_optional(self) -> None:
        result = StemsResult(job_id="abc", stems=[StemFile(name="bass", url="https://x.com/b.mp3")])
        assert result.processing_time_ms is None


class TestMidiResult:
    def test_valid(self) -> None:
        result = MidiResult(
            job_id="abc",
            midi_files=[MidiFile(name="chord_progression", url="https://cdn.example.com/chords.mid")],
        )
        assert result.midi_files[0].name == "chord_progression"

    def test_empty_midi_raises(self) -> None:
        with pytest.raises(ValidationError):
            MidiResult(job_id="abc", midi_files=[])


class TestAnalysisResult:
    def test_valid_full(self) -> None:
        result = AnalysisResult(
            job_id="abc",
            key="C major",
            tempo_bpm=120.0,
            time_signature="4/4",
            chord_progression=[
                ChordEntry(chord="C", start_beat=1.0, duration_beats=4.0),
                ChordEntry(chord="G"),
            ],
        )
        assert result.key == "C major"
        assert result.tempo_bpm == 120.0
        assert result.chord_progression[1].start_beat is None

    def test_tempo_below_minimum_raises(self) -> None:
        with pytest.raises(ValidationError):
            AnalysisResult(job_id="abc", key="C", tempo_bpm=5.0, chord_progression=[])

    def test_tempo_above_maximum_raises(self) -> None:
        with pytest.raises(ValidationError):
            AnalysisResult(job_id="abc", key="C", tempo_bpm=999.0, chord_progression=[])


# ===========================================================================
# FadrTask / FadrMetaData (raw response models)
# ===========================================================================


class TestFadrResponseModels:
    def test_fadr_task_parses_via_alias(self) -> None:
        task = FadrTask(**{"_id": "task-123", "status": {"complete": True, "msg": "done"}})
        assert task.task_id == "task-123"
        assert task.status.complete is True
        assert task.status.msg == "done"
        assert task.asset is None

    def test_fadr_task_with_asset(self) -> None:
        raw = {
            "_id": "task-456",
            "status": {"complete": True, "msg": "done", "progress": 100},
            "asset": {
                "_id": "asset-789",
                "name": "my-song",
                "extension": "mp3",
                "stems": ["s1", "s2"],
                "midi": ["m1"],
                "metaData": {"tempo": 128.0, "key": "A minor"},
            },
        }
        task = FadrTask(**raw)
        assert isinstance(task.asset, FadrTaskAsset)
        assert task.asset.stems == ["s1", "s2"]
        assert task.asset.meta_data is not None
        assert task.asset.meta_data.tempo == 128.0

    def test_fadr_metadata_extra_fields_allowed(self) -> None:
        meta = FadrMetaData(**{"tempo": 100.0, "key": "D minor", "unknownField": "value"})
        assert meta.tempo == 100.0

    def test_fadr_asset_parses_via_alias(self) -> None:
        asset = FadrAsset(**{"_id": "a1", "name": "vocals", "extension": "mp3"})
        assert asset.asset_id == "a1"
        assert asset.name == "vocals"

    def test_fadr_task_asset_with_partial_data(self) -> None:
        raw = {"_id": "a2", "stems": ["s1"]}
        asset = FadrTaskAsset(**raw)
        assert asset.stems == ["s1"]
        assert asset.midi is None
        assert asset.meta_data is None


# ===========================================================================
# Chord progression parser
# ===========================================================================


class TestParseChordProgression:
    def test_none_returns_empty(self) -> None:
        assert _parse_chord_progression(None) == []

    def test_csv_string(self) -> None:
        result = _parse_chord_progression("Am,F,C,G")
        assert len(result) == 4
        assert result[0].chord == "Am"
        assert result[3].chord == "G"
        assert result[0].start_beat is None

    def test_csv_with_whitespace(self) -> None:
        result = _parse_chord_progression("Am, F , C , G")
        assert [e.chord for e in result] == ["Am", "F", "C", "G"]

    def test_list_of_strings(self) -> None:
        result = _parse_chord_progression(["Dm", "Bb", "F", "C"])
        assert [e.chord for e in result] == ["Dm", "Bb", "F", "C"]

    def test_list_of_dicts_with_timing(self) -> None:
        raw = [
            {"chord": "Am", "beat": 1, "duration": 4},
            {"chord": "F", "beat": 5, "duration": 4},
        ]
        result = _parse_chord_progression(raw)
        assert result[0].chord == "Am"
        assert result[0].start_beat == 1.0
        assert result[0].duration_beats == 4.0
        assert result[1].chord == "F"

    def test_list_of_dicts_with_alternative_keys(self) -> None:
        raw = [{"chord": "G", "start_beat": 9, "duration_beats": 4}]
        result = _parse_chord_progression(raw)
        assert result[0].start_beat == 9.0

    def test_unknown_type_returns_empty(self) -> None:
        assert _parse_chord_progression(42) == []

    def test_empty_list_returns_empty(self) -> None:
        assert _parse_chord_progression([]) == []

    def test_empty_csv_string_returns_empty(self) -> None:
        assert _parse_chord_progression("") == []
