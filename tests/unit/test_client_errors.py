"""Tests for client error handling and exception propagation.

Verifies that:
1. FadrApiError raised by the mock client propagates correctly to callers.
2. Error codes on typed exceptions match the envelope error code contract.
3. Exception messages do not contain the API key (security baseline).
"""

from __future__ import annotations

import pytest

from server.clients.mock_client import MockFadrClient, build_asset, build_done_task
from server.exceptions import (
    AudioDownloadError,
    FadrApiError,
    FadrServerError,
    TaskFailedError,
    TaskTimeoutError,
    UrlValidationError,
)
from server.services.stem_service import StemService
from server.utils.config import Settings
from tests.conftest import MIDI_IDS, MIDI_NAMES, STEM_IDS, STEM_NAMES
from tests.helpers import FailingAudioFetcher, MockAudioFetcher, PermissiveUrlValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_API_KEY = "super-secret-api-key-do-not-log-12345"


def _make_settings() -> Settings:
    return Settings(
        fadr_api_key=_API_KEY,  # type: ignore[arg-type]
        fadr_poll_interval_s=0.0,
        fadr_poll_timeout_s=0.5,
    )


def _make_assets() -> dict:  # type: ignore[type-arg]
    stem = {sid: build_asset(sid, name) for sid, name in zip(STEM_IDS, STEM_NAMES)}
    midi = {mid: build_asset(mid, name, "mid") for mid, name in zip(MIDI_IDS, MIDI_NAMES)}
    return {**stem, **midi}


def _make_done_task():  # type: ignore[return]
    return build_done_task(stem_ids=STEM_IDS, midi_ids=MIDI_IDS)


# ===========================================================================
# Error code contract
# ===========================================================================


class TestErrorCodes:
    """Verify that each exception carries the correct error_code string."""

    def test_url_validation_error_code(self) -> None:
        exc = UrlValidationError("bad url")
        assert exc.error_code == "INVALID_URL"

    def test_audio_download_error_code(self) -> None:
        exc = AudioDownloadError("download failed")
        assert exc.error_code == "UPLOAD_FAILED"

    def test_fadr_api_error_code(self) -> None:
        exc = FadrApiError("api error", status_code=500)
        assert exc.error_code == "DOWNSTREAM_ERROR"
        assert exc.status_code == 500

    def test_task_failed_error_code(self) -> None:
        exc = TaskFailedError("task-123")
        assert exc.error_code == "TASK_FAILED"
        assert exc.task_id == "task-123"

    def test_task_timeout_error_code(self) -> None:
        exc = TaskTimeoutError("task-456", timeout_s=300.0)
        assert exc.error_code == "TASK_TIMEOUT"
        assert exc.timeout_s == 300.0

    def test_all_exceptions_are_fadr_server_error(self) -> None:
        for exc_cls in (
            UrlValidationError,
            AudioDownloadError,
            FadrApiError,
            TaskFailedError,
            TaskTimeoutError,
        ):
            assert issubclass(exc_cls, FadrServerError)


# ===========================================================================
# Upload failure propagation
# ===========================================================================


class TestUploadFailurePropagation:
    async def test_upload_failure_raises_fadr_api_error(self) -> None:
        error = FadrApiError("S3 PUT failed", status_code=503)
        client = MockFadrClient(
            final_task=_make_done_task(),
            assets=_make_assets(),
            raise_on_upload=error,
        )
        service = StemService(
            fadr_client=client,
            audio_fetcher=MockAudioFetcher(),
            url_validator=PermissiveUrlValidator(),  # type: ignore[arg-type]
            config=_make_settings(),
        )
        with pytest.raises(FadrApiError) as exc_info:
            await service.separate_stems("https://example.com/song.mp3")
        assert exc_info.value.status_code == 503
        assert exc_info.value.error_code == "DOWNSTREAM_ERROR"


# ===========================================================================
# Create task failure propagation
# ===========================================================================


class TestCreateTaskFailurePropagation:
    async def test_create_task_failure_propagates(self) -> None:
        error = FadrApiError("Billing threshold exceeded", status_code=402)
        client = MockFadrClient(
            final_task=_make_done_task(),
            assets=_make_assets(),
            raise_on_create_task=error,
        )
        service = StemService(
            fadr_client=client,
            audio_fetcher=MockAudioFetcher(),
            url_validator=PermissiveUrlValidator(),  # type: ignore[arg-type]
            config=_make_settings(),
        )
        with pytest.raises(FadrApiError) as exc_info:
            await service.extract_midi("https://example.com/song.mp3")
        assert exc_info.value.status_code == 402


# ===========================================================================
# Audio download failure
# ===========================================================================


class TestAudioDownloadFailure:
    async def test_audio_download_error_propagates(self) -> None:
        client = MockFadrClient(final_task=_make_done_task(), assets=_make_assets())
        service = StemService(
            fadr_client=client,
            audio_fetcher=FailingAudioFetcher(),
            url_validator=PermissiveUrlValidator(),  # type: ignore[arg-type]
            config=_make_settings(),
        )
        with pytest.raises(AudioDownloadError):
            await service.analyze_music("https://example.com/song.mp3")

    async def test_upload_not_called_on_download_failure(self) -> None:
        client = MockFadrClient(final_task=_make_done_task(), assets=_make_assets())
        service = StemService(
            fadr_client=client,
            audio_fetcher=FailingAudioFetcher(),
            url_validator=PermissiveUrlValidator(),  # type: ignore[arg-type]
            config=_make_settings(),
        )
        with pytest.raises(AudioDownloadError):
            await service.separate_stems("https://example.com/song.mp3")
        # Upload URL should never be requested if download fails first
        assert client.upload_url_calls == 0


# ===========================================================================
# Security: API key not in exception messages
# ===========================================================================


class TestApiKeyNotInExceptions:
    def test_fadr_api_error_message_does_not_contain_key(self) -> None:
        exc = FadrApiError("Unauthorised", status_code=401)
        assert _API_KEY not in str(exc)
        assert _API_KEY not in exc.message

    def test_task_failed_error_message_does_not_contain_key(self) -> None:
        exc = TaskFailedError("task-xyz")
        assert _API_KEY not in str(exc)

    def test_url_validation_error_does_not_contain_key(self) -> None:
        exc = UrlValidationError("invalid scheme", details={"issue": "invalid_scheme"})
        assert _API_KEY not in str(exc)
        if exc.details:
            for v in exc.details.values():
                assert _API_KEY not in str(v)


# ===========================================================================
# MockFadrClient call counters
# ===========================================================================


class TestMockClientCallCounters:
    async def test_counters_start_at_zero(self) -> None:
        client = MockFadrClient(final_task=_make_done_task(), assets=_make_assets())
        assert client.upload_url_calls == 0
        assert client.upload_audio_calls == 0
        assert client.create_asset_calls == 0
        assert client.create_stem_task_calls == 0
        assert client.get_task_calls == 0
        assert client.get_asset_calls == 0
        assert client.get_download_url_calls == 0

    async def test_counters_increment_on_call(self) -> None:
        client = MockFadrClient(final_task=_make_done_task(), assets=_make_assets())
        service = StemService(
            fadr_client=client,
            audio_fetcher=MockAudioFetcher(),
            url_validator=PermissiveUrlValidator(),  # type: ignore[arg-type]
            config=_make_settings(),
        )
        await service.separate_stems("https://example.com/song.mp3")
        assert client.upload_url_calls == 1
        assert client.upload_audio_calls == 1
        assert client.create_asset_calls == 1
        assert client.create_stem_task_calls == 1
