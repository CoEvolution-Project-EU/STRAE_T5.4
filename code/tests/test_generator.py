from unittest.mock import AsyncMock, MagicMock

import pytest
from app.clients.minio_client import MinioClient
from app.clients.storage_client import StorageClient, StorageConnectionError
from app.services.generator import (
    AIMBOMGenerator,
    GeneratorGenerationError,
    GeneratorMissingReportError,
    GeneratorStorageError,
)
from app.utils.utils import AIMBOMTier, ReportComment, ReportType
from fastapi.encoders import jsonable_encoder

from tests.utils import (
    MODEL_UUID,
    MODEL_VERSION,
    create_empty_mock_minio,
    create_new_mock_minio,
    verify_report,
)


@pytest.mark.anyio
async def test_generate_success():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    minio = create_new_mock_minio()
    generator = AIMBOMGenerator(minio)

    tiered_aimbom = await generator.generate(model_uuid, model_version, None)

    aimbom_tier3 = tiered_aimbom[AIMBOMTier.TIER_3]
    aimbom_tier2 = tiered_aimbom[AIMBOMTier.TIER_2]
    aimbom_tier1 = tiered_aimbom[AIMBOMTier.TIER_1]

    # Check that the serial numbers are valid URNs
    assert aimbom_tier3.serial_number.startswith("urn:uuid:")

    # Check that the external references urls are as expected
    references = {ref.comment: ref for ref in aimbom_tier3.external_references}

    assert references[ReportComment.AI_MODEL_INFO].url == (
        "urn:cdx:2d2e6ba3-b9f2-4865-a182-9d31ea4d2f9e/1"
    )

    assert references[ReportComment.ASSESSMENTS].url == (
        "urn:cdx:bbc77e3c-ec17-42b1-af15-580626ea66d7/1"
    )

    assert references[ReportComment.DATASETS].url == (
        "urn:cdx:a1b2c3d4-e5f6-7890-abcd-ef1234567891/1"
    )

    assert references[ReportComment.DEFENCES].url == (
        "urn:cdx:0680d443-854c-49f6-ab4e-a0b560219a3a/1"
    )

    assert references[ReportComment.EU_AI_ACT].url == (
        "urn:cdx:7e8a5f72-1b3e-4f4c-94d1-3a2f6c4fbbd1/1"
    )

    assert references[ReportComment.GADGETS].url == (
        "urn:cdx:52c57fd2-b03a-44c1-b9c0-7c5f7d2a8666/1"
    )

    assert references[ReportComment.RISK_REPORT].url == (
        "urn:cdx:689d20e1-38b1-4c07-bdcb-b5736440c2f7/1"
    )

    # Check that the external references in each tiered AIMBOM have the expected reference types
    tier2_comments = {ref.comment for ref in aimbom_tier2.external_references}
    assert tier2_comments == {
        ReportComment.EU_AI_ACT,
        ReportComment.RISK_REPORT,
        ReportComment.ASSESSMENTS,
        ReportComment.DEFENCES,
        ReportComment.GADGETS,
    }

    tier1_comments = {ref.comment for ref in aimbom_tier1.external_references}
    assert tier1_comments == {ReportComment.EU_AI_ACT}

    # Check that the generated AIMBOM is valid and can be verified
    assert verify_report(jsonable_encoder(aimbom_tier3, exclude_none=True)) is True


@pytest.mark.anyio
async def test_generate_missing_reports():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    minio = create_empty_mock_minio()
    generator = AIMBOMGenerator(minio)

    with pytest.raises(GeneratorMissingReportError):
        await generator.generate(model_uuid, model_version, None)


@pytest.mark.anyio
async def test_minio_connection_failure():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    minio = MagicMock(spec=MinioClient)
    minio.get_reports_for_model.side_effect = StorageConnectionError("MinIO down")
    generator = AIMBOMGenerator(minio)

    with pytest.raises(GeneratorStorageError):
        await generator.generate(model_uuid, model_version, None)


@pytest.mark.anyio
async def test_invalid_report_data():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    storage = MagicMock(spec=StorageClient)

    storage.get_reports_for_model = AsyncMock(
        return_value={ReportType.AI_MODEL_INFO: {"invalid": "schema"}}
    )

    generator = AIMBOMGenerator(storage)

    with pytest.raises(GeneratorGenerationError):
        await generator.generate(model_uuid, model_version, None)
