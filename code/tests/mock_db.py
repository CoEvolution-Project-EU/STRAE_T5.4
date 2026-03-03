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
        return self.buckets[bucket_name][object_name]
