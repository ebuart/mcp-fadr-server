"""Unit tests for FadrHttpClient.

Uses ``unittest.mock`` to inject a fake ``httpx.AsyncClient`` so no real
network calls are made.  Tests cover happy paths, error code mapping, retry
behaviour, and the security property that the API key never appears in
exception messages.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from server.clients.fadr_client import FadrHttpClient
from server.exceptions import FadrApiError
from server.utils.config import Settings

_TEST_KEY = "test-fadr-key-abcdef"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = dict(
        fadr_api_key=_TEST_KEY,
        fadr_base_url="https://api.fadr.com",
        fadr_timeout_s=5.0,
        fadr_max_retries=0,  # disable retries in most tests
        fadr_poll_interval_s=0.0,
        fadr_poll_timeout_s=1.0,
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _mock_response(
    status_code: int = 200,
    json_data: Any = None,
    *,
    is_success: bool | None = None,
) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.is_success = is_success if is_success is not None else (200 <= status_code < 300)
    resp.json.return_value = json_data or {}
    return resp


def _make_client(mock_response: MagicMock, *, max_retries: int = 0) -> FadrHttpClient:
    settings = _make_settings(fadr_max_retries=max_retries)
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.request.return_value = mock_response
    mock_http.put.return_value = mock_response
    return FadrHttpClient(settings, _http_client=mock_http)


# ---------------------------------------------------------------------------
# get_upload_url
# ---------------------------------------------------------------------------


class TestGetUploadUrl:
    async def test_success_returns_upload_url_response(self) -> None:
        resp = _mock_response(
            json_data={"url": "https://s3.example.com/put", "s3Path": "mock/path"}
        )
        client = _make_client(resp)
        result = await client.get_upload_url("song", "mp3")
        assert result.url == "https://s3.example.com/put"
        assert result.s3_path == "mock/path"

    async def test_sends_correct_json_body(self) -> None:
        resp = _mock_response(json_data={"url": "https://x.com", "s3Path": "p"})
        settings = _make_settings()
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.request.return_value = resp
        client = FadrHttpClient(settings, _http_client=mock_http)
        await client.get_upload_url("my-track", "wav")
        call_kwargs = mock_http.request.call_args
        assert call_kwargs.kwargs["json"] == {"name": "my-track", "extension": "wav"}

    async def test_401_raises_fadr_api_error(self) -> None:
        resp = _mock_response(status_code=401)
        client = _make_client(resp)
        with pytest.raises(FadrApiError) as exc_info:
            await client.get_upload_url("song", "mp3")
        assert exc_info.value.status_code == 401
        assert exc_info.value.error_code == "DOWNSTREAM_ERROR"

    async def test_402_raises_fadr_api_error(self) -> None:
        resp = _mock_response(status_code=402)
        client = _make_client(resp)
        with pytest.raises(FadrApiError) as exc_info:
            await client.get_upload_url("song", "mp3")
        assert exc_info.value.status_code == 402
        assert "billing" in exc_info.value.message.lower()

    async def test_404_raises_fadr_api_error(self) -> None:
        resp = _mock_response(status_code=404)
        client = _make_client(resp)
        with pytest.raises(FadrApiError) as exc_info:
            await client.get_upload_url("song", "mp3")
        assert exc_info.value.status_code == 404

    async def test_500_raises_fadr_api_error(self) -> None:
        resp = _mock_response(status_code=500)
        client = _make_client(resp)
        with pytest.raises(FadrApiError) as exc_info:
            await client.get_upload_url("song", "mp3")
        assert exc_info.value.status_code == 500

    async def test_api_key_not_in_exception_message(self) -> None:
        resp = _mock_response(status_code=401)
        client = _make_client(resp)
        with pytest.raises(FadrApiError) as exc_info:
            await client.get_upload_url("song", "mp3")
        assert _TEST_KEY not in exc_info.value.message
        if exc_info.value.details:
            assert _TEST_KEY not in str(exc_info.value.details)

    async def test_bearer_token_in_request_headers(self) -> None:
        resp = _mock_response(json_data={"url": "https://x.com", "s3Path": "p"})
        settings = _make_settings()
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.request.return_value = resp
        client = FadrHttpClient(settings, _http_client=mock_http)
        await client.get_upload_url("song", "mp3")
        headers = mock_http.request.call_args.kwargs["headers"]
        assert headers["Authorization"] == f"Bearer {_TEST_KEY}"


# ---------------------------------------------------------------------------
# upload_audio
# ---------------------------------------------------------------------------


class TestUploadAudio:
    async def test_success_no_return(self) -> None:
        resp = _mock_response(status_code=200)
        settings = _make_settings()
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.put.return_value = resp
        client = FadrHttpClient(settings, _http_client=mock_http)
        # Should not raise
        await client.upload_audio("https://s3.example.com/put", b"audio", "audio/mpeg")

    async def test_put_failure_raises_fadr_api_error(self) -> None:
        resp = _mock_response(status_code=403)
        settings = _make_settings()
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.put.return_value = resp
        client = FadrHttpClient(settings, _http_client=mock_http)
        with pytest.raises(FadrApiError) as exc_info:
            await client.upload_audio("https://s3.example.com/put", b"audio", "audio/mpeg")
        assert exc_info.value.status_code == 403

    async def test_network_error_raises_fadr_api_error(self) -> None:
        settings = _make_settings()
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.put.side_effect = httpx.ConnectError("connection refused")
        client = FadrHttpClient(settings, _http_client=mock_http)
        with pytest.raises(FadrApiError) as exc_info:
            await client.upload_audio("https://s3.example.com/put", b"audio", "audio/mpeg")
        assert exc_info.value.error_code == "DOWNSTREAM_ERROR"


# ---------------------------------------------------------------------------
# get_download_url
# ---------------------------------------------------------------------------


class TestGetDownloadUrl:
    async def test_dict_response(self) -> None:
        resp = _mock_response(json_data={"url": "https://cdn.example.com/file.mp3"})
        client = _make_client(resp)
        url = await client.get_download_url("asset-123", "hqPreview")
        assert url == "https://cdn.example.com/file.mp3"

    async def test_string_response(self) -> None:
        resp = _mock_response(json_data="https://cdn.example.com/file.mp3")
        client = _make_client(resp)
        url = await client.get_download_url("asset-123", "hqPreview")
        assert url == "https://cdn.example.com/file.mp3"

    async def test_unexpected_response_raises(self) -> None:
        resp = _mock_response(json_data={"something": "unexpected"})
        client = _make_client(resp)
        with pytest.raises(FadrApiError):
            await client.get_download_url("asset-123", "hqPreview")


# ---------------------------------------------------------------------------
# create_asset
# ---------------------------------------------------------------------------


class TestCreateAsset:
    async def test_returns_fadr_asset(self) -> None:
        resp = _mock_response(
            json_data={"asset": {"_id": "asset-abc", "name": "track", "extension": "mp3"}}
        )
        client = _make_client(resp)
        asset = await client.create_asset("track", "mp3", "mock/s3/path")
        assert asset.asset_id == "asset-abc"
        assert asset.name == "track"

    async def test_group_included_when_provided(self) -> None:
        resp = _mock_response(json_data={"asset": {"_id": "a1", "name": "t", "extension": "mp3"}})
        settings = _make_settings()
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.request.return_value = resp
        client = FadrHttpClient(settings, _http_client=mock_http)
        await client.create_asset("track", "mp3", "path", group="my-group")
        body = mock_http.request.call_args.kwargs["json"]
        assert body["group"] == "my-group"


# ---------------------------------------------------------------------------
# get_asset
# ---------------------------------------------------------------------------


class TestGetAsset:
    async def test_returns_fadr_asset(self) -> None:
        resp = _mock_response(
            json_data={"asset": {"_id": "asset-xyz", "name": "vocals", "extension": "mp3"}}
        )
        client = _make_client(resp)
        asset = await client.get_asset("asset-xyz")
        assert asset.asset_id == "asset-xyz"
        assert asset.name == "vocals"


# ---------------------------------------------------------------------------
# create_stem_task
# ---------------------------------------------------------------------------


class TestCreateStemTask:
    async def test_returns_fadr_task(self) -> None:
        task_payload = {
            "_id": "task-001", "status": {"msg": "processing", "progress": 0, "complete": False}
        }
        resp = _mock_response(json_data={"msg": "ok", "task": task_payload})
        client = _make_client(resp)
        task = await client.create_stem_task("asset-abc")
        assert task.task_id == "task-001"
        assert task.status.complete is False
        assert task.status.msg == "processing"

    async def test_sends_correct_body(self) -> None:
        task_payload = {
            "_id": "task-002", "status": {"msg": "processing", "progress": 0, "complete": False}
        }
        resp = _mock_response(json_data={"msg": "ok", "task": task_payload})
        settings = _make_settings()
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.request.return_value = resp
        client = FadrHttpClient(settings, _http_client=mock_http)
        await client.create_stem_task("asset-abc", model="main")
        body = mock_http.request.call_args.kwargs["json"]
        assert body == {"_id": "asset-abc", "model": "main"}


# ---------------------------------------------------------------------------
# get_task
# ---------------------------------------------------------------------------


class TestGetTask:
    async def test_returns_fadr_task(self) -> None:
        from server.schemas.fadr_responses import FadrTaskAsset
        resp = _mock_response(
            json_data={
                "task": {
                    "_id": "task-999",
                    "status": {"msg": "done", "progress": 100, "complete": True},
                    "asset": {
                        "_id": "asset-999",
                        "name": "track",
                        "extension": "mp3",
                        "stems": ["s1"],
                        "midi": ["m1"],
                        "metaData": {"tempo": 120.0, "key": "C major"},
                    },
                }
            }
        )
        client = _make_client(resp)
        task = await client.get_task("task-999")
        assert task.task_id == "task-999"
        assert task.status.complete is True
        assert isinstance(task.asset, FadrTaskAsset)
        assert task.asset.stems == ["s1"]

    async def test_404_raises_fadr_api_error(self) -> None:
        resp = _mock_response(status_code=404)
        client = _make_client(resp)
        with pytest.raises(FadrApiError) as exc_info:
            await client.get_task("no-such-task")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


class TestRetryBehaviour:
    async def test_retries_on_503_then_succeeds(self) -> None:
        resp_503 = _mock_response(status_code=503)
        resp_200 = _mock_response(json_data={"url": "https://x.com", "s3Path": "p"})

        settings = _make_settings(fadr_max_retries=2)
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        # First call returns 503, second returns 200
        mock_http.request.side_effect = [resp_503, resp_200]
        client = FadrHttpClient(settings, _http_client=mock_http)

        result = await client.get_upload_url("song", "mp3")
        assert mock_http.request.call_count == 2
        assert result.url == "https://x.com"

    async def test_network_error_then_succeeds(self) -> None:
        task_payload = {
            "_id": "t-1", "status": {"msg": "processing", "progress": 0, "complete": False}
        }
        resp_200 = _mock_response(json_data={"msg": "ok", "task": task_payload})
        settings = _make_settings(fadr_max_retries=2)
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.request.side_effect = [
            httpx.ConnectError("timeout"),
            resp_200,
        ]
        client = FadrHttpClient(settings, _http_client=mock_http)
        task = await client.create_stem_task("asset-id")
        assert mock_http.request.call_count == 2
        assert task.task_id == "t-1"

    async def test_all_retries_exhausted_raises(self) -> None:
        resp_503 = _mock_response(status_code=503)
        settings = _make_settings(fadr_max_retries=1)
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.request.side_effect = [resp_503, resp_503]
        client = FadrHttpClient(settings, _http_client=mock_http)
        with pytest.raises(FadrApiError):
            await client.get_upload_url("song", "mp3")
        assert mock_http.request.call_count == 2

    async def test_non_retryable_401_raises_immediately(self) -> None:
        resp_401 = _mock_response(status_code=401)
        settings = _make_settings(fadr_max_retries=3)
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.request.return_value = resp_401
        client = FadrHttpClient(settings, _http_client=mock_http)
        with pytest.raises(FadrApiError):
            await client.get_upload_url("song", "mp3")
        # Should not retry on 401
        assert mock_http.request.call_count == 1
