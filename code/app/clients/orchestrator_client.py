import json
import logging
from typing import Dict

import httpx
from fastapi.encoders import jsonable_encoder

from app.clients.storage_client import (
    StorageAuthError,
    StorageConnectionError,
    StorageInvalidFileError,
    StorageOperationError,
)
from app.core.auth import OrchestratorAuth
from app.core.config import settings
from app.models.aimbom import AIMBOM
from app.models.requests import GenerationMetadata, UploadReportMetadata
from app.utils.utils import uuid_from_serial_number

logger = logging.getLogger(__name__)


class OrchestratorClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        auth: OrchestratorAuth,
    ):
        """Initialize the orchestrator client with an HTTP client and authentication.

        Args:
            client: Async HTTP client used to make requests.
            auth: Authentication handler used to obtain bearer tokens.
        """
        self.client = client
        self.auth = auth

    async def get_file_from_url(self, download_url: str) -> Dict:
        """Download a file from the orchestrator using the provided download URL.

        Args:
            download_url: The relative URL to download the file from.
        """

        try:
            response = await self.client.get(download_url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(
                "Connection error while downloading file from %s",
                download_url,
                exc_info=True,
            )
            raise StorageConnectionError(str(e)) from e
        except httpx.HTTPStatusError as e:
            logger.error(
                "HTTP error while downloading file from %s status_code=%s",
                download_url,
                e.response.status_code,
                exc_info=True,
            )
            raise StorageOperationError(
                f"Orchestrator returned {e.response.status_code}"
            ) from e
        except ValueError as e:
            logger.error(
                "File downloaded from %s is not valid JSON",
                download_url,
                exc_info=True,
            )
            raise StorageInvalidFileError(
                f"File downloaded from '{download_url}' is not valid JSON: {e}"
            ) from e
        except Exception as e:
            logger.error(
                "Unexpected error while downloading file from %s",
                download_url,
                exc_info=True,
            )
            raise StorageOperationError(str(e)) from e

    async def save_file(
        self,
        file: Dict,
        filename: str,
        upload_report_metadata: UploadReportMetadata,
    ):
        """Upload a file to the orchestrator.

        Args:
            file: JSON-serializable payload to upload.
            filename: Name of the uploaded file.
            upload_report_metadata: Destination `pool` / `bucket`, model and tags.

        Raises:
            StorageAuthError: On authentication failures.
            StorageConnectionError: On connection issues.
            StorageOperationError: On non-2xx HTTP responses or unexpected errors.
        """

        try:
            token = await self.auth.get_token()
            headers = {"Authorization": f"Bearer {token}"}
        except Exception as e:
            logger.error(
                "Authentication error while uploading file",
                exc_info=True,
            )
            raise StorageAuthError("Failed to authenticate with orchestrator") from e

        try:
            data = {
                "pool": upload_report_metadata.pool,
                "bucket": upload_report_metadata.bucket,
                "model_uuid": upload_report_metadata.model_uuid,
                "version": upload_report_metadata.version,
            }
            if upload_report_metadata.tags:
                data["tags"] = upload_report_metadata.tags

            logger.info(
                "Uploading file=%s for model_uuid=%s model_version=%s",
                filename,
                upload_report_metadata.model_uuid,
                upload_report_metadata.version,
            )

            files = [
                (
                    "files",
                    (
                        filename,
                        json.dumps(file).encode("utf-8"),
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
                "File uploaded successfully file=%s model_uuid=%s model_version=%s",
                filename,
                upload_report_metadata.model_uuid,
                upload_report_metadata.version,
            )

        except httpx.RequestError as e:
            logger.error(
                "Connection error while uploading file",
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
                "Unexpected error while uploading file",
                exc_info=True,
            )

            raise StorageOperationError(str(e)) from e

    async def get_reports_for_model(
        self,
        generation_metadata: GenerationMetadata,
    ) -> Dict:
        """Retrieve reports from the orchestrator using provided metadata.

        Args:
            generation_metadata: A `GenerationMetadata` instance containing download URLs.

        Returns:
            Mapping of report type keys to parsed JSON report objects.

        Raises:
            StorageConnectionError: On connection issues.
            StorageOperationError: On non-2xx HTTP responses or unexpected errors.
        """

        logger.info("Retrieving reports")

        reports = {}

        # TODO: Retrieve reports concurrently
        for (
            report_type,
            metadata,
        ) in generation_metadata.reports.model_dump().items():
            logger.debug("Downloading report type=%s from orchestrator", report_type)

            if metadata is None:
                logger.warning("No metadata for report type=%s", report_type)
                continue

            reports[report_type] = await self.get_file_from_url(
                download_url=metadata["download_url"]
            )
        return reports

    async def save_aimbom(
        self,
        model_uuid: str,
        model_version: str,
        aimbom: AIMBOM,
    ):
        """Upload a generated AIMBOM document to the orchestrator.

        Args:
            model_uuid: Model UUID used for logging/context only.
            model_version: Model version used for logging/context only.
            aimbom: The generated AIMBOM instance.

        Raises:
            StorageAuthError: On authentication failures.
            StorageConnectionError: On connection issues.
            StorageOperationError: On non-2xx HTTP responses or unexpected errors.
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

            logger.info(
                "Uploading AIMBOM for model_uuid=%s model_version=%s",
                model_uuid,
                model_version,
            )

            # Convert AIMBOM to JSON bytes
            aimbom_json = json.dumps(
                jsonable_encoder(aimbom, exclude_none=True),
            )

            filename = f"model-{model_uuid}-{model_version}-aimbom-{uuid_from_serial_number(aimbom.serial_number)}-v{aimbom.version}.json"

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
        """Close the underlying HTTP client."""
        await self.client.aclose()


def get_orchestrator_client() -> OrchestratorClient:
    """Return an `OrchestratorClient` instance for the application.

    Returns:
        A `OrchestratorClient` instance.
    """

    return OrchestratorClient(
        client=httpx.AsyncClient(
            base_url=settings.ORCHESTRATOR_API_BASE_URL,
        ),
        auth=OrchestratorAuth(),
    )
