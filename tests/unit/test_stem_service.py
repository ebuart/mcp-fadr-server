"""Unit tests for StemService.

All tests use the mock Fadr client and mock audio fetcher — no network calls.
Polling intervals are set to 0s so tests complete instantly.
"""

from __future__ import annotations

import pytest

from server.clients.mock_client import (
    MockFadrClient,
    build_asset,
    build_done_task,
)
from server.exceptions import TaskFailedError, TaskTimeoutError, UrlValidationError
from server.schemas.fadr_responses import FadrTask
from server.services.stem_service import StemService
from server.utils.config import Settings
from tests.conftest import MIDI_IDS, MIDI_NAMES, STEM_IDS, STEM_NAMES
from tests.helpers import FailingAudioFetcher, MockAudioFetcher, PermissiveUrlValidator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides: object) -> Settings:
    defaults = dict(
        fadr_api_key="test-key",  # type: ignore[arg-type]
        fadr_poll_interval_s=0.0,
        fadr_poll_timeout_s=1.0,
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _make_service(
    client: MockFadrClient,
    fetcher: MockAudioFetcher | FailingAudioFetcher | None = None,
    settings: Settings | None = None,
) -> StemService:
    return StemService(
        fadr_client=client,
        audio_fetcher=fetcher or MockAudioFetcher(),
        url_validator=PermissiveUrlValidator(),  # type: ignore[arg-type]
        config=settings or _make_settings(),
    )


def _default_assets() -> dict:  # type: ignore[type-arg]
    stem = {sid: build_asset(sid, name) for sid, name in zip(STEM_IDS, STEM_NAMES, strict=False)}
    midi = {
        mid: build_asset(mid, name, "mid") for mid, name in zip(MIDI_IDS, MIDI_NAMES, strict=False)
    }
    return {**stem, **midi}


def _default_task() -> FadrTask:
    return build_done_task(
        stem_ids=STEM_IDS,
        midi_ids=MIDI_IDS,
        tempo=128.0,
        key="A minor",
        chord_progression="Am,F,C,G",
        time_signature="4/4",
    )


# ===========================================================================
# separate_stems
# ===========================================================================


class TestSeparateStems:
    async def test_returns_correct_stem_count(self, stem_service: StemService) -> None:
        result = await stem_service.separate_stems("https://example.com/song.mp3")
        assert len(result.stems) == len(STEM_IDS)

    async def test_stem_names_match_assets(self, stem_service: StemService) -> None:
        result = await stem_service.separate_stems("https://example.com/song.mp3")
        names = {s.name for s in result.stems}
        assert names == set(STEM_NAMES)

    async def test_stem_urls_contain_asset_ids(self, stem_service: StemService) -> None:
        result = await stem_service.separate_stems("https://example.com/song.mp3")
        for stem in result.stems:
            # Mock download URL template: "https://mock-cdn.example.com/download/{asset_id}?..."
            assert "mock-cdn.example.com" in stem.url

    async def test_job_id_is_mock_task_id(self, stem_service: StemService) -> None:
        result = await stem_service.separate_stems("https://example.com/song.mp3")
        assert result.job_id == "mock-task-id"

    async def test_processing_time_ms_is_non_negative(self, stem_service: StemService) -> None:
        result = await stem_service.separate_stems("https://example.com/song.mp3")
        assert result.processing_time_ms is not None
        assert result.processing_time_ms >= 0

    async def test_quality_forwarded_to_download_url(self) -> None:
        assets = _default_assets()
        client = MockFadrClient(final_task=_default_task(), assets=assets)
        service = _make_service(client)
        result = await service.separate_stems("https://example.com/song.mp3", quality="download")
        for stem in result.stems:
            assert "quality=download" in stem.url

    async def test_pipeline_calls_all_fadr_endpoints(self) -> None:
        assets = _default_assets()
        client = MockFadrClient(final_task=_default_task(), assets=assets)
        service = _make_service(client)
        await service.separate_stems("https://example.com/song.mp3")

        assert client.upload_url_calls == 1
        assert client.upload_audio_calls == 1
        assert client.create_asset_calls == 1
        assert client.create_stem_task_calls == 1
        assert client.get_task_calls >= 1
        assert client.get_asset_calls == len(STEM_IDS)
        assert client.get_download_url_calls == len(STEM_IDS)


# ===========================================================================
# extract_midi
# ===========================================================================


class TestExtractMidi:
    async def test_returns_correct_midi_count(self, stem_service: StemService) -> None:
        result = await stem_service.extract_midi("https://example.com/song.mp3")
        assert len(result.midi_files) == len(MIDI_IDS)

    async def test_midi_names_match_assets(self, stem_service: StemService) -> None:
        result = await stem_service.extract_midi("https://example.com/song.mp3")
        names = {m.name for m in result.midi_files}
        assert names == set(MIDI_NAMES)

    async def test_midi_urls_contain_quality_download(self, stem_service: StemService) -> None:
        result = await stem_service.extract_midi("https://example.com/song.mp3")
        for midi in result.midi_files:
            assert "quality=download" in midi.url

    async def test_job_id_present(self, stem_service: StemService) -> None:
        result = await stem_service.extract_midi("https://example.com/song.mp3")
        assert result.job_id == "mock-task-id"


# ===========================================================================
# analyze_music
# ===========================================================================


class TestAnalyzeMusic:
    async def test_returns_correct_key(self, stem_service: StemService) -> None:
        result = await stem_service.analyze_music("https://example.com/song.mp3")
        assert result.key == "A minor"

    async def test_returns_correct_tempo(self, stem_service: StemService) -> None:
        result = await stem_service.analyze_music("https://example.com/song.mp3")
        assert result.tempo_bpm == 128.0

    async def test_returns_time_signature(self, stem_service: StemService) -> None:
        result = await stem_service.analyze_music("https://example.com/song.mp3")
        assert result.time_signature == "4/4"

    async def test_chord_progression_parsed_from_csv(self, stem_service: StemService) -> None:
        result = await stem_service.analyze_music("https://example.com/song.mp3")
        assert len(result.chord_progression) == 4
        assert result.chord_progression[0].chord == "Am"
        assert result.chord_progression[3].chord == "G"

    async def test_chord_progression_list_format(self) -> None:
        assets = _default_assets()
        task = build_done_task(
            stem_ids=STEM_IDS,
            midi_ids=MIDI_IDS,
            chord_progression=["Dm", "Bb", "F", "C"],
        )
        service = _make_service(MockFadrClient(final_task=task, assets=assets))
        result = await service.analyze_music("https://example.com/song.mp3")
        assert [e.chord for e in result.chord_progression] == ["Dm", "Bb", "F", "C"]

    async def test_chord_progression_dict_format(self) -> None:
        raw_chords = [
            {"chord": "Am", "beat": 1, "duration": 4},
            {"chord": "F", "beat": 5, "duration": 4},
        ]
        assets = _default_assets()
        task = build_done_task(stem_ids=STEM_IDS, midi_ids=MIDI_IDS, chord_progression=raw_chords)
        service = _make_service(MockFadrClient(final_task=task, assets=assets))
        result = await service.analyze_music("https://example.com/song.mp3")
        assert result.chord_progression[0].start_beat == 1.0

    async def test_none_chord_progression_returns_empty(self) -> None:
        assets = _default_assets()
        task = build_done_task(stem_ids=STEM_IDS, midi_ids=MIDI_IDS, chord_progression=None)
        service = _make_service(MockFadrClient(final_task=task, assets=assets))
        result = await service.analyze_music("https://example.com/song.mp3")
        assert result.chord_progression == []


# ===========================================================================
# Polling behaviour
# ===========================================================================


class TestPolling:
    async def test_polls_until_stems_ready(self) -> None:
        """Service should call get_task multiple times if statuses are 'processing'."""
        assets = _default_assets()
        client = MockFadrClient(
            final_task=_default_task(),
            assets=assets,
            poll_statuses=["processing", "processing"],
        )
        service = _make_service(client, settings=_make_settings(fadr_poll_interval_s=0.0))
        await service.separate_stems("https://example.com/song.mp3")
        # 2 intermediate + 1 final = 3 calls
        assert client.get_task_calls == 3

    async def test_task_timeout_raises(self) -> None:
        """TaskTimeoutError raised when task never completes."""
        assets = _default_assets()

        # Build a task that is never complete (status.complete=False) so polling times out
        from server.schemas.fadr_responses import FadrTask as _FadrTask

        stuck_task = _FadrTask(
            **{"_id": "stuck-id", "status": {"complete": False, "msg": "processing"}, "asset": None}
        )

        client = MockFadrClient(
            final_task=stuck_task,
            assets=assets,
            # always return "processing"
            poll_statuses=["processing"] * 100,
        )
        service = _make_service(
            client,
            settings=_make_settings(fadr_poll_interval_s=0.0, fadr_poll_timeout_s=0.0),
        )
        with pytest.raises(TaskTimeoutError) as exc_info:
            await service.separate_stems("https://example.com/song.mp3")
        assert exc_info.value.error_code == "TASK_TIMEOUT"

    async def test_task_failed_status_raises(self) -> None:
        """TaskFailedError raised when task completes with no stems (failed output)."""
        assets = _default_assets()
        # complete=True but asset=None → "complete but no expected output" → TaskFailedError
        failed_task = FadrTask(
            **{"_id": "fail-id", "status": {"complete": True, "msg": "failed"}, "asset": None}
        )
        client = MockFadrClient(
            final_task=failed_task,
            assets=assets,
            poll_statuses=[],  # immediately return failed_task
        )
        service = _make_service(client)
        with pytest.raises(TaskFailedError) as exc_info:
            await service.separate_stems("https://example.com/song.mp3")
        assert exc_info.value.error_code == "TASK_FAILED"


# ===========================================================================
# URL validation integration
# ===========================================================================


class TestUrlValidation:
    async def test_http_scheme_rejected(self) -> None:
        """UrlValidationError raised for non-https URLs (real validator)."""
        from server.utils.url_validator import UrlValidator

        client = MockFadrClient(final_task=_default_task(), assets=_default_assets())
        # Use real validator with no DNS (we intercept before DNS via scheme check)
        validator = UrlValidator(allowed_schemes=frozenset({"https"}))
        service = StemService(
            fadr_client=client,
            audio_fetcher=MockAudioFetcher(),
            url_validator=validator,
            config=_make_settings(),
        )
        with pytest.raises(UrlValidationError) as exc_info:
            await service.separate_stems("http://example.com/song.mp3")
        assert exc_info.value.error_code == "INVALID_URL"
        assert exc_info.value.details is not None
        assert exc_info.value.details["issue"] == "invalid_scheme"

    async def test_unsupported_extension_rejected(self) -> None:
        from server.utils.url_validator import UrlValidator

        client = MockFadrClient(final_task=_default_task(), assets=_default_assets())
        validator = UrlValidator(allowed_schemes=frozenset({"https"}))
        service = StemService(
            fadr_client=client,
            audio_fetcher=MockAudioFetcher(),
            url_validator=validator,
            config=_make_settings(),
        )
        with pytest.raises(UrlValidationError) as exc_info:
            await service.separate_stems("https://example.com/song.exe")
        assert exc_info.value.error_code == "INVALID_URL"


# ===========================================================================
# Audio download failure
# ===========================================================================


class TestAudioDownload:
    async def test_audio_download_failure_propagates(self) -> None:
        from server.exceptions import AudioDownloadError

        client = MockFadrClient(final_task=_default_task(), assets=_default_assets())
        service = _make_service(client, fetcher=FailingAudioFetcher())
        with pytest.raises(AudioDownloadError):
            await service.separate_stems("https://example.com/song.mp3")
