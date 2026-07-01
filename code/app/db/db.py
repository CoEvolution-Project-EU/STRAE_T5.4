import json
import logging
from functools import lru_cache
from io import BytesIO
from typing import Dict

from app.core.config import settings
from minio import Minio, S3Error
from minio.datatypes import Object

logger = logging.getLogger(__name__)


class MinioError(Exception):
    """Base exception for MinIO errors."""

    pass


class MinioConnectionError(MinioError):
    """Minio connection error."""

    pass


class MinioOperationError(MinioError):
    """Minio operation error."""

    pass


class MinioDB:
    def __init__(self):
        """Initialize the MinIO client wrapper.

        Creates a `Minio` client using settings from the configuration. Raises
        `MinioConnectionError` if initialization fails.
        """

        try:
            self.client = Minio(
                endpoint=settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ROOT_USER,
                secret_key=settings.MINIO_ROOT_PASSWORD,
                secure=settings.MINIO_SECURE,
            )
        except Exception as e:
            raise MinioConnectionError(f"Failed to initialize MinIO client: {e}") from e

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
            raise MinioOperationError(
                f"S3 error while ensuring bucket '{bucket_name}': {e}"
            ) from e
        except Exception as e:
            raise MinioConnectionError(
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
            raise MinioOperationError(
                f"S3 error while uploading '{object_name}' to bucket '{bucket_name}': {e}"
            ) from e
        except Exception as e:
            raise MinioConnectionError(
                f"Failed to upload object '{object_name}' to bucket '{bucket_name}': {e}"
            ) from e

    def list_objects_in_bucket(
        self, bucket_name: str, prefix: str = ""
    ) -> list[Object]:
        """List objects in a bucket optionally filtered by prefix.

        Args:
            bucket_name: Target bucket name.
            prefix: Optional prefix to filter objects.

        Returns:
            A list of `minio.datatypes.Object` instances.
        """

        try:
            return list(
                self.client.list_objects(
                    bucket_name=bucket_name,
                    prefix=prefix,
                    recursive=True,
                )
            )
        except S3Error as e:
            raise MinioOperationError(
                f"S3 error while listing objects in bucket '{bucket_name}': {e}"
            ) from e
        except Exception as e:
            raise MinioConnectionError(
                f"Failed to list objects in bucket '{bucket_name}': {e}"
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
            MinioOperationError: On S3 errors.
            MinioConnectionError: On transport/connection errors.

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
                raise MinioOperationError(
                    f"S3 operation failed for '{object_name}' in bucket '{bucket_name}': {e}"
                ) from e
            except Exception as e:
                raise MinioConnectionError(
                    f"Failed to retrieve object '{object_name}' from bucket '{bucket_name}': {e}"
                ) from e
            return json.loads(response.read())
        finally:
            if response:
                response.close()
                response.release_conn()

    def get_reports_for_model(
        self, bucket_name: str, model_uuid: str, model_version: str
    ) -> Dict:
        """Retrieve all report JSON files for a given model/version prefix.

        Args:
            bucket_name: Bucket to scan for reports.
            model_uuid: Model UUID used as prefix.
            model_version: Model version used as prefix.

        Returns:
            Mapping of object basename (without .json) to parsed JSON content.

        Raises:
            MinioOperationError: If no reports are found or S3 operations fail.
        """

        reports = {}
        prefix = f"{model_uuid}/{model_version}/"

        objects = self.list_objects_in_bucket(bucket_name=bucket_name, prefix=prefix)

        if not objects:
            raise MinioOperationError(
                f"No reports found for model_uuid={model_uuid}, model_version={model_version} in bucket '{bucket_name}' with prefix '{prefix}'"
            )

        for obj in objects:
            if not obj.object_name.endswith(".json"):
                continue

            data = self.get_json(bucket_name, obj.object_name)
            reports[obj.object_name.split("/")[-1].replace(".json", "")] = data

        return reports


@lru_cache
def get_minio_client() -> MinioDB:
    """Return a cached `MinioDB` instance for the application.

    Returns:
        A `MinioDB` instance.
    """

    return MinioDB()
