from unittest.mock import MagicMock

import pytest
from app.db.db import MinioConnectionError, MinioDB
from app.services.generator import (
    AIMBOMGenerator,
    GeneratorMissingReportError,
    GeneratorStorageError,
)
from app.services.storage import MinioStorage

from tests.utils import (
    MODEL_UUID,
    MODEL_VERSION,
    create_empty_mock_minio,
    create_new_mock_minio,
)


@pytest.mark.anyio
async def test_generate_success():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    minio = create_new_mock_minio()
    storage = MinioStorage(minio)

    generator = AIMBOMGenerator(storage)

    aimbom = await generator.generate(model_uuid, model_version, None)

    assert aimbom.serial_number.startswith("urn:uuid:")


@pytest.mark.anyio
async def test_generate_missing_reports():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    minio = create_empty_mock_minio()
    storage = MinioStorage(minio)

    generator = AIMBOMGenerator(storage)

    with pytest.raises(GeneratorMissingReportError):
        await generator.generate(model_uuid, model_version, None)


@pytest.mark.anyio
async def test_minio_connection_failure():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    minio = MagicMock(spec=MinioDB)
    minio.get_reports_for_model.side_effect = MinioConnectionError("MinIO down")
    storage = MinioStorage(minio)

    generator = AIMBOMGenerator(storage)

    with pytest.raises(GeneratorStorageError):
        await generator.generate(model_uuid, model_version, None)


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
