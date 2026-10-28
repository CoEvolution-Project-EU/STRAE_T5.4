from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.clients.storage_client import StorageClient, StorageConnectionError
from app.models.aimbom import AIMBOM
from app.models.requests import GenerationMetadata
from app.services.generator import (
    AIMBOMGenerator,
    GeneratorGenerationError,
    GeneratorMissingReportError,
    GeneratorSigningError,
    GeneratorStorageError,
)
from app.services.signing import SigningError
from app.utils.utils import (
    REPORT_MODELS,
    ReportComment,
    ReportType,
)
from fastapi.encoders import jsonable_encoder

from tests.utils import (
    AIMBOMS_DIR,
    MODEL_UUID,
    MODEL_VERSION,
    REPORTS_DIR,
    create_empty_mock_storage,
    create_new_mock_storage,
    get_generation_metadata,
    get_generation_metadata_deprecation,
    get_generation_metadata_deprecation_with_gadgets,
    load_json,
    verify_signature,
)


@pytest.mark.anyio
async def test_generate_success():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    storage = create_new_mock_storage()
    generator = AIMBOMGenerator(storage)

    aimbom = await generator.generate(
        GenerationMetadata(**get_generation_metadata(model_uuid, model_version)),
    )

    # Check that the serial numbers are valid URNs
    assert aimbom.serial_number.startswith("urn:uuid:")

    # Check that the external references urls are as expected
    references = {ref.comment: ref for ref in aimbom.external_references}

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

    # Check that the generated AIMBOM signature is valid and can be verified
    assert verify_signature(jsonable_encoder(aimbom, exclude_none=True)) is True


@pytest.mark.anyio
async def test_generate_missing_reports():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    storage = create_empty_mock_storage()
    generator = AIMBOMGenerator(storage)

    with pytest.raises(GeneratorMissingReportError):
        await generator.generate(
            GenerationMetadata(**get_generation_metadata(model_uuid, model_version)),
        )


@pytest.mark.anyio
async def test_storage_connection_failure():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    storage = MagicMock(spec=StorageClient)
    storage.get_reports_for_model.side_effect = StorageConnectionError("MinIO down")
    generator = AIMBOMGenerator(storage)

    with pytest.raises(GeneratorStorageError):
        await generator.generate(
            GenerationMetadata(**get_generation_metadata(model_uuid, model_version)),
        )


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
        await generator.generate(
            GenerationMetadata(**get_generation_metadata(model_uuid, model_version)),
        )


@pytest.mark.anyio
async def test_signing_material_mismatch_raises_signing_error():
    """A signing key/certificate mismatch (e.g. caught mid-rotation) is a
    distinct failure from a malformed report: it reflects the state of the
    signing material, not the input, so it must surface as
    GeneratorSigningError rather than GeneratorGenerationError."""

    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    storage = create_new_mock_storage()
    generator = AIMBOMGenerator(storage)

    with patch(
        "app.services.signing.sign_report",
        side_effect=SigningError("Signing key and certificate do not match"),
    ):
        with pytest.raises(GeneratorSigningError):
            await generator.generate(
                GenerationMetadata(**get_generation_metadata(model_uuid, model_version)),
            )


@pytest.mark.anyio
async def test_deprecate_invalid_new_report_data_is_rejected():
    # The update path must validate new reports through the same
    # _validate_reports used for new generations -- it used to skip the
    # generic CycloneDX check and only run the report-specific Pydantic
    # model.
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    storage = create_new_mock_storage()
    storage.data[
        f"reports/{model_uuid}/{model_version}/risk_report_updated.json"
    ] = {"invalid": "schema"}

    generator = AIMBOMGenerator(storage)

    with pytest.raises(GeneratorGenerationError):
        await generator.generate(
            GenerationMetadata(
                **get_generation_metadata_deprecation(model_uuid, model_version)
            ),
        )


@pytest.mark.anyio
async def test_create_updated_aimbom_increments_version_and_replaces_changed_refs():
    storage = create_empty_mock_storage()
    generator = AIMBOMGenerator(storage)

    previous_aimbom = AIMBOM(**load_json(AIMBOMS_DIR / "aimbom.json"))
    original_references = {
        ref.comment: ref for ref in previous_aimbom.external_references
    }

    new_reports = {
        ReportType.ASSESSMENTS: REPORT_MODELS[ReportType.ASSESSMENTS].model_validate(
            load_json(REPORTS_DIR / "assessment_report_updated.json")
        ),
        ReportType.RISK_REPORT: REPORT_MODELS[ReportType.RISK_REPORT].model_validate(
            load_json(REPORTS_DIR / "risk_report_updated.json")
        ),
    }

    aimbom = await generator._create_updated_aimbom(previous_aimbom, new_reports)

    # The version is incremented, but the serial number stays the same.
    assert aimbom.version == previous_aimbom.version + 1
    assert aimbom.serial_number == previous_aimbom.serial_number

    references = {ref.comment: ref for ref in aimbom.external_references}

    # Changed report types point at their new report's serial number/version.
    assert references[ReportComment.ASSESSMENTS].url == (
        "urn:cdx:bbc77e3c-ec17-42b1-af15-580626ea66d7/2"
    )
    assert references[ReportComment.RISK_REPORT].url == (
        "urn:cdx:689d20e1-38b1-4c07-bdcb-b5736440c2f7/2"
    )

    # Unchanged report types keep their original external reference untouched.
    unchanged_comments = [
        ReportComment.AI_MODEL_INFO,
        ReportComment.DATASETS,
        ReportComment.DEFENCES,
        ReportComment.EU_AI_ACT,
        ReportComment.GADGETS,
    ]
    for comment in unchanged_comments:
        assert references[comment].url == original_references[comment].url

    # Check that the re-signed AIMBOM's signature is valid and can be verified
    assert verify_signature(jsonable_encoder(aimbom, exclude_none=True)) is True


