"""Real Fadr API HTTP client.

Implements :class:`~server.clients.base.FadrClientBase` using ``httpx``.

Security rules enforced here:
- API key is accessed via ``SecretStr.get_secret_value()`` immediately before
  each request and never stored in a local variable that outlives the call.
- API key is never included in log records or exception messages.
- TLS certificate verification is always enabled (httpx default).

Retry logic:
- Retryable HTTP status codes: 429, 500, 502, 503, 504.
- Exponential backoff: ``2 ** attempt`` seconds between retries.
- Network-level errors (``httpx.RequestError``) are retried the same way.
- Non-retryable errors (401, 402, 403, 404, 422) raise immediately.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

import httpx

from server.clients.base import FadrClientBase
from server.exceptions import FadrApiError
from server.schemas.fadr_responses import FadrAsset, FadrTask, FadrUploadUrlResponse
from server.utils.config import Settings
from server.utils.logging import get_logger

_logger = get_logger(__name__)

_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

_STATUS_MESSAGES: dict[int, str] = {
    401: "Unauthorized: your FADR_API_KEY is invalid or missing.",
    402: "Payment required: Fadr billing threshold exceeded. Check your account.",
    403: "Forbidden: insufficient API permissions.",
    404: "Resource not found on Fadr API.",
    422: "Unprocessable request: Fadr rejected the input.",
    429: "Rate limited by Fadr API.",
}


class FadrHttpClient(FadrClientBase):
    """Production HTTP client for ``https://api.fadr.com``."""

    def __init__(
        self,
        settings: Settings,
        *,
        _http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = settings.fadr_base_url.rstrip("/")
        self._api_key = settings.fadr_api_key  # SecretStr — never log
        self._max_retries = settings.fadr_max_retries
        self._http = _http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.fadr_timeout_s),
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    # Public interface (FadrClientBase)
    # ------------------------------------------------------------------

    async def get_upload_url(self, name: str, extension: str) -> FadrUploadUrlResponse:
        data = await self._fadr_post(
            "/assets/upload2",
            json_body={"name": name, "extension": extension},
        )
        return FadrUploadUrlResponse(**data)

    async def upload_audio(
        self,
        presigned_url: str,
        audio_bytes: bytes,
        mime_type: str,
    ) -> None:
        """PUT audio bytes directly to the S3 presigned URL (no Fadr auth)."""
        try:
            response = await self._http.put(
                presigned_url,
                content=audio_bytes,
                headers={"Content-Type": mime_type},
            )
        except httpx.RequestError as exc:
            raise FadrApiError(
                "Network error uploading audio to storage.",
                details={"error": type(exc).__name__},
            ) from exc

        if not response.is_success:
            raise FadrApiError(
                "Failed to upload audio to presigned URL.",
                status_code=response.status_code,
                details={"status_code": response.status_code},
            )

    async def get_download_url(self, asset_id: str, quality: str) -> str:
        data = await self._fadr_get(f"/assets/download/{asset_id}/{quality}")
        # Fadr returns {"url": "..."} — handle both dict and plain string
        if isinstance(data, dict):
            url = data.get("url")
            if url and isinstance(url, str):
                return cast(str, url)
        if isinstance(data, str):
            return data
        raise FadrApiError(
            "Unexpected response format from Fadr download URL endpoint.",
            details={"asset_id": asset_id, "quality": quality},
        )

    async def create_asset(
        self,
        name: str,
        extension: str,
        s3_path: str,
        group: str | None = None,
    ) -> FadrAsset:
        body: dict[str, Any] = {"name": name, "extension": extension, "s3Path": s3_path}
        if group is not None:
            body["group"] = group
        data = await self._fadr_post("/assets", json_body=body)
        # POST /assets returns {"asset": {...}}
        return FadrAsset(**data["asset"])

    async def get_asset(self, asset_id: str) -> FadrAsset:
        data = await self._fadr_get(f"/assets/{asset_id}")
        # GET /assets/:id returns {"asset": {...}}
        return FadrAsset(**data["asset"])

    async def create_stem_task(
        self,
        asset_id: str,
        model: str = "main",
    ) -> FadrTask:
        data = await self._fadr_post(
            "/assets/analyze/stem",
            json_body={"_id": asset_id, "model": model},
        )
        # POST /assets/analyze/stem returns {"msg": "...", "task": {...}}
        return FadrTask(**data["task"])

    async def get_task(self, task_id: str) -> FadrTask:
        data = await self._fadr_get(f"/tasks/{task_id}")
        # GET /tasks/:id returns {"task": {...}}
        return FadrTask(**data["task"])

    # ------------------------------------------------------------------
    # Private HTTP helpers
    # ------------------------------------------------------------------

    @property
    def _auth_headers(self) -> dict[str, str]:
        # Key accessed here and not stored beyond this call
        return {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}

    async def _fadr_post(self, path: str, *, json_body: dict[str, Any]) -> Any:
        return await self._fadr_request("POST", path, json_body=json_body)

    async def _fadr_get(self, path: str) -> Any:
        return await self._fadr_request("GET", path)

    async def _fadr_request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        """Send an authenticated request to the Fadr API with retry logic."""
        url = f"{self._base_url}{path}"

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._http.request(
                    method,
                    url,
                    headers=self._auth_headers,
                    json=json_body,
                )
            except httpx.RequestError as exc:
                if attempt < self._max_retries:
                    delay = 2**attempt
                    _logger.warning(
                        "Network error on Fadr request, retrying.",
                        extra={
                            "attempt": attempt + 1,
                            "max_retries": self._max_retries,
                            "delay_s": delay,
                            "error_type": type(exc).__name__,
                            "path": path,
                        },
                    )
                    await asyncio.sleep(delay)
                    continue
                raise FadrApiError(
                    "Network error communicating with Fadr API.",
                    details={"path": path, "error": type(exc).__name__},
                ) from exc

            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < self._max_retries:
                delay = 2**attempt
                _logger.warning(
                    "Retryable Fadr API response.",
                    extra={
                        "attempt": attempt + 1,
                        "status_code": response.status_code,
                        "delay_s": delay,
                        "path": path,
                    },
                )
                await asyncio.sleep(delay)
                continue

            if response.is_success:
                _logger.debug(
                    "Fadr API request succeeded.",
                    extra={"method": method, "path": path, "status_code": response.status_code},
                )
                return response.json()

            # Non-retryable error
            self._raise_for_status(response, path)

        # Unreachable — loop always returns or raises
        raise FadrApiError("Max retries exceeded.", details={"path": path})  # pragma: no cover

    def _raise_for_status(self, response: httpx.Response, path: str) -> None:
        """Map HTTP error status to a typed :class:`FadrApiError`."""
        msg = _STATUS_MESSAGES.get(
            response.status_code,
            "Fadr API returned an unexpected error.",
        )
        _logger.error(
            "Fadr API error response.",
            extra={"status_code": response.status_code, "path": path},
        )
        raise FadrApiError(
            msg,
            status_code=response.status_code,
            details={"status_code": response.status_code, "path": path},
        )
