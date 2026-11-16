import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Dict, Tuple

from fastapi import Request

from app.models.aimbom import AIMBOM
from app.models.requests import GenerationMetadata
from app.models.storage import UploadReportMetadata

logger = logging.getLogger(__name__)

# Content type of uploaded AIMBOMs. Other files are uploaded as plain JSON.
CYCLONEDX_CONTENT_TYPE = "application/vnd.cyclonedx+json"


class StorageError(Exception):
    """Base storage error."""


class StorageConnectionError(StorageError):
    """External system unavailable."""


class StorageOperationError(StorageError):
    """Generic failure during storage operation."""


class StorageConflictError(StorageOperationError):
    """The file already exists in storage (e.g. the original was already signed)."""


class StorageBadRequestError(StorageOperationError):
    """The storage backend rejected the request as invalid."""


class StorageNotFoundError(StorageOperationError):
    """The requested file does not exist in storage."""


class StorageInvalidFileError(StorageOperationError):
    """Retrieved file is not valid JSON."""


class StorageAuthError(StorageError):
    """Authentication failure."""


class StorageClient(ABC):
    @abstractmethod
    async def get_file_from_url(self, download_url: str) -> Dict: ...

    @abstractmethod
    async def save_file(
        self,
        file: Dict,
        filename: str,
        upload_report_metadata: UploadReportMetadata,
    ): ...

    @abstractmethod
    async def get_reports_for_model(
        self,
        generation_metadata: object,
    ) -> Dict: ...

    @abstractmethod
    async def save_aimbom(
        self,
        model_uuid: str,
        model_version: str,
        aimbom: AIMBOM,
    ): ...

    @abstractmethod
    async def get_aimbom(
        self,
        model_uuid: str,
        model_version: str,
    ) -> Tuple[Dict, Dict[str, Dict]]: ...


async def get_file_if_exists(client: StorageClient, download_url: str) -> Dict | None:
    """Download a file, returning `None` if it does not exist.

    Args:
        client: The storage client to download with.
        download_url: The download URL of the file.

    Returns:
        The parsed file, or `None` if storage has no such file.
    """

    try:
        return await client.get_file_from_url(download_url)
    except StorageNotFoundError:
        return None


async def get_reports_concurrently(
    client: StorageClient, generation_metadata: GenerationMetadata
) -> Dict:
    """Download every report of a generation request concurrently.

    Report types without metadata are left out. If any download fails, its
    error is raised (the first one, if several fail).

    Args:
        client: The storage client to download with.
        generation_metadata: A `GenerationMetadata` instance containing the
            download URL of each report.

    Returns:
        Mapping of report type keys to parsed JSON report objects.
    """

    download_urls = {}
    for report_type, metadata in generation_metadata.reports.model_dump().items():
        if metadata is None:
            logger.warning("No metadata for report type=%s", report_type)
            continue
        logger.debug("Downloading report type=%s", report_type)
        download_urls[report_type] = metadata["download_url"]

    downloaded = await asyncio.gather(
        *(client.get_file_from_url(download_url=url) for url in download_urls.values())
    )
    # `gather` keeps the order of its arguments, so the reports line up with
    # their report types.
    return dict(zip(download_urls, downloaded))


async def get_storage_client(request: Request) -> StorageClient:
    """FastAPI dependency to retrieve the configured storage implementation.

    Args:
        request: FastAPI `Request` whose `app.state.client` contains the implementation.

    Returns:
        The configured `StorageClient` instance stored on the application.
    """

    return request.app.state.client
