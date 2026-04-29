from functools import lru_cache
from typing import Dict

import httpx
from fastapi import Depends
from fastapi.encoders import jsonable_encoder

from app.config import Environment, settings
from app.db import MinioConnectionError, MinioDB, MinioOperationError, get_minio_client
from app.models.aimbom import AIMBOM


class StorageError(Exception):
    """Base storage error."""


class StorageConnectionError(StorageError):
    """External system unavailable."""


class StorageOperationError(StorageError):
    """Generic failure during storage operation."""


class StorageInterface:
    async def get_reports_for_model(self, model_uuid: str, model_version: str) -> Dict:
        raise NotImplementedError

    async def save_aimbom(
        self, model_uuid: str, model_version: str, aimbom: AIMBOM
    ) -> None:
        raise NotImplementedError


class MinioStorage(StorageInterface):
    def __init__(self, minio: MinioDB):
        self.minio = minio

    # TODO: Use asyncer to make these methods async without blocking the event loop
    async def get_reports_for_model(self, model_uuid: str, model_version: str) -> Dict:
        try:
            return self.minio.get_reports_for_model(
                settings.REPORTS_BUCKET, model_uuid, model_version
            )
        except MinioConnectionError as e:
            raise StorageConnectionError(str(e)) from e
        except MinioOperationError as e:
            raise StorageOperationError(str(e)) from e

    async def save_aimbom(
        self, model_uuid: str, model_version: str, aimbom: AIMBOM
    ) -> None:
        try:
            self.minio.upload_json(
                bucket_name=settings.AIMBOMS_BUCKET,
                object_name=f"{model_uuid}/{model_version}/{aimbom.serial_number}.json",
                data=jsonable_encoder(aimbom, exclude_none=True),
            )
        except MinioConnectionError as e:
            raise StorageConnectionError(str(e)) from e
        except MinioOperationError as e:
            raise StorageOperationError(str(e)) from e


class OrchestratorStorage(StorageInterface):
    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=settings.ORCHESTRATOR_URL,
            timeout=10.0,
        )

    async def get_reports_for_model(self, model_uuid: str, model_version: str) -> Dict:
        try:
            response = await self.client.get(
                "/orch/get-reports",
                params={"model_uuid": model_uuid, "model_version": model_version},
            )
            response.raise_for_status()

            return response.json()
        except httpx.RequestError as e:
            raise StorageConnectionError(str(e)) from e
        except httpx.HTTPStatusError as e:
            raise StorageOperationError(
                f"Orchestrator returned {e.response.status_code}"
            ) from e

    async def save_aimbom(
        self, model_uuid: str, model_version: str, aimbom: AIMBOM
    ) -> None:
        try:
            response = await self.client.post(
                "/orch/aimbom",
                json={
                    "model_uuid": model_uuid,
                    "model_version": model_version,
                    "aimbom": jsonable_encoder(aimbom, exclude_none=True),
                },
            )
            response.raise_for_status()

        except httpx.RequestError as e:
            raise StorageConnectionError(str(e)) from e
        except httpx.HTTPStatusError as e:
            raise StorageOperationError(
                f"Orchestrator returned {e.response.status_code}"
            ) from e

    async def close(self):
        await self.client.aclose()


@lru_cache
def get_storage(minio: MinioDB = Depends(get_minio_client)):
    if settings.ENVIRONMENT == Environment.prod:
        return OrchestratorStorage()
    return MinioStorage(minio)
