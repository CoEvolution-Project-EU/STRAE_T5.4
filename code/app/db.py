import json
import logging
from functools import lru_cache
from io import BytesIO

from minio import Minio
from minio.datatypes import Object

from app.config import settings

logger = logging.getLogger(__name__)


class MinioConnectionError(Exception):
    """Minio connection error."""

    pass


class MinioDB:
    def __init__(self):
        try:
            self.client = Minio(
                endpoint=settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE,
            )
        except Exception as e:
            raise MinioConnectionError(f"Failed to initialize MinIO client: {e}") from e

        logger.info("MinIO client initialized")

    def create_bucket(self, bucket_name: str) -> None:
        try:
            if not self.client.bucket_exists(bucket_name):
                self.client.make_bucket(bucket_name)
                logger.info("Created bucket %s", bucket_name)
            else:
                logger.debug("Bucket %s already exists", bucket_name)
        except Exception as e:
            raise MinioConnectionError(
                f"Failed to ensure bucket '{bucket_name}': {e}"
            ) from e

    def upload_json(
        self,
        bucket_name: str,
        object_name: str,
        data: dict,
    ) -> None:
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
        except Exception as e:
            raise MinioConnectionError(
                f"Failed to upload object '{object_name}' to bucket '{bucket_name}': {e}"
            ) from e

    def list_objects_in_bucket(
        self, bucket_name: str, prefix: str = ""
    ) -> list[Object]:
        try:
            return list(
                self.client.list_objects(
                    bucket_name=bucket_name,
                    prefix=prefix,
                    recursive=True,
                )
            )
        except Exception as e:
            raise MinioConnectionError(
                f"Failed to list objects in bucket '{bucket_name}': {e}"
            ) from e

    def get_json(
        self,
        bucket_name: str,
        object_name: str,
    ) -> dict:
        response = None
        try:
            try:
                response = self.client.get_object(
                    bucket_name=bucket_name,
                    object_name=object_name,
                )
            except Exception as e:
                raise MinioConnectionError(
                    f"Failed to retrieve object '{object_name}' from bucket '{bucket_name}': {e}"
                ) from e
            return json.loads(response.read())
        finally:
            if response:
                response.close()
                response.release_conn()


# MinioDB dependency
# Use lru_cache to ensure a singleton MinioDB instance is used throughout the application
# Officially recommended by FastAPI for shared resources. Is thread-safe.
@lru_cache
def get_minio_client() -> MinioDB:
    return MinioDB()
