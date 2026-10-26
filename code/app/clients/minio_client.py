import json
import logging
from functools import lru_cache
from io import BytesIO
from typing import Dict

from asyncer import asyncify
from fastapi.encoders import jsonable_encoder
from minio import Minio, S3Error

from app.clients.storage_client import (
    StorageClient,
    StorageConnectionError,
    StorageOperationError,
)
from app.core.config import settings
from app.models.aimbom import AIMBOM
from app.models.requests import GenerationMetadata
from app.utils.utils import uuid_from_serial_number

logger = logging.getLogger(__name__)


class MinioClient(StorageClient):
    def __init__(self, client: Minio):
        """Initialize the MinIO client wrapper.

        Creates a `Minio` client using settings from the configuration. Raises
        `StorageConnectionError` if initialization fails.
        """

        self.client = client
        logger.info("MinIO client initialized")

    def create_bucket(self, bucket_name: str) -> None:
        """Ensure a MinIO bucket exists, creating it if necessary.

        Args:
            bucket_name: The name of the bucket to ensure exists.

        Returns:
            None
        """

        try:
            if not self.client.bucket_exists(bucket_name):
                self.client.make_bucket(bucket_name)
                logger.info("Created bucket %s", bucket_name)
            else:
                logger.debug("Bucket %s already exists", bucket_name)
        except S3Error as e:
            raise StorageOperationError(
                f"S3 error while ensuring bucket '{bucket_name}': {e}"
            ) from e
        except Exception as e:
            raise StorageConnectionError(
                f"Failed to ensure bucket '{bucket_name}': {e}"
            ) from e

    def upload_json(
        self,
        bucket_name: str,
        object_name: str,
        data: Dict,
    ) -> None:
        """Upload a JSON-serializable object to MinIO as application/json.

        Args:
            bucket_name: Target bucket.
            object_name: Object key path in the bucket.
            data: JSON-serializable payload to store.

        Returns:
            None
        """

        json_bytes = json.dumps(data).encode("utf-8")
        json_stream = BytesIO(json_bytes)

        try:
            self.client.put_object(
                bucket_name=bucket_name,
                object_name=object_name,
                data=json_stream,
                length=len(json_bytes),
                content_type="application/vnd.cyclonedx+json",
            )
        except S3Error as e:
            raise StorageOperationError(
                f"S3 error while uploading '{object_name}' to bucket '{bucket_name}': {e}"
            ) from e
        except Exception as e:
            raise StorageConnectionError(
                f"Failed to upload object '{object_name}' to bucket '{bucket_name}': {e}"
            ) from e

    def get_json(
        self,
        bucket_name: str,
        object_name: str,
    ) -> Dict:
        """Retrieve a JSON object from MinIO and parse it.

        Args:
            bucket_name: The bucket containing the object.
            object_name: The object key to retrieve.

        Returns:
            The parsed JSON payload as a `dict`.

        Raises:
            StorageOperationError: On S3 errors.
            StorageConnectionError: On transport/connection errors.

        Ensures the response stream is properly closed after reading.
        """

        response = None
        try:
            try:
                response = self.client.get_object(
                    bucket_name=bucket_name,
                    object_name=object_name,
                )
            except S3Error as e:
                raise StorageOperationError(
                    f"S3 operation failed for '{object_name}' in bucket '{bucket_name}': {e}"
                ) from e
            except Exception as e:
                raise StorageConnectionError(
                    f"Failed to retrieve object '{object_name}' from bucket '{bucket_name}': {e}"
                ) from e
            return json.loads(response.read())
        finally:
            if response:
                response.close()
                response.release_conn()

    async def get_file_from_url(self, download_url: str) -> Dict:
        """Retrieve a file from MinIO given a download URL.

        Args:
            download_url: The download URL in the format 'bucket_name/object_name'.

        Returns:
            The parsed JSON content of the file.

        Raises:
            StorageOperationError: If the download URL format is invalid
        """

        try:
            bucket_name, object_name = download_url.split("/", 1)
        except ValueError:
            raise StorageOperationError(
                f"Invalid download URL format: '{download_url}'. Expected 'bucket_name/object_name'."
            )

        return await asyncify(self.get_json)(
            bucket_name=bucket_name,
            object_name=object_name,
        )

    async def get_reports_for_model(
        self,
        generation_metadata: GenerationMetadata,
    ) -> Dict:
        """Retrieve all report JSON files for a given model/version prefix.

        Args:
            generation_metadata: Metadata containing download URLs for each report type.

        Returns:
            Mapping of object basename (without .json) to parsed JSON content.
        """

        reports = {}

        for report_type, metadata in generation_metadata.reports.model_dump().items():
            logger.debug("Downloading report type=%s from orchestrator", report_type)

            if metadata is None:
                logger.warning("No metadata for report type=%s", report_type)
                continue

            download_url = metadata.get("download_url")
            if not download_url:
                logger.warning("No download URL for report type=%s", report_type)
                continue

            reports[report_type] = await self.get_file_from_url(
                download_url=download_url
            )

        return reports

    async def save_aimbom(
        self,
        model_uuid: str,
        model_version: str,
        aimbom: AIMBOM,
    ):
        logger.debug(
            "Saving AIMBOM to bucket for model_uuid=%s, model_version=%s, serial_number=%s",
            model_uuid,
            model_version,
            aimbom.serial_number,
        )
        await asyncify(self.upload_json)(
            bucket_name=settings.AIMBOMS_BUCKET,
            object_name=f"{model_uuid}/{model_version}/{uuid_from_serial_number(aimbom.serial_number)}-v{aimbom.version}.json",
            data=jsonable_encoder(aimbom, exclude_none=True),
        )


@lru_cache
def get_minio_client() -> MinioClient:
    """Return a cached `MinioClient` instance for the application.

    Returns:
        A `MinioClient` instance.
    """

    return MinioClient(
        client=Minio(
            endpoint=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ROOT_USER,
            secret_key=settings.MINIO_ROOT_PASSWORD,
            secure=settings.MINIO_SECURE,
        )
    )
