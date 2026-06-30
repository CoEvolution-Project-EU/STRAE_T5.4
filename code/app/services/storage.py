import json
import logging
from typing import Dict, Protocol

import httpx
from asyncer import asyncify
from fastapi import Request
from fastapi.encoders import jsonable_encoder

from app.core.auth import OrchestratorAuth
from app.core.config import settings
from app.db.db import MinioConnectionError, MinioDB, MinioOperationError
from app.models.aimbom import AIMBOM
from app.models.requests import ReportsMetadata
from app.utils.utils import AIMBOMTier, uuid_from_serial_number

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
        self,
        model_uuid: str,
        model_version: str,
        tiered_aimbom: Dict[AIMBOMTier, AIMBOM],
    ) -> None: ...


class MinioStorage(StorageInterface):
    def __init__(self, minio: MinioDB):
        """Initialize MinIO-backed storage adapter.

        Args:
            minio: A `MinioDB` client used for direct MinIO operations.

        Returns:
            None
        """

        self.minio = minio

    async def get_reports_for_model(
        self,
        model_uuid: str,
        model_version: str,
        reports_metadata: ReportsMetadata | None,
    ) -> Dict:
        """Retrieve reports for a given model/version from MinIO.

        Args:
            model_uuid: Model UUID used as object prefix.
            model_version: Model version used as object prefix.
            reports_metadata: Not used for MinIO backend; present for API compatibility.

        Returns:
            Mapping of report name to parsed report JSON.
        """

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
        self,
        model_uuid: str,
        model_version: str,
        tiered_aimbom: Dict[AIMBOMTier, AIMBOM],
    ) -> None:
        """Save tiered AIMBOM JSON documents into MinIO.

        Args:
            model_uuid: Model UUID to associate with uploaded objects.
            model_version: Model version to associate with uploaded objects.
            tiered_aimbom: Mapping of `AIMBOMTier` to `AIMBOM` instances.

        Returns:
            None

        Raises:
            StorageConnectionError: When MinIO is unreachable.
            StorageOperationError: When MinIO operations fail.
        """

        try:
            for tier, aimbom in tiered_aimbom.items():
                logger.debug(
                    "Saving AIMBOM tier %s to bucket for model_uuid=%s, model_version=%s, serial_number=%s",
                    tier.value,
                    model_uuid,
                    model_version,
                    aimbom.serial_number,
                )

                await asyncify(self.minio.upload_json)(
                    bucket_name=settings.AIMBOMS_BUCKET,
                    object_name=f"{model_uuid}/{model_version}/{uuid_from_serial_number(aimbom.serial_number)}-{tier.value}.json",
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
        """Initialize orchestrator-backed storage adapter.

        Args:
            client: An `httpx.AsyncClient` configured to talk to the orchestrator API.
            auth: An `OrchestratorAuth` instance used to obtain auth tokens.

        Returns:
            None
        """

        self.client = client
        self.auth = auth

    async def get_reports_for_model(
        self,
        model_uuid: str,
        model_version: str,
        reports_metadata: ReportsMetadata | None,
    ) -> Dict:
        """Retrieve reports from the orchestrator using provided metadata.

        Args:
            model_uuid: Model UUID used for logging/context only.
            model_version: Model version used for logging/context only.
            reports_metadata: A `ReportsMetadata` instance containing download URLs.

        Returns:
            Mapping of report type keys to parsed JSON report objects.

        Raises:
            StorageConnectionError: On connection issues.
            StorageOperationError: On non-2xx HTTP responses or unexpected errors.
        """

        logger.info(
            "Retrieving reports for model_uuid=%s model_version=%s",
            model_uuid,
            model_version,
        )

        reports = {}

        try:
            # TODO: Retrieve reports concurrently
            for report_type, metadata in reports_metadata.model_dump().items():
                print(f"Report metadata for {report_type}: {metadata}")

                response = await self.client.get(
                    metadata["download_url"],
                )
                response.raise_for_status()

                reports[report_type] = response.json()
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
        tiered_aimbom: Dict[AIMBOMTier, AIMBOM],
    ) -> None:
        """Upload tiered AIMBOMs to the orchestrator file upload endpoint.

        Args:
            model_uuid: Model UUID to associate with uploaded files.
            model_version: Model version to associate with uploaded files.
            tiered_aimbom: Mapping of `AIMBOMTier` to `AIMBOM` instances.

        Returns:
            None

        Raises:
            StorageAuthError: If authentication with orchestrator fails.
            StorageConnectionError: On connection issues.
            StorageOperationError: On HTTP errors from orchestrator.
        """

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
            data = {
                "pool": settings.POOL_NAME,
                "bucket": settings.BUCKET_NAME,
                "model_uuid": model_uuid,
                "version": model_version,
                # "tags": "aimbom,generated",
            }

            for tier, aimbom in tiered_aimbom.items():
                logger.info(
                    "Uploading AIMBOM tier %s for model_uuid=%s model_version=%s",
                    tier.value,
                    model_uuid,
                    model_version,
                )

                # Convert AIMBOM to JSON bytes
                aimbom_json = json.dumps(
                    jsonable_encoder(aimbom, exclude_none=True),
                )

                filename = f"aimbom-{model_uuid}-{model_version}-{tier.value}.json"

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

                response = await self.client.post(
                    "/files/upload",
                    headers=headers,
                    files=files,
                    data=data,
                )

                response.raise_for_status()

                logger.info(
                    "AIMBOM tier %s uploaded successfully model_uuid=%s model_version=%s",
                    tier.value,
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
        """Close the underlying HTTP client connection.

        Ensures the `httpx.AsyncClient` is closed when the storage adapter is
        being shut down.
        """

        await self.client.aclose()


async def get_storage(request: Request) -> StorageInterface:
    """FastAPI dependency to retrieve the configured storage implementation.

    Args:
        request: FastAPI `Request` whose `app.state.storage` contains the implementation.

    Returns:
        The configured `StorageInterface` instance stored on the application.
    """

    return request.app.state.storage
