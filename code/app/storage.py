from typing import Dict, Protocol

import httpx
from asyncer import asyncify
from fastapi import Request
from fastapi.encoders import jsonable_encoder

from app.config import settings
from app.db import MinioConnectionError, MinioDB, MinioOperationError
from app.models.aimbom import AIMBOM


class StorageError(Exception):
    """Base storage error."""


class StorageConnectionError(StorageError):
    """External system unavailable."""


class StorageOperationError(StorageError):
    """Generic failure during storage operation."""


class StorageInterface(Protocol):
    async def get_reports_for_model(
        self, model_uuid: str, model_version: str, report_urls: list[str] | None
    ) -> Dict: ...

    async def save_aimbom(
        self, model_uuid: str, model_version: str, aimbom: AIMBOM
    ) -> None: ...


class MinioStorage(StorageInterface):
    def __init__(self, minio: MinioDB):
        self.minio = minio

    async def get_reports_for_model(
        self, model_uuid: str, model_version: str, report_urls: list[str] | None
    ) -> Dict:
        try:
            return await asyncify(self.minio.get_reports_for_model)(
                bucket_name=settings.REPORTS_BUCKET,
                model_uuid=model_uuid,
                model_version=model_version,
            )
        except MinioConnectionError as e:
            raise StorageConnectionError(str(e)) from e
        except MinioOperationError as e:
            raise StorageOperationError(str(e)) from e

    async def save_aimbom(
        self, model_uuid: str, model_version: str, aimbom: AIMBOM
    ) -> None:
        try:
            await asyncify(self.minio.upload_json)(
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

    async def get_reports_for_model(
        self, model_uuid: str, model_version: str, report_urls: list[str] | None
    ) -> Dict:
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


async def get_storage(request: Request) -> StorageInterface:
    return request.app.state.storage