def test_validate_aimbom_raises_generation_error_on_invalid_schema():
    storage = create_empty_mock_storage()
    generator = AIMBOMGenerator(storage)

    aimbom = AIMBOM(**load_json(AIMBOMS_DIR / "aimbom.json"))

    with patch(
        "app.services.generator.validation.cdx_validate_dict",
        side_effect=ValueError("CycloneDX validation failed"),
    ):
        with pytest.raises(GeneratorGenerationError):
            generator._validate_aimbom(aimbom)


@pytest.mark.anyio
async def test_deprecate_success():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    storage = create_new_mock_storage()
    generator = AIMBOMGenerator(storage)

    aimbom = await generator.generate(
        GenerationMetadata(
            **get_generation_metadata_deprecation(model_uuid, model_version)
        ),
    )

    # Check that the serial numbers are valid URNs
    assert aimbom.serial_number.startswith("urn:uuid:")

    # Check that the version of the generated AIMBOM is incremented
    assert aimbom.version == 2

    # Check that the external references urls are as expected
    references = {ref.comment: ref for ref in aimbom.external_references}

    assert references[ReportComment.AI_MODEL_INFO].url == (
        "urn:cdx:2d2e6ba3-b9f2-4865-a182-9d31ea4d2f9e/1"
    )

    assert references[ReportComment.ASSESSMENTS].url == (
        "urn:cdx:bbc77e3c-ec17-42b1-af15-580626ea66d7/2"
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
        "urn:cdx:689d20e1-38b1-4c07-bdcb-b5736440c2f7/2"
    )

    # Check that the generated AIMBOM signature is valid and can be verified
    assert verify_signature(jsonable_encoder(aimbom, exclude_none=True)) is True


@pytest.mark.anyio
async def test_deprecate_with_gadgets_report_success():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    storage = create_new_mock_storage()
    generator = AIMBOMGenerator(storage)

    previous_aimbom = AIMBOM(**load_json(AIMBOMS_DIR / "aimbom.json"))
    original_references = {
        ref.comment: ref for ref in previous_aimbom.external_references
    }

    aimbom = await generator.generate(
        GenerationMetadata(
            **get_generation_metadata_deprecation_with_gadgets(
                model_uuid, model_version
            )
        ),
    )

    # The version is incremented, but the serial number stays the same.
    assert aimbom.version == previous_aimbom.version + 1
    assert aimbom.serial_number == previous_aimbom.serial_number

    references = {ref.comment: ref for ref in aimbom.external_references}

    # Changed report types point at their new report's serial number/version.
    assert references[ReportComment.ASSESSMENTS].url == (
        "urn:cdx:bbc77e3c-ec17-42b1-af15-580626ea66d7/2"
    )
    assert references[ReportComment.RISK_REPORT].url == (
        "urn:cdx:689d20e1-38b1-4c07-bdcb-b5736440c2f7/2"
    )
    assert references[ReportComment.GADGETS].url == (
        "urn:cdx:52c57fd2-b03a-44c1-b9c0-7c5f7d2a8666/2"
    )

    # Unchanged report types keep their original external reference untouched.
    unchanged_comments = [
        ReportComment.AI_MODEL_INFO,
        ReportComment.DATASETS,
        ReportComment.DEFENCES,
        ReportComment.EU_AI_ACT,
    ]
    for comment in unchanged_comments:
        assert references[comment].url == original_references[comment].url

    # Each report type still has exactly one external reference.
    assert len(aimbom.external_references) == len(
        previous_aimbom.external_references
    )

    # Check that the re-signed AIMBOM's signature is valid and can be verified
    assert verify_signature(jsonable_encoder(aimbom, exclude_none=True)) is True


@pytest.mark.anyio
async def test_deprecate_without_gadgets_report_keeps_previous_gadgets_ref():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    storage = create_new_mock_storage()
    generator = AIMBOMGenerator(storage)

    previous_aimbom = AIMBOM(**load_json(AIMBOMS_DIR / "aimbom.json"))
    original_references = {
        ref.comment: ref for ref in previous_aimbom.external_references
    }

    aimbom = await generator.generate(
        GenerationMetadata(
            **get_generation_metadata_deprecation(model_uuid, model_version)
        ),
    )

    references = {ref.comment: ref for ref in aimbom.external_references}

    assert (
        references[ReportComment.GADGETS].url
        == original_references[ReportComment.GADGETS].url
    )


@pytest.mark.anyio
async def test_deprecate_invalid_gadgets_report_data_is_rejected():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    storage = create_new_mock_storage()
    storage.data[
        f"reports/{model_uuid}/{model_version}/gadgets_report_updated.json"
    ] = {"invalid": "schema"}

    generator = AIMBOMGenerator(storage)

    with pytest.raises(GeneratorGenerationError):
        await generator.generate(
            GenerationMetadata(
                **get_generation_metadata_deprecation_with_gadgets(
                    model_uuid, model_version
                )
            ),
        )
