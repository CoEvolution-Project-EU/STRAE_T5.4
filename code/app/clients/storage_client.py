from abc import ABC, abstractmethod
from typing import Dict

from fastapi import Request

from app.models.aimbom import AIMBOM


class StorageError(Exception):
    """Base storage error."""


class StorageConnectionError(StorageError):
    """External system unavailable."""


class StorageOperationError(StorageError):
    """Generic failure during storage operation."""


class StorageAuthError(StorageError):
    """Authentication failure."""


class StorageClient(ABC):
    @abstractmethod
    async def get_file_from_url(self, download_url: str) -> Dict: ...

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


async def get_storage_client(request: Request) -> StorageClient:
    """FastAPI dependency to retrieve the configured storage implementation.

    Args:
        request: FastAPI `Request` whose `app.state.client` contains the implementation.

    Returns:
        The configured `StorageClient` instance stored on the application.
    """

    return request.app.state.client
