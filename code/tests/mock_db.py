from typing import Dict

from app.clients.storage_client import StorageClient, StorageOperationError
from app.models.aimbom import AIMBOM
from app.models.requests import GenerationMetadata
from app.utils.utils import AIMBOMTier


class MockMinioObjectInfo:
    def __init__(self, object_name: str):
        self.object_name = object_name


class MockMinioClient(StorageClient):
    def __init__(self):
        # bucket_name -> { object_name: data }
        self.buckets = {}

    def create_bucket(self, bucket_name: str):
        self.buckets.setdefault(bucket_name, {})

    def upload_json(self, bucket_name: str, object_name: str, data: dict):
        if bucket_name not in self.buckets:
            raise RuntimeError("Bucket does not exist")
        self.buckets[bucket_name][object_name] = data

    def list_objects_in_bucket(self, bucket_name: str, prefix: str = ""):
        if bucket_name not in self.buckets:
            return []

        return [
            MockMinioObjectInfo(object_name)
            for object_name in self.buckets[bucket_name].keys()
            if object_name.startswith(prefix)
        ]

    def get_json(self, bucket_name: str, object_name: str):
        try:
            return self.buckets[bucket_name][object_name]
        except KeyError as e:
            raise StorageOperationError(f"{object_name} not found") from e

    async def get_reports_for_model(
        self,
        model_uuid: str,
        model_version: str,
        generation_metadata: GenerationMetadata,
    ):
        reports = {}
        bucket_name = "reports"

        prefix = f"{model_uuid}/{model_version}/"

        objects = self.list_objects_in_bucket(bucket_name=bucket_name, prefix=prefix)
        if not objects:
            raise StorageOperationError(
                f"No reports found for model_uuid={model_uuid}, model_version={model_version} in bucket '{bucket_name}' with prefix '{prefix}'"
            )

        for obj in objects:
            if not obj.object_name.endswith(".json"):
                continue

            data = self.get_json(bucket_name, obj.object_name)

            reports[obj.object_name.split("/")[-1].replace(".json", "")] = data

        return reports

    async def save_aimbom(
        self,
        model_uuid: str,
        model_version: str,
        tiered_aimbom: Dict[AIMBOMTier, AIMBOM],
    ):
        bucket_name = "aimboms"
        for tier, aimbom in tiered_aimbom.items():
            object_name = f"{model_uuid}/{model_version}/{tier.value}.json"
            self.upload_json(bucket_name, object_name, aimbom.model_dump())
