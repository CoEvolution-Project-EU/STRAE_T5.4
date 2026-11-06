import asyncio
import json
import logging
from functools import lru_cache
from io import BytesIO
from typing import Dict, Tuple

from asyncer import asyncify
from fastapi.encoders import jsonable_encoder
from minio import Minio, S3Error

from app.clients.storage_client import (
    CYCLONEDX_CONTENT_TYPE,
    StorageClient,
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
        content_type: str = "application/json",
    ) -> None:
        """Upload a JSON-serializable object to MinIO.

        Args:
            bucket_name: Target bucket.
            object_name: Object key path in the bucket.
            data: JSON-serializable payload to store.
            content_type: Content type of the stored object.

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
                content_type=content_type,
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
            StorageNotFoundError: If the object does not exist.
            StorageOperationError: On other S3 errors.
            StorageConnectionError: On transport/connection errors.
            StorageInvalidFileError: If the object is not valid JSON.

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
                if e.code == "NoSuchKey":
                    raise StorageNotFoundError(
                        f"Object '{object_name}' does not exist in bucket '{bucket_name}'"
                    ) from e
                raise StorageOperationError(
                    f"S3 operation failed for '{object_name}' in bucket '{bucket_name}': {e}"
                ) from e
            except Exception as e:
                raise StorageConnectionError(
                    f"Failed to retrieve object '{object_name}' from bucket '{bucket_name}': {e}"
                ) from e
            try:
                return json.loads(response.read())
            except ValueError as e:
                raise StorageInvalidFileError(
                    f"Object '{object_name}' in bucket '{bucket_name}' is not valid JSON: {e}"
                ) from e
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

    async def save_file(
        self,
        file: Dict,
        filename: str,
        upload_report_metadata: UploadReportMetadata,
    ):
        """Upload a file to the reports bucket under `{model_uuid}/{version}/{bucket}`.

        MinIO doesn't use `pool`, `tags` or `filename`.

        Args:
            file: JSON-serializable payload to store.
            filename: Name of the file. Unused, see above.
            upload_report_metadata: Destination of the uploaded file.
        """

        logger.debug(
            "Saving file to bucket=%s for model_uuid=%s, model_version=%s",
            upload_report_metadata.bucket,
            upload_report_metadata.model_uuid,
            upload_report_metadata.version,
        )

        await asyncify(self.upload_json)(
            bucket_name=settings.REPORTS_BUCKET,
            object_name=f"{upload_report_metadata.model_uuid}/{upload_report_metadata.version}/{upload_report_metadata.bucket}.json",
            data=file,
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
            content_type=CYCLONEDX_CONTENT_TYPE,
        )

    async def get_aimbom_urls(
        self,
        model_uuid: str,
        model_version: str,
    ) -> Tuple[str, Dict[str, str]]:
        """Get the download URLs of a model version's first AIMBOM and its reports.

        The first AIMBOM is the earliest uploaded object under
        `{AIMBOMS_BUCKET}/{model_uuid}/{model_version}/`. The report URLs are
        not looked up: they are the version 1 reports,
        `{REPORTS_BUCKET}/{model_uuid}/{model_version}/{report_type}.json` for
        each `ReportType`, whether or not they exist.

        Args:
            model_uuid: The UUID of the model.
            model_version: The version of the model.

        Returns:
            Download URLs in the format `bucket_name/object_name`: the
            AIMBOM's, and a mapping of report type value (e.g. `risk_report`)
            to each report's.

        Raises:
            StorageNotFoundError: If the model version has no AIMBOM.
            StorageOperationError: On S3 errors.
            StorageConnectionError: On transport/connection errors.
        """

        # Trailing slash so `v1.0` doesn't also match `v1.0.1`.
        prefix = f"{model_uuid}/{model_version}/"

        def list_aimboms() -> list:
            try:
                return [
                    obj
                    for obj in self.client.list_objects(
                        settings.AIMBOMS_BUCKET, prefix=prefix, recursive=True
                    )
                    if not obj.is_dir
                ]
            except S3Error as e:
                raise StorageOperationError(
                    f"S3 error while listing '{prefix}' in bucket '{settings.AIMBOMS_BUCKET}': {e}"
                ) from e
            except Exception as e:
                raise StorageConnectionError(
                    f"Failed to list '{prefix}' in bucket '{settings.AIMBOMS_BUCKET}': {e}"
                ) from e

        aimboms = await asyncify(list_aimboms)()
        if not aimboms:
            raise StorageNotFoundError(
                f"No AIMBOM found for model_uuid='{model_uuid}', "
                f"model_version='{model_version}'"
            )
        first_aimbom = min(aimboms, key=lambda obj: obj.last_modified)

        aimbom_url = f"{settings.AIMBOMS_BUCKET}/{first_aimbom.object_name}"

        report_urls = {
            report_type.value: f"{settings.REPORTS_BUCKET}/{prefix}{report_type.value}.json"
            for report_type in ReportType
        }

        return aimbom_url, report_urls

    async def get_aimbom(
        self,
        model_uuid: str,
        model_version: str,
    ) -> Tuple[Dict, Dict[str, Dict]]:
        """Retrieve a model version's first AIMBOM and its reports.

        See `get_aimbom_urls` for which files are retrieved. Files are
        downloaded concurrently. Reports that do not exist are left out of the
        result.

        Args:
            model_uuid: The UUID of the model.
            model_version: The version of the model.

        Returns:
            The AIMBOM, and a mapping of report type value (e.g. `risk_report`)
            to report, as in `get_reports_for_model`. Each file is parsed JSON.

        Raises:
            StorageNotFoundError: If the model version has no AIMBOM.
            StorageConnectionError: On transport/connection errors.
            StorageOperationError: On other S3 errors.
            StorageInvalidFileError: If a file is not valid JSON.
        """

        logger.debug(
            "Retrieving AIMBOM from bucket for model_uuid=%s, model_version=%s",
            model_uuid,
            model_version,
        )

        aimbom_url, report_urls = await self.get_aimbom_urls(model_uuid, model_version)

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

        logger.debug(
            "Retrieved AIMBOM %s and %d reports for model_uuid=%s, model_version=%s",
            aimbom_url,
            len(reports),
            model_uuid,
            model_version,
        )

        return aimbom, reports


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
