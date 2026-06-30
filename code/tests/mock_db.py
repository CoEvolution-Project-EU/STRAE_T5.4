from app.db.db import MinioOperationError


class MockMinioObjectInfo:
    def __init__(self, object_name: str):
        self.object_name = object_name


class MockMinioDB:
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
            raise MinioOperationError(f"{object_name} not found") from e

    def get_reports_for_model(
        self, bucket_name: str, model_uuid: str, model_version: str
    ):
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
