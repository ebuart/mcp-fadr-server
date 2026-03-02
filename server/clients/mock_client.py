"""In-memory mock implementation of :class:`~server.clients.base.FadrClientBase`.

Used exclusively in tests.  The mock is configured with:

* A ``final_task`` — the fully-completed task returned once the
  ``poll_statuses`` sequence is exhausted.
* An ``assets`` dict mapping asset _id → :class:`FadrAsset` for every
  stem and MIDI asset referenced by ``final_task``.
* An optional ``poll_statuses`` list controlling intermediate statuses
  before the final task is surfaced.

Example (task completes after two "processing" polls)::

    mock = MockFadrClient(
        final_task=done_task,
        assets={"stem-1": FadrAsset(...)},
        poll_statuses=["processing", "processing"],
    )
"""

from __future__ import annotations

from collections.abc import Iterator

from server.clients.base import FadrClientBase
from server.exceptions import FadrApiError
from server.schemas.fadr_responses import (
    FadrAsset,
    FadrTask,
    FadrTaskAsset,
    FadrTaskStatus,
    FadrUploadUrlResponse,
)

_MOCK_UPLOAD_URL = "https://mock-s3.example.com/presigned-put"
_MOCK_S3_PATH = "mock/uploads/audio.mp3"
_MOCK_SOURCE_ASSET_ID = "mock-source-asset-id"
_MOCK_TASK_ID = "mock-task-id"
_DOWNLOAD_URL_TEMPLATE = "https://mock-cdn.example.com/download/{asset_id}?quality={quality}"


class MockFadrClient(FadrClientBase):
    """Deterministic in-memory Fadr client for unit and golden tests."""

    def __init__(
        self,
        final_task: FadrTask,
        assets: dict[str, FadrAsset],
        *,
        poll_statuses: list[str] | None = None,
        raise_on_upload: Exception | None = None,
        raise_on_create_task: Exception | None = None,
    ) -> None:
        """
        Args:
            final_task: The task returned once ``poll_statuses`` are exhausted.
            assets: Mapping of asset_id → FadrAsset for all stem/MIDI assets
                referenced by ``final_task.asset.stems`` and
                ``final_task.asset.midi``.
            poll_statuses: Sequence of status strings to return from
                :meth:`get_task` before surfacing ``final_task``.  If
                ``None``, the final task is returned on the first poll.
            raise_on_upload: If set, :meth:`upload_audio` raises this exception.
            raise_on_create_task: If set, :meth:`create_stem_task` raises this.
        """
        self._final_task = final_task
        self._assets = assets
        self._status_iter: Iterator[str] = iter(poll_statuses or [])
        self._raise_on_upload = raise_on_upload
        self._raise_on_create_task = raise_on_create_task

        # Counters for asserting call counts in tests
        self.upload_url_calls: int = 0
        self.upload_audio_calls: int = 0
        self.create_asset_calls: int = 0
        self.create_stem_task_calls: int = 0
        self.get_task_calls: int = 0
        self.get_asset_calls: int = 0
        self.get_download_url_calls: int = 0

    # ------------------------------------------------------------------
    # File management
    # ------------------------------------------------------------------

    async def get_upload_url(self, name: str, extension: str) -> FadrUploadUrlResponse:
        self.upload_url_calls += 1
        return FadrUploadUrlResponse(url=_MOCK_UPLOAD_URL, s3Path=_MOCK_S3_PATH)

    async def upload_audio(
        self,
        presigned_url: str,
        audio_bytes: bytes,
        mime_type: str,
    ) -> None:
        self.upload_audio_calls += 1
        if self._raise_on_upload is not None:
            raise self._raise_on_upload

    async def get_download_url(self, asset_id: str, quality: str) -> str:
        self.get_download_url_calls += 1
        if asset_id not in self._assets:
            raise FadrApiError(
                f"Asset '{asset_id}' not found.",
                status_code=404,
                details={"asset_id": asset_id},
            )
        return _DOWNLOAD_URL_TEMPLATE.format(asset_id=asset_id, quality=quality)

    # ------------------------------------------------------------------
    # Asset management
    # ------------------------------------------------------------------

    async def create_asset(
        self,
        name: str,
        extension: str,
        s3_path: str,
        group: str | None = None,
    ) -> FadrAsset:
        self.create_asset_calls += 1
        return FadrAsset.model_validate(
            {"_id": _MOCK_SOURCE_ASSET_ID, "name": name, "extension": extension}
        )

    async def get_asset(self, asset_id: str) -> FadrAsset:
        self.get_asset_calls += 1
        if asset_id not in self._assets:
            raise FadrApiError(
                f"Asset '{asset_id}' not found.",
                status_code=404,
                details={"asset_id": asset_id},
            )
        return self._assets[asset_id]

    # ------------------------------------------------------------------
    # Task management
    # ------------------------------------------------------------------

    async def create_stem_task(
        self,
        asset_id: str,
        model: str = "main",
    ) -> FadrTask:
        self.create_stem_task_calls += 1
        if self._raise_on_create_task is not None:
            raise self._raise_on_create_task
        # Return a minimal "processing" reference — just enough for the service
        # to obtain the task_id and start polling.
        return FadrTask.model_validate(
            {
                "_id": _MOCK_TASK_ID,
                "status": FadrTaskStatus(complete=False, msg="processing"),
                "asset": None,
            }
        )

    async def get_task(self, task_id: str) -> FadrTask:
        self.get_task_calls += 1
        try:
            msg = next(self._status_iter)
            # Return an in-progress task (no results yet)
            return FadrTask.model_validate(
                {
                    "_id": task_id,
                    "status": FadrTaskStatus(complete=False, msg=msg),
                    "asset": None,
                }
            )
        except StopIteration:
            return self._final_task


# ---------------------------------------------------------------------------
# Factory helpers for common test fixtures
# ---------------------------------------------------------------------------


def build_done_task(
    *,
    stem_ids: list[str],
    midi_ids: list[str],
    tempo: float = 120.0,
    key: str = "C major",
    chord_progression: object = "C,G,Am,F",
    time_signature: str | None = "4/4",
) -> FadrTask:
    """Build a fully-completed FadrTask fixture."""
    from server.schemas.fadr_responses import FadrMetaData

    meta = FadrMetaData(
        tempo=tempo,
        key=key,
        chordProgression=chord_progression,
        timeSignature=time_signature,
    )
    task_asset = FadrTaskAsset.model_validate(
        {
            "_id": _MOCK_SOURCE_ASSET_ID,
            "name": "test-song",
            "extension": "mp3",
            "stems": stem_ids,
            "midi": midi_ids,
            "metaData": meta.model_dump(by_alias=True),
        }
    )
    return FadrTask.model_validate(
        {
            "_id": _MOCK_TASK_ID,
            "status": FadrTaskStatus(complete=True, msg="done", progress=100),
            "asset": task_asset,
        }
    )


def build_asset(asset_id: str, name: str, extension: str = "mp3") -> FadrAsset:
    """Build a minimal FadrAsset fixture."""
    return FadrAsset.model_validate({"_id": asset_id, "name": name, "extension": extension})
