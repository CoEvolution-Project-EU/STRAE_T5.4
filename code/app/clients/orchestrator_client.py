import json
import logging
from typing import Dict

import httpx
from fastapi.encoders import jsonable_encoder

from app.clients.storage_client import (
    StorageAuthError,
    StorageConnectionError,
    StorageOperationError,
)
from app.core.auth import OrchestratorAuth
from app.core.config import settings
from app.models.aimbom import AIMBOM
from app.models.requests import GenerationMetadata
from app.utils.utils import AIMBOMTier

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

    async def get_reports_for_model(
        self,
        model_uuid: str,
        model_version: str,
        generation_metadata: GenerationMetadata,
    ) -> Dict:
        """Retrieve reports from the orchestrator using provided metadata.

        Args:
            model_uuid: Model UUID used for logging/context only.
            model_version: Model version used for logging/context only.
            generation_metadata: A `GenerationMetadata` instance containing download URLs.

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
            for report_type, metadata in generation_metadata.model_dump().items():
                logger.debug(
                    "Downloading report type=%s from orchestrator for model_uuid=%s model_version=%s",
                    report_type,
                    model_uuid,
                    model_version,
                )

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

    async def upload_aimbom(
        self,
        model_uuid: str,
        model_version: str,
        tiered_aimbom: Dict[AIMBOMTier, AIMBOM],
    ):
        """Upload generated AIMBOM documents to the orchestrator.

        Args:
            model_uuid: Model UUID used for logging/context only.
            model_version: Model version used for logging/context only.
            tiered_aimbom: Mapping of AIMBOM tiers to AIMBOM payloads.

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

            # TODO: Upload AIMBOMs concurrently
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
