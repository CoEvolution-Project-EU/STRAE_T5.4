from unittest.mock import MagicMock

import pytest
from app.db import MinioConnectionError, MinioDB
from app.generator import (
    AIMBOMGenerator,
    GeneratorMinioError,
    GeneratorMissingReportError,
)

from tests.utils import MODEL_UUID, create_empty_mock_minio, create_new_mock_minio


def test_generate_success():
    model_uuid = MODEL_UUID

    minio = create_new_mock_minio()

    generator = AIMBOMGenerator(minio)

    aimbom = generator.generate(model_uuid)

    assert aimbom.serial_number.startswith("urn:uuid:")


def test_generate_missing_reports():
    model_uuid = MODEL_UUID

    minio = create_empty_mock_minio()

    generator = AIMBOMGenerator(minio)

    with pytest.raises(GeneratorMissingReportError):
        generator.generate(model_uuid)


def test_minio_connection_failure():
    model_uuid = MODEL_UUID

    minio = MagicMock(spec=MinioDB)
    minio.get_json.side_effect = MinioConnectionError("MinIO down")

    generator = AIMBOMGenerator(minio)

    with pytest.raises(GeneratorMinioError):
        generator.generate(model_uuid)


# Update this test when we have report validation logic implemented
# def test_invalid_report_data():
#     model_uuid = "4ff2dab7-bffe-414d-88a5-1826b9fea8df"

#     minio = MagicMock(spec=MinioDB)

#     obj = MagicMock()
#     obj.object_name = "4ff2dab7-bffe-414d-88a5-1826b9fea8df/bad.json"

#     minio.list_objects_in_bucket.return_value = [obj]
#     minio.get_json.return_value = {"invalid": "schema"}

#     generator = AIMBOMGenerator(minio)

#     with pytest.raises(GeneratorGenerationError):
#         generator.generate(model_uuid)
