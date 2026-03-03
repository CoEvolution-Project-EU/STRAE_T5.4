from unittest.mock import MagicMock

import pytest

from app.db import MinioConnectionError, MinioDB
from app.generator import (
    AIMBOMGenerator,
    GenerationError,
    MinioStorageError,
    MissingReportsError,
)
from tests.utils import create_empty_mock_minio, create_new_mock_minio


def test_generate_success():
    model_id = "model-123"

    minio = create_new_mock_minio()

    generator = AIMBOMGenerator(minio)

    aimbom = generator.generate(model_id)

    assert aimbom.get_model_id() == model_id
    assert aimbom.serial_number.startswith("urn:uuid:")


def test_generate_missing_reports():
    model_id = "model-123"

    minio = create_empty_mock_minio()

    generator = AIMBOMGenerator(minio)

    with pytest.raises(MissingReportsError):
        generator.generate(model_id)


def test_minio_connection_failure():
    minio = MagicMock(spec=MinioDB)
    minio.list_objects_in_bucket.side_effect = MinioConnectionError("MinIO down")

    generator = AIMBOMGenerator(minio)

    with pytest.raises(MinioStorageError):
        generator.generate("model-123")


def test_invalid_report_data():
    minio = MagicMock(spec=MinioDB)

    obj = MagicMock()
    obj.object_name = "model-123/bad.json"

    minio.list_objects_in_bucket.return_value = [obj]
    minio.get_json.return_value = {"invalid": "schema"}

    generator = AIMBOMGenerator(minio)

    with pytest.raises(GenerationError):
        generator.generate("model-123")
