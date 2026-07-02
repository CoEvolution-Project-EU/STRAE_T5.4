from abc import ABC, abstractmethod
from typing import Dict

from app.models.aimbom import AIMBOM
from app.utils.utils import AIMBOMTier
from fastapi import Request


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
    async def get_reports_for_model(
        model_uuid: str,
        model_version: str,
        generation_metadata: object,
    ): ...

    @abstractmethod
    async def save_aimbom(
        model_uuid: str,
        model_version: str,
        tiered_aimbom: Dict[AIMBOMTier, AIMBOM],
    ): ...


async def get_storage_client(request: Request) -> StorageClient:
    """FastAPI dependency to retrieve the configured storage implementation.

    Args:
        request: FastAPI `Request` whose `app.state.client` contains the implementation.

    Returns:
        The configured `StorageClient` instance stored on the application.
    """

    return request.app.state.client
