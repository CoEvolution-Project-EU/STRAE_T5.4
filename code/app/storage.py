import json
import logging
from typing import Dict, Protocol

import httpx
from asyncer import asyncify
from fastapi import Request
from fastapi.encoders import jsonable_encoder

from app.auth import OrchestratorAuth
from app.config import settings
from app.db import MinioConnectionError, MinioDB, MinioOperationError
from app.models.aimbom import AIMBOM

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Base storage error."""


class StorageConnectionError(StorageError):
    """External system unavailable."""


class StorageOperationError(StorageError):
    """Generic failure during storage operation."""


class StorageAuthError(StorageError):
    """Authentication failure."""


class StorageInterface(Protocol):
    async def get_reports_for_model(
        self,
        model_uuid: str,
        model_version: str,
        reports_metadata: dict[str, dict] | None,
    ) -> Dict: ...

    async def save_aimbom(
        self, model_uuid: str, model_version: str, aimbom: AIMBOM
    ) -> None: ...


class MinioStorage(StorageInterface):
    def __init__(self, minio: MinioDB):
        self.minio = minio

    async def get_reports_for_model(
        self,
        model_uuid: str,
        model_version: str,
        reports_metadata: dict[str, dict] | None,
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
    def __init__(
        self,
        client: httpx.AsyncClient,
        auth: OrchestratorAuth,
    ):
        self.client = client
        self.auth = auth

    async def get_reports_for_model(
        self,
        model_uuid: str,
        model_version: str,
        reports_metadata: dict[str, dict] | None,
    ) -> Dict:
        logger.info(
            "Retrieving reports for model_uuid=%s model_version=%s",
            model_uuid,
            model_version,
        )

        reports = {}

        try:
            # TODO: Retrieve reports concurrently
            for report_type, metadata in reports_metadata.items():
                print(f"Report metadata for {report_type}: {metadata}")

                response = await self.client.get(
                    metadata["download_url"],
                )
                response.raise_for_status()

                reports[metadata["filename"].split("-")[-1].replace(".json", "")] = (
                    response.json()
                )
            return reports
        except httpx.RequestError as e:
            logger.error(
                "Connection error while retrieving reports",
                exc_info=True,
            )

            raise StorageConnectionError(str(e)) from e

        except httpx.HTTPStatusError as e:
            logger.error(
                "HTTP error while retrieving reports status_code=%s",
                e.response.status_code,
                exc_info=True,
            )

            raise StorageOperationError(
                f"Orchestrator returned {e.response.status_code}"
            ) from e

        except Exception as e:
            logger.error(
                "Unexpected error while retrieving reports",
                exc_info=True,
            )

            raise StorageOperationError(str(e)) from e

    async def save_aimbom(
        self,
        model_uuid: str,
        model_version: str,
        aimbom: AIMBOM,
    ) -> None:

        try:
            token = await self.auth.get_token()
            headers = {"Authorization": f"Bearer {token}"}
        except Exception as e:
            logger.error(
                "Authentication error while saving AIMBOM",
                exc_info=True,
            )
            raise StorageAuthError("Failed to authenticate with orchestrator") from e

        try:
            logger.info(
                "Uploading AIMBOM for model_uuid=%s model_version=%s",
                model_uuid,
                model_version,
            )

            # Convert AIMBOM to JSON bytes
            aimbom_json = json.dumps(
                jsonable_encoder(aimbom, exclude_none=True),
            )

            filename = f"aimbom-{model_uuid}-{model_version}.json"

            files = [
                (
                    "files",
                    (
                        filename,
                        aimbom_json.encode("utf-8"),
                        "application/vnd.cyclonedx+json",
                    ),
                )
            ]

            data = {
                "pool": "SAP",
                "bucket": "ai-mbom",
                "model_uuid": model_uuid,
                "version": model_version,
                # "tags": "aimbom,generated",
            }

            response = await self.client.post(
                "/files/upload",
                headers=headers,
                files=files,
                data=data,
            )

            response.raise_for_status()

            logger.info(
                "AIMBOM uploaded successfully model_uuid=%s model_version=%s",
                model_uuid,
                model_version,
            )

        except httpx.RequestError as e:
            logger.error(
                "Connection error while uploading AIMBOM",
                exc_info=True,
            )

            raise StorageConnectionError(str(e)) from e

        except httpx.HTTPStatusError as e:
            logger.error(
                "Upload failed with status_code=%s response=%s",
                e.response.status_code,
                e.response.text,
                exc_info=True,
            )

            raise StorageOperationError(
                f"Orchestrator returned {e.response.status_code}"
            ) from e

        except Exception as e:
            logger.error(
                "Unexpected error while uploading AIMBOM",
                exc_info=True,
            )

            raise StorageOperationError(str(e)) from e

    async def close(self):
        await self.client.aclose()


async def get_storage(request: Request) -> StorageInterface:
    return request.app.state.storage
