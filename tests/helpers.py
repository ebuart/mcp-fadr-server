"""Shared test helpers and lightweight mock implementations."""

from __future__ import annotations

from server.exceptions import AudioDownloadError


class MockAudioFetcher:
    """Returns pre-configured bytes without making any network calls."""

    def __init__(
        self,
        audio_bytes: bytes = b"fake-audio-data",
        mime_type: str = "audio/mpeg",
        raise_error: Exception | None = None,
    ) -> None:
        self.audio_bytes = audio_bytes
        self.mime_type = mime_type
        self.raise_error = raise_error
        self.call_count: int = 0

    async def fetch(self, url: str, max_bytes: int) -> tuple[bytes, str]:
        self.call_count += 1
        if self.raise_error is not None:
            raise self.raise_error
        return self.audio_bytes, self.mime_type


class FailingAudioFetcher:
    """Always raises AudioDownloadError."""

    async def fetch(self, url: str, max_bytes: int) -> tuple[bytes, str]:
        raise AudioDownloadError(
            "Mock download failure.",
            details={"url": url, "status_code": 503},
        )


class PermissiveUrlValidator:
    """Accepts every URL without any checks (for service-layer tests)."""

    def validate(self, url: str) -> None:
        pass  # always valid
