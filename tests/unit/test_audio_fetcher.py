"""Unit tests for HttpxAudioFetcher.

Uses a mock httpx client to simulate streaming HTTP responses without network
calls.  Covers happy path, size-limit enforcement, HTTP errors, and network
exceptions.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from server.clients.http_audio_fetcher import HttpxAudioFetcher
from server.exceptions import AudioDownloadError


# ---------------------------------------------------------------------------
# Helpers: fake streaming response
# ---------------------------------------------------------------------------


def _make_stream_response(
    *,
    status_code: int = 200,
    is_success: bool = True,
    headers: dict[str, str] | None = None,
    chunks: list[bytes] | None = None,
) -> MagicMock:
    """Build a mock for the response returned inside an ``httpx.stream()`` context."""
    resp = MagicMock()
    resp.is_success = is_success
    resp.status_code = status_code
    resp.headers = headers or {"content-type": "audio/mpeg"}

    async def _aiter_bytes(chunk_size: int = 65536) -> AsyncIterator[bytes]:
        for chunk in (chunks or [b"fake-audio-data"]):
            yield chunk

    resp.aiter_bytes = _aiter_bytes
    return resp


def _make_fetcher_with_mock_stream(mock_response: MagicMock) -> HttpxAudioFetcher:
    """Return a fetcher whose ``_http.stream()`` yields ``mock_response``."""
    fetcher = HttpxAudioFetcher()

    @asynccontextmanager
    async def _fake_stream(method: str, url: str) -> AsyncIterator[MagicMock]:
        yield mock_response

    mock_http = MagicMock(spec=httpx.AsyncClient)
    mock_http.stream = _fake_stream
    fetcher._http = mock_http  # type: ignore[assignment]
    return fetcher


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestFetchSuccess:
    async def test_returns_audio_bytes(self) -> None:
        resp = _make_stream_response(chunks=[b"hello", b"world"])
        fetcher = _make_fetcher_with_mock_stream(resp)
        data, mime = await fetcher.fetch("https://example.com/song.mp3", max_bytes=10 * 1024 * 1024)
        assert data == b"helloworld"

    async def test_returns_mime_type_from_headers(self) -> None:
        resp = _make_stream_response(headers={"content-type": "audio/wav"})
        fetcher = _make_fetcher_with_mock_stream(resp)
        _, mime = await fetcher.fetch("https://example.com/song.wav", max_bytes=10 * 1024 * 1024)
        assert mime == "audio/wav"

    async def test_strips_charset_from_mime_type(self) -> None:
        resp = _make_stream_response(headers={"content-type": "audio/mpeg; charset=utf-8"})
        fetcher = _make_fetcher_with_mock_stream(resp)
        _, mime = await fetcher.fetch("https://example.com/s.mp3", max_bytes=10 * 1024 * 1024)
        assert mime == "audio/mpeg"

    async def test_defaults_mime_type_when_header_absent(self) -> None:
        resp = _make_stream_response(headers={})
        fetcher = _make_fetcher_with_mock_stream(resp)
        _, mime = await fetcher.fetch("https://example.com/s.mp3", max_bytes=10 * 1024 * 1024)
        assert mime == "audio/mpeg"  # default


# ---------------------------------------------------------------------------
# Size limit enforcement
# ---------------------------------------------------------------------------


class TestSizeLimits:
    async def test_content_length_exceeded_raises(self) -> None:
        resp = _make_stream_response(
            headers={"content-type": "audio/mpeg", "content-length": "99999999"}
        )
        fetcher = _make_fetcher_with_mock_stream(resp)
        with pytest.raises(AudioDownloadError) as exc_info:
            await fetcher.fetch("https://example.com/huge.mp3", max_bytes=1024)
        assert exc_info.value.error_code == "UPLOAD_FAILED"
        assert exc_info.value.details is not None
        assert "declared_bytes" in exc_info.value.details

    async def test_streaming_size_exceeded_raises(self) -> None:
        # Content-Length not provided but actual data exceeds limit
        resp = _make_stream_response(chunks=[b"x" * 512, b"x" * 512])
        fetcher = _make_fetcher_with_mock_stream(resp)
        with pytest.raises(AudioDownloadError) as exc_info:
            await fetcher.fetch("https://example.com/song.mp3", max_bytes=500)
        assert exc_info.value.error_code == "UPLOAD_FAILED"

    async def test_exact_size_limit_allowed(self) -> None:
        payload = b"x" * 100
        resp = _make_stream_response(chunks=[payload])
        fetcher = _make_fetcher_with_mock_stream(resp)
        data, _ = await fetcher.fetch("https://example.com/s.mp3", max_bytes=100)
        assert len(data) == 100


# ---------------------------------------------------------------------------
# HTTP errors
# ---------------------------------------------------------------------------


class TestHttpErrors:
    async def test_non_2xx_raises_audio_download_error(self) -> None:
        resp = _make_stream_response(status_code=404, is_success=False)
        fetcher = _make_fetcher_with_mock_stream(resp)
        with pytest.raises(AudioDownloadError) as exc_info:
            await fetcher.fetch("https://example.com/missing.mp3", max_bytes=10 * 1024 * 1024)
        assert exc_info.value.details is not None
        assert exc_info.value.details["status_code"] == 404

    async def test_503_raises_audio_download_error(self) -> None:
        resp = _make_stream_response(status_code=503, is_success=False)
        fetcher = _make_fetcher_with_mock_stream(resp)
        with pytest.raises(AudioDownloadError):
            await fetcher.fetch("https://example.com/song.mp3", max_bytes=10 * 1024 * 1024)


# ---------------------------------------------------------------------------
# Network exceptions
# ---------------------------------------------------------------------------


class TestNetworkExceptions:
    async def test_timeout_raises_audio_download_error(self) -> None:
        fetcher = HttpxAudioFetcher()
        mock_http = MagicMock(spec=httpx.AsyncClient)

        @asynccontextmanager
        async def _timeout_stream(method: str, url: str) -> AsyncIterator[None]:
            raise httpx.TimeoutException("timed out", request=MagicMock())
            yield  # type: ignore[misc]  # pragma: no cover

        mock_http.stream = _timeout_stream
        fetcher._http = mock_http  # type: ignore[assignment]

        with pytest.raises(AudioDownloadError) as exc_info:
            await fetcher.fetch("https://example.com/song.mp3", max_bytes=10 * 1024 * 1024)
        assert "timed out" in exc_info.value.message.lower()

    async def test_connect_error_raises_audio_download_error(self) -> None:
        fetcher = HttpxAudioFetcher()
        mock_http = MagicMock(spec=httpx.AsyncClient)

        @asynccontextmanager
        async def _connect_error(method: str, url: str) -> AsyncIterator[None]:
            raise httpx.ConnectError("connection refused", request=MagicMock())
            yield  # type: ignore[misc]  # pragma: no cover

        mock_http.stream = _connect_error
        fetcher._http = mock_http  # type: ignore[assignment]

        with pytest.raises(AudioDownloadError) as exc_info:
            await fetcher.fetch("https://example.com/song.mp3", max_bytes=10 * 1024 * 1024)
        assert exc_info.value.error_code == "UPLOAD_FAILED"
