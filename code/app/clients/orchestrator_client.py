import asyncio
import json
import logging
from typing import Dict, Tuple
from urllib.parse import quote

import httpx
from fastapi.encoders import jsonable_encoder

from app.clients.orchestrator_auth import OrchestratorAuth
from app.clients.storage_client import (
    CYCLONEDX_CONTENT_TYPE,
    StorageAuthError,
    StorageBadRequestError,
    StorageConflictError,
    StorageConnectionError,
    StorageInvalidFileError,
    StorageNotFoundError,
    StorageOperationError,
    get_file_if_exists,
)
from app.core.config import settings
from app.models.aimbom import AIMBOM
from app.models.requests import GenerationMetadata
from app.models.storage import UploadReportMetadata
from app.utils.utils import ReportType, uuid_from_serial_number

logger = logging.getLogger(__name__)


def _get_download_url(file: object, name: str) -> str:
    """Get the download URL of an entry of the orchestrator's latest files.

    Args:
        file: The entry from the `/latest` response.
        name: The entry's key in the response, for the error message.

    Returns:
        The entry's download URL.

    Raises:
        StorageOperationError: If the entry has no download URL.
    """

    url = file.get("download_url") if isinstance(file, dict) else None
    if not url or not isinstance(url, str):
        raise StorageOperationError(
            f"Orchestrator response for the latest files has no 'download_url' "
            f"for '{name}'"
        )

    return url


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

        Raises:
            StorageNotFoundError: If the file does not exist.
            StorageConnectionError: On connection issues or 5xx responses.
            StorageInvalidFileError: If the file is not valid JSON.
            StorageOperationError: On other non-2xx HTTP responses or
                unexpected errors.
        """

        try:
            response = await self.client.get(download_url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(
                "Connection error while downloading file from %s: %s",
                download_url,
                e,
            )
            raise StorageConnectionError(str(e)) from e
        except httpx.HTTPStatusError as e:
            logger.error(
                "HTTP error while downloading file from %s status_code=%s",
                download_url,
                e.response.status_code,
            )
            message = f"Orchestrator returned {e.response.status_code}"
            if e.response.status_code == httpx.codes.NOT_FOUND:
                raise StorageNotFoundError(message) from e
            if e.response.status_code >= 500:
                raise StorageConnectionError(message) from e
            raise StorageOperationError(message) from e
        except ValueError as e:
            logger.error(
                "File downloaded from %s is not valid JSON: %s",
                download_url,
                e,
            )
            raise StorageInvalidFileError(
                f"File downloaded from '{download_url}' is not valid JSON: {e}"
            ) from e
        except Exception as e:
            logger.error(
                "Unexpected error while downloading file from %s: %s",
                download_url,
                e,
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
            upload_report_metadata: Destination `pool` / `bucket`, model, tags and
                the ID of the original the file is a signed copy of.

        Raises:
            StorageAuthError: On authentication failures.
            StorageConnectionError: On connection issues.
            StorageConflictError: If the original has already been signed (409).
            StorageBadRequestError: If the orchestrator rejects the fields (400).
            StorageOperationError: On other non-2xx HTTP responses or unexpected errors.
        """

        logger.info(
            "Uploading file=%s for model_uuid=%s model_version=%s",
            filename,
            upload_report_metadata.model_uuid,
            upload_report_metadata.version,
        )

        data = {
            "pool": upload_report_metadata.pool,
            "bucket": upload_report_metadata.bucket,
            "model_uuid": upload_report_metadata.model_uuid,
            "version": upload_report_metadata.version,
            "tags": upload_report_metadata.tags,
            "original_file_id": upload_report_metadata.original_file_id,
        }

        await self._upload_file(filename=filename, file=file, data=data)

        logger.info(
            "File uploaded successfully file=%s model_uuid=%s model_version=%s",
            filename,
            upload_report_metadata.model_uuid,
            upload_report_metadata.version,
        )

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
        """Upload an AIMBOM to the orchestrator.

        Args:
            model_uuid: The UUID of the model.
            model_version: The version of the model.
            aimbom: The AIMBOM object to upload.

        Raises:
            StorageAuthError: On authentication failures.
            StorageConnectionError: On connection issues.
            StorageOperationError: On non-2xx HTTP responses or unexpected errors.
        """

        logger.info(
            "Uploading AIMBOM for model_uuid=%s model_version=%s",
            model_uuid,
            model_version,
        )

        await self._upload_file(
            filename=f"model-{model_uuid}-{model_version}-aimbom-{uuid_from_serial_number(aimbom.serial_number)}-v{aimbom.version}.json",
            file=jsonable_encoder(aimbom, exclude_none=True),
            data={
                "pool": settings.POOL_NAME,
                "bucket": settings.BUCKET_NAME,
                "model_uuid": model_uuid,
                "version": model_version,
            },
            content_type=CYCLONEDX_CONTENT_TYPE,
        )

        logger.info(
            "AIMBOM uploaded successfully model_uuid=%s model_version=%s",
            model_uuid,
            model_version,
        )

    async def get_aimbom(
        self,
        model_uuid: str,
        model_version: str,
    ) -> Tuple[Dict, Dict[str, Dict]]:
        """Retrieve a model version's latest AIMBOM and latest signed reports.

        Asks the orchestrator's `GET /models/{uuid}/versions/{version}/latest`
        endpoint for the files, then downloads them concurrently. Report
        types the orchestrator lists as missing, or whose file does not exist,
        are left out of the result.

        Args:
            model_uuid: The UUID of the model.
            model_version: The version of the model.

        Returns:
            The AIMBOM, and a mapping of report type value (e.g. `risk_report`)
            to report, as in `get_reports_for_model`. Each file is parsed JSON.

        Raises:
            StorageNotFoundError: If the model version does not exist or has
                no AIMBOM.
            StorageConnectionError: On connection issues or 5xx responses.
            StorageInvalidFileError: If a downloaded file is not valid JSON.
            StorageOperationError: On other non-2xx HTTP responses, or if the
                `/latest` response is malformed.
        """

        logger.info(
            "Retrieving latest AIMBOM for model_uuid=%s model_version=%s",
            model_uuid,
            model_version,
        )

        latest = await self._get_latest_files(model_uuid, model_version)

        files = latest.get("reports") if isinstance(latest, dict) else None
        if not isinstance(files, dict):
            raise StorageOperationError(
                "Orchestrator response for the latest files has no 'reports'"
            )

        aimbom_file = files.get("aimbom_report")
        if not aimbom_file:
            raise StorageNotFoundError(
                f"No AIMBOM found for model_uuid='{model_uuid}', "
                f"model_version='{model_version}'"
            )
        aimbom_url = _get_download_url(aimbom_file, "aimbom_report")

        report_urls = {}
        for report_type in ReportType:
            report_file = files.get(report_type.value)
            if not report_file:
                logger.warning(
                    "No %s for model_uuid=%s model_version=%s",
                    report_type.value,
                    model_uuid,
                    model_version,
                )
                continue
            report_urls[report_type.value] = _get_download_url(
                report_file, report_type.value
            )

        aimbom, *downloaded_reports = await asyncio.gather(
            self.get_file_from_url(aimbom_url),
            *(get_file_if_exists(self, url) for url in report_urls.values()),
        )
        # `gather` keeps the order of its arguments, so the reports line up
        # with `report_urls`.
        reports = {
            report_type: report
            for report_type, report in zip(report_urls, downloaded_reports)
            if report is not None
        }

        logger.info(
            "Retrieved AIMBOM and %d reports for model_uuid=%s model_version=%s",
            len(reports),
            model_uuid,
            model_version,
        )

        return aimbom, reports

    async def _get_latest_files(self, model_uuid: str, model_version: str) -> Dict:
        """Get the orchestrator's latest files of a model version.

        Args:
            model_uuid: The UUID of the model.
            model_version: The version of the model.

        Returns:
            The parsed response of `GET /models/{uuid}/versions/{version}/latest`.

        Raises:
            StorageNotFoundError: If the model version does not exist or has
                no AIMBOM.
            StorageConnectionError: On connection issues or 5xx responses.
            StorageOperationError: On other non-2xx HTTP responses, or if the
                response is not valid JSON.
        """

        url = (
            f"/models/{quote(model_uuid, safe='')}"
            f"/versions/{quote(model_version, safe='')}/latest"
        )

        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error("Connection error while getting %s: %s", url, e)
            raise StorageConnectionError(str(e)) from e
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            logger.error("Getting %s failed with status_code=%s", url, status_code)
            if status_code == httpx.codes.NOT_FOUND:
                raise StorageNotFoundError(
                    f"Model not found: model_uuid='{model_uuid}', "
                    f"model_version='{model_version}'"
                ) from e
            if status_code >= 500:
                raise StorageConnectionError(
                    f"Orchestrator returned {status_code}"
                ) from e
            raise StorageOperationError(f"Orchestrator returned {status_code}") from e
        except ValueError as e:
            raise StorageOperationError(
                f"Orchestrator response for '{url}' is not valid JSON: {e}"
            ) from e

    async def _upload_file(
        self,
        filename: str,
        file: Dict,
        data: Dict,
        content_type: str = "application/json",
    ):
        """Upload a file to the orchestrator.

        Args:
            filename: Name of the file to upload.
            file: JSON-serializable payload to upload.
            data: Additional form data to send with the request.
            content_type: Content type of the uploaded file.

        Raises:
            StorageAuthError: On authentication failures.
            StorageConnectionError: On connection issues or 5xx responses.
            StorageConflictError: On a 409 response.
            StorageBadRequestError: On a 400 response.
            StorageOperationError: On other non-2xx HTTP responses or unexpected errors.
        """

        try:
            token = await self.auth.get_token()
            headers = {"Authorization": f"Bearer {token}"}
        except Exception as e:
            logger.error(
                "Authentication error while saving file: %s",
                e,
            )
            raise StorageAuthError("Failed to authenticate with orchestrator") from e

        try:
            files = [
                (
                    "files",
                    (
                        filename,
                        json.dumps(file).encode("utf-8"),
                        content_type,
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

        except httpx.RequestError as e:
            logger.error(
                "Connection error while uploading file: %s",
                e,
            )

            raise StorageConnectionError(str(e)) from e

        except httpx.HTTPStatusError as e:
            if e.response.status_code == httpx.codes.CONFLICT:
                logger.info(
                    "Orchestrator already has file=%s response=%s",
                    filename,
                    e.response.text,
                )

                raise StorageConflictError(
                    f"Orchestrator returned {e.response.status_code}: {e.response.text}"
                ) from e

            logger.error(
                "Upload failed with status_code=%s response=%s",
                e.response.status_code,
                e.response.text,
            )

            if e.response.status_code == httpx.codes.BAD_REQUEST:
                raise StorageBadRequestError(
                    f"Orchestrator returned {e.response.status_code}: {e.response.text}"
                ) from e

            # Same as for downloads: a 5xx means the orchestrator is unavailable.
            if e.response.status_code >= 500:
                raise StorageConnectionError(
                    f"Orchestrator returned {e.response.status_code}"
                ) from e

            raise StorageOperationError(
                f"Orchestrator returned {e.response.status_code}"
            ) from e

        except Exception as e:
            logger.error(
                "Unexpected error while uploading file: %s",
                e,
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
