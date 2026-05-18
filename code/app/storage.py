import json
import logging
from typing import Dict, Protocol

import httpx
from asyncer import asyncify
from fastapi import Request
from fastapi.encoders import jsonable_encoder

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
    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=settings.ORCHESTRATOR_BASE_URL,
            timeout=10.0,
        )

        token = "eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICIxckUtem5VbU9MT3JpYkZxT3ViQmk1WmxxWnhoelZVVVJLV1F1TEFPNHlRIn0.eyJleHAiOjE3NzkwOTkzMzMsImlhdCI6MTc3OTA5NTczMywianRpIjoiY2YyOTIwZDAtM2EwOC00MWI2LTlkZWYtOWQxNDRkNTY2OTY1IiwiaXNzIjoiaHR0cHM6Ly9hZWdpcy5jb2V2b2x1dGlvbi1wcm9qZWN0LmV1L3JlYWxtcy9jb2V2b2x1dGlvbiIsImF1ZCI6ImFjY291bnQiLCJzdWIiOiJmOWE4M2E5MC1iYmE0LTRlMmQtOWQ2ZC1hMTdlNmEwMjc1Y2UiLCJ0eXAiOiJCZWFyZXIiLCJhenAiOiJjb2V2b2x1dGlvbiIsInNpZCI6IjgzYTQzYWQ4LTA3YWYtNDU0ZC1iM2E5LWY5ODk4ODMzNDRlYyIsImFjciI6IjEiLCJhbGxvd2VkLW9yaWdpbnMiOlsiaHR0cDovL2xvY2FsaG9zdDo0MjAwIl0sInJlYWxtX2FjY2VzcyI6eyJyb2xlcyI6WyJkZWZhdWx0LXJvbGVzLWNvZXZvbHV0aW9uIiwib2ZmbGluZV9hY2Nlc3MiLCJ1bWFfYXV0aG9yaXphdGlvbiJdfSwicmVzb3VyY2VfYWNjZXNzIjp7ImFjY291bnQiOnsicm9sZXMiOlsibWFuYWdlLWFjY291bnQiLCJtYW5hZ2UtYWNjb3VudC1saW5rcyIsInZpZXctcHJvZmlsZSJdfX0sInNjb3BlIjoicHJvZmlsZSBlbWFpbCIsImVtYWlsX3ZlcmlmaWVkIjpmYWxzZSwibmFtZSI6ImNvZXZvbHV0aW9uIGNvZXZvbHV0aW9uIiwicHJlZmVycmVkX3VzZXJuYW1lIjoiY29ldm9sdXRpb25fdXNlciIsImdpdmVuX25hbWUiOiJjb2V2b2x1dGlvbiIsImZhbWlseV9uYW1lIjoiY29ldm9sdXRpb24iLCJlbWFpbCI6ImMua3JvdXRpQGFlZ2lzcmVzZWFyY2guZXUifQ.QRu-sC0IzO_ER6n0F402cy6K1qwU8dnklklt9PdUVpx87oEfFuuP7QDmtuMPLRSHgxbsxhui6e2kSvxr8xRfpcYFhBmUqEXgOlkVmtX4O7VjY_iSKbd1uRwYVGhu9_7Enwd5qY7LJXu0R-yHp3pDUCSJ8Du5o50hpLTIQ48A144Ui8H1gXNRW01s8xmQ3fJfAlwpsdUItbnJpIdKmbsn3VIsLXkVeOySJPOrqjXgbPaAtxK6SKDi_AlHrqK0wFkC4msX5LYo9P6ScUNWNGP_8J4TpkfcoZJwahmircXg2MetJe1TYEOKyiTP34TCteDpZSakLb9n9-UJWjQJHn2rHA"

        self.client.headers.update({"Authorization": f"Bearer {token}"})

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
            logger.info(
                "Uploading AIMBOM for model_uuid=%s model_version=%s",
                model_uuid,
                model_version,
            )

            # Convert AIMBOM to JSON bytes
            aimbom_json = json.dumps(
                jsonable_encoder(aimbom, exclude_none=True),
                indent=2,
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
