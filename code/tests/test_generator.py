from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.clients.storage_client import StorageClient, StorageConnectionError
from app.models.aimbom import AIMBOM
from app.models.requests import GenerationMetadata
from app.services.generator import (
    AIMBOMGenerator,
    GeneratorGenerationError,
    GeneratorInvalidReportError,
    GeneratorMissingReportError,
    GeneratorSigningError,
    GeneratorStorageError,
)
from app.services.signing import SigningError, verify_report
from app.utils.utils import ReportComment, ReportType
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
)

# The report behind each external reference of an AIMBOM, for a new generation.
REPORT_FILES = {
    ReportComment.AI_MODEL_INFO: "aimodelinfo_report.json",
    ReportComment.ASSESSMENTS: "assessment_report.json",
    ReportComment.DATASETS: "datasets_report.json",
    ReportComment.DEFENCES: "defence_report.json",
    ReportComment.EU_AI_ACT: "euaiact_report.json",
    ReportComment.GADGETS: "gadgets_report.json",
    ReportComment.RISK_REPORT: "risk_report.json",
}


def report_link(filename: str) -> str:
    """The BOM-Link an AIMBOM should use to reference a report fixture."""

    report = load_json(REPORTS_DIR / filename)
    report_uuid = report["serialNumber"].removeprefix("urn:uuid:")
    # CycloneDX documents without a version are at version 1.
    return f"urn:cdx:{report_uuid}/{report.get('version', 1)}"


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

    for comment, filename in REPORT_FILES.items():
        assert references[comment].url == report_link(filename)

    # Check that the generated AIMBOM signature is valid and can be verified
    verify_report(jsonable_encoder(aimbom, exclude_none=True))

    # Check that the generated AIMBOM reached storage
    assert storage.data[
        f"aimboms/{model_uuid}/{model_version}/aimbom.json"
    ] == jsonable_encoder(aimbom, exclude_none=True)


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

    with pytest.raises(GeneratorInvalidReportError):
        await generator.generate(
            GenerationMetadata(**get_generation_metadata(model_uuid, model_version)),
        )


@pytest.mark.anyio
async def test_tampered_report_signature_is_rejected():
    storage = create_new_mock_storage()
    risk_report_url = f"reports/{MODEL_UUID}/{MODEL_VERSION}/risk_report.json"
    storage.data[risk_report_url]["metadata"]["timestamp"] = "2000-01-01T00:00:00Z"

    generator = AIMBOMGenerator(storage)

    with pytest.raises(GeneratorInvalidReportError):
        await generator.generate(
            GenerationMetadata(**get_generation_metadata(MODEL_UUID, MODEL_VERSION)),
        )


def test_validate_aimbom_raises_generation_error_on_invalid_signature():
    generator = AIMBOMGenerator(create_empty_mock_storage())

    aimbom = AIMBOM(**load_json(AIMBOMS_DIR / "aimbom.json"))
    aimbom.version = 2  # No longer matches its signature

    with pytest.raises(GeneratorGenerationError):
        generator._validate_aimbom(aimbom)


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
                GenerationMetadata(
                    **get_generation_metadata(model_uuid, model_version)
                ),
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
    storage.data[f"reports/{model_uuid}/{model_version}/risk_report_updated.json"] = {
        "invalid": "schema"
    }

    generator = AIMBOMGenerator(storage)

    with pytest.raises(GeneratorInvalidReportError):
        await generator.generate(
            GenerationMetadata(
                **get_generation_metadata_deprecation(model_uuid, model_version)
            ),
        )


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

    updated_files = {
        **REPORT_FILES,
        ReportComment.ASSESSMENTS: "assessment_report_updated.json",
        ReportComment.RISK_REPORT: "risk_report_updated.json",
    }
    for comment, filename in updated_files.items():
        assert references[comment].url == report_link(filename)

    # Check that the generated AIMBOM signature is valid and can be verified
    verify_report(jsonable_encoder(aimbom, exclude_none=True))


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
    assert references[ReportComment.ASSESSMENTS].url == report_link(
        "assessment_report_updated.json"
    )
    assert references[ReportComment.RISK_REPORT].url == report_link(
        "risk_report_updated.json"
    )
    assert references[ReportComment.GADGETS].url == report_link(
        "gadgets_report_updated.json"
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
    assert len(aimbom.external_references) == len(previous_aimbom.external_references)

    # Check that the re-signed AIMBOM's signature is valid and can be verified
    verify_report(jsonable_encoder(aimbom, exclude_none=True))
