"""HTTP audio fetcher — real implementation of AudioFetcherProtocol.

Downloads audio from a public URL using ``httpx``, enforcing a configurable
byte-size limit.  The response is streamed so we can enforce the limit
without loading the full file into memory before the check.

This module has no Fadr-specific knowledge.  It only knows how to perform
a safe bounded HTTP download.
"""

from __future__ import annotations

import httpx

from server.exceptions import AudioDownloadError
from server.utils.logging import get_logger

_logger = get_logger(__name__)

_DEFAULT_CHUNK_SIZE: int = 65_536  # 64 KiB


class HttpxAudioFetcher:
    """Downloads audio from a public URL up to *max_bytes*."""

    def __init__(
        self,
        *,
        timeout_s: float = 30.0,
        _http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._http = _http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s),
            follow_redirects=True,
        )

    async def fetch(self, url: str, max_bytes: int) -> tuple[bytes, str]:
        """Download audio from *url*, raising if it exceeds *max_bytes*.

        Args:
            url: Validated public URL of the audio file.
            max_bytes: Maximum number of bytes to accept.

        Returns:
            ``(audio_bytes, mime_type)`` tuple.

        Raises:
            :class:`~server.exceptions.AudioDownloadError`: on any failure.
        """
        try:
            async with self._http.stream("GET", url) as response:
                if not response.is_success:
                    raise AudioDownloadError(
                        f"Failed to download audio (HTTP {response.status_code}).",
                        details={"status_code": response.status_code},
                    )

                # Reject oversized files declared in Content-Length
                content_length_hdr = response.headers.get("content-length")
                if content_length_hdr:
                    declared_size = int(content_length_hdr)
                    if declared_size > max_bytes:
                        raise AudioDownloadError(
                            f"Audio file exceeds the maximum allowed size "
                            f"({max_bytes // (1024 * 1024)} MB).",
                            details={"declared_bytes": declared_size, "max_bytes": max_bytes},
                        )

                mime_type = response.headers.get("content-type", "audio/mpeg").split(";")[0].strip()

                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes(chunk_size=_DEFAULT_CHUNK_SIZE):
                    total += len(chunk)
                    if total > max_bytes:
                        raise AudioDownloadError(
                            f"Audio file exceeds the maximum allowed size "
                            f"({max_bytes // (1024 * 1024)} MB).",
                            details={"max_bytes": max_bytes},
                        )
                    chunks.append(chunk)

        except AudioDownloadError:
            raise
        except httpx.TimeoutException as exc:
            raise AudioDownloadError(
                "Timed out while downloading audio.",
                details={"error": type(exc).__name__},
            ) from exc
        except httpx.RequestError as exc:
            raise AudioDownloadError(
                "Network error while downloading audio.",
                details={"error": type(exc).__name__},
            ) from exc

        audio_bytes = b"".join(chunks)
        _logger.debug(
            "Audio downloaded successfully.",
            extra={"size_bytes": len(audio_bytes), "mime_type": mime_type},
        )
        return audio_bytes, mime_type
