"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from server.clients.mock_client import (
    MockFadrClient,
    build_asset,
    build_done_task,
)
from server.schemas.fadr_responses import FadrAsset, FadrTask
from server.services.stem_service import StemService
from server.utils.config import Settings
from tests.helpers import MockAudioFetcher, PermissiveUrlValidator

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

TEST_FADR_API_KEY = "test-key-not-a-real-secret"


@pytest.fixture
def settings() -> Settings:
    """Settings with a zero poll interval so tests never sleep."""
    return Settings(
        fadr_api_key=TEST_FADR_API_KEY,  # type: ignore[arg-type]
        fadr_poll_interval_s=0.0,
        fadr_poll_timeout_s=1.0,
    )


# ---------------------------------------------------------------------------
# Standard stem + MIDI asset fixtures
# ---------------------------------------------------------------------------

STEM_IDS = ["stem-vocals", "stem-bass", "stem-drums", "stem-melodies", "stem-instrumental"]
MIDI_IDS = ["midi-vocals", "midi-bass", "midi-melodies", "midi-chords"]

STEM_NAMES = ["vocals", "bass", "drums", "melodies", "instrumental"]
MIDI_NAMES = ["vocals", "bass", "melodies", "chord_progression"]


@pytest.fixture
def stem_assets() -> dict[str, FadrAsset]:
    return {sid: build_asset(sid, name) for sid, name in zip(STEM_IDS, STEM_NAMES, strict=False)}


@pytest.fixture
def midi_assets() -> dict[str, FadrAsset]:
    return {
        mid: build_asset(mid, name, extension="mid")
        for mid, name in zip(MIDI_IDS, MIDI_NAMES, strict=False)
    }


@pytest.fixture
def all_assets(
    stem_assets: dict[str, FadrAsset],
    midi_assets: dict[str, FadrAsset],
) -> dict[str, FadrAsset]:
    return {**stem_assets, **midi_assets}


@pytest.fixture
def done_task(all_assets: dict[str, FadrAsset]) -> FadrTask:
    return build_done_task(
        stem_ids=STEM_IDS,
        midi_ids=MIDI_IDS,
        tempo=128.0,
        key="A minor",
        chord_progression="Am,F,C,G",
        time_signature="4/4",
    )


@pytest.fixture
def mock_client(
    done_task: FadrTask,
    all_assets: dict[str, FadrAsset],
) -> MockFadrClient:
    return MockFadrClient(final_task=done_task, assets=all_assets)


# ---------------------------------------------------------------------------
# Service fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def audio_fetcher() -> MockAudioFetcher:
    return MockAudioFetcher()


@pytest.fixture
def stem_service(
    mock_client: MockFadrClient,
    audio_fetcher: MockAudioFetcher,
    settings: Settings,
) -> StemService:
    return StemService(
        fadr_client=mock_client,
        audio_fetcher=audio_fetcher,
        url_validator=PermissiveUrlValidator(),  # type: ignore[arg-type]
        config=settings,
    )
