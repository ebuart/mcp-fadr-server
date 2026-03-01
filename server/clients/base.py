"""Abstract base class for the Fadr API HTTP client.

Defining an ABC makes the client fully mockable: tests inject a
:class:`MockFadrClient` while production wires in the real ``FadrHttpClient``
(implemented in Phase 3).

All methods are ``async``; the real client uses ``httpx.AsyncClient``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from server.schemas.fadr_responses import (
    FadrAsset,
    FadrTask,
    FadrUploadUrlResponse,
)


class FadrClientBase(ABC):
    """Interface contract for all Fadr API interactions."""

    # ------------------------------------------------------------------
    # File management
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_upload_url(self, name: str, extension: str) -> FadrUploadUrlResponse:
        """Request a presigned S3 upload URL.

        Fadr endpoint: ``POST /assets/upload2``

        Args:
            name: Base name for the file (without extension).
            extension: File extension without a leading dot, e.g. ``"mp3"``.

        Returns:
            A :class:`~server.schemas.fadr_responses.FadrUploadUrlResponse`
            containing the presigned PUT URL and the ``s3Path``.
        """

    @abstractmethod
    async def upload_audio(
        self,
        presigned_url: str,
        audio_bytes: bytes,
        mime_type: str,
    ) -> None:
        """Upload raw audio bytes to the presigned S3 URL.

        Fadr requires the ``Content-Type`` header on the PUT request.

        Args:
            presigned_url: The presigned URL returned by :meth:`get_upload_url`.
            audio_bytes: Raw audio file content.
            mime_type: MIME type of the audio, e.g. ``"audio/mp3"``.
        """

    @abstractmethod
    async def get_download_url(self, asset_id: str, quality: str) -> str:
        """Obtain a presigned download URL for an asset.

        Fadr endpoint: ``GET /assets/download/:_id/:type``

        Args:
            asset_id: The Fadr ``_id`` of the asset to download.
            quality: Download type — one of ``"preview"``, ``"hqPreview"``,
                ``"download"``.

        Returns:
            A presigned URL string pointing to the asset file.
        """

    # ------------------------------------------------------------------
    # Asset management
    # ------------------------------------------------------------------

    @abstractmethod
    async def create_asset(
        self,
        name: str,
        extension: str,
        s3_path: str,
        group: str | None = None,
    ) -> FadrAsset:
        """Register an uploaded file as a Fadr asset.

        Fadr endpoint: ``POST /assets``

        Args:
            name: Display name of the asset.
            extension: File extension without a leading dot.
            s3_path: The ``s3Path`` value returned by :meth:`get_upload_url`.
            group: Optional asset group identifier.

        Returns:
            The created :class:`~server.schemas.fadr_responses.FadrAsset`.
        """

    @abstractmethod
    async def get_asset(self, asset_id: str) -> FadrAsset:
        """Retrieve asset metadata by ID.

        Fadr endpoint: ``GET /assets/:_id``

        Used to resolve stem / MIDI asset names after a task completes.
        """

    # ------------------------------------------------------------------
    # Task management
    # ------------------------------------------------------------------

    @abstractmethod
    async def create_stem_task(
        self,
        asset_id: str,
        model: str = "main",
    ) -> FadrTask:
        """Start a stem-separation task on the given asset.

        Fadr endpoint: ``POST /assets/analyze/stem``

        The ``"main"`` model produces stems, MIDI, key, tempo, and chord
        progression.  Returns immediately with a task in ``"processing"``
        status; callers must poll :meth:`get_task` until complete.

        Args:
            asset_id: The Fadr ``_id`` of the source audio asset.
            model: Separation model to use (default ``"main"``).
        """

    @abstractmethod
    async def get_task(self, task_id: str) -> FadrTask:
        """Fetch the current state of a task.

        Fadr endpoint: ``GET /tasks/:_id``

        Poll this endpoint every ~5 seconds until ``task.status`` is
        ``"done"`` or ``"failed"``.
        """
