from unittest.mock import AsyncMock, MagicMock

import pytest
from app.clients.storage_client import (
    StorageConflictError,
    StorageConnectionError,
    get_storage_client,
)
from app.main import app
from app.services.generator import (
    AIMBOMGenerator,
    GeneratorGenerationError,
    GeneratorInvalidReportError,
    GeneratorSigningError,
    GeneratorStorageError,
    get_generator,
)
from httpx import ASGITransport, AsyncClient

from tests.utils import (
    MODEL_UUID,
    MODEL_VERSION,
    create_new_mock_storage,
    get_generation_metadata,
    get_generation_metadata_deprecation,
    get_generation_metadata_deprecation_with_gadgets,
    get_signing_event,
    verify_signature,
)


@pytest.fixture
def get_mock_storage():
    return create_new_mock_storage()


@pytest.fixture(autouse=True)
def override_storage(get_mock_storage):
    app.dependency_overrides[get_storage_client] = lambda: get_mock_storage
    yield
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_get_status():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/status")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "operational"
    assert "version" in data


REPORT_URL = f"reports/{MODEL_UUID}/{MODEL_VERSION}"


@pytest.mark.anyio
async def test_sign_report(get_mock_storage):
    download_url = f"{REPORT_URL}/risk_report.json"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post("/api/sign", json=get_signing_event(download_url))

    assert response.status_code == 201
    data = response.json()
    assert data["detail"] == "Reports signed successfully"
    assert data["target_pool"] == "RP"
    assert data["target_bucket"] == "risk-reports"
    assert data["model_uuid"] == MODEL_UUID
    assert data["model_version"] == MODEL_VERSION
    assert data["files"] == [
        {"original_file_id": "original-0", "filename": "risk_report.json"}
    ]
    assert data["signed"] == 1
    assert data["already_signed"] == 0

    # Check that the uploaded report is signed and its signature can be verified
    signed_report = get_mock_storage.data[
        f"risk-reports/{MODEL_UUID}/{MODEL_VERSION}/risk_report.json"
    ]
    assert verify_signature(signed_report) is True


@pytest.mark.anyio
async def test_sign_multiple_reports(get_mock_storage):
    event = get_signing_event(
        f"{REPORT_URL}/risk_report.json", f"{REPORT_URL}/assessment_report.json"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post("/api/sign", json=event)

    assert response.status_code == 201
    assert [file["filename"] for file in response.json()["files"]] == [
        "risk_report.json",
        "assessment_report.json",
    ]

    for filename in ("risk_report.json", "assessment_report.json"):
        signed_report = get_mock_storage.data[
            f"risk-reports/{MODEL_UUID}/{MODEL_VERSION}/{filename}"
        ]
        assert verify_signature(signed_report) is True


@pytest.mark.anyio
async def test_sign_reports_counts_already_signed_files(get_mock_storage):
    get_mock_storage.save_file = AsyncMock(
        side_effect=[StorageConflictError("409"), None]
    )
    event = get_signing_event(
        f"{REPORT_URL}/risk_report.json", f"{REPORT_URL}/assessment_report.json"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post("/api/sign", json=event)

    assert response.status_code == 201
    assert response.json()["signed"] == 1
    assert response.json()["already_signed"] == 1


@pytest.mark.anyio
async def test_sign_report_missing_report():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/sign", json=get_signing_event("reports/missing.json")
        )

    assert response.status_code == 409


@pytest.mark.anyio
async def test_sign_report_missing_report_still_signs_other_files(get_mock_storage):
    event = get_signing_event(
        "reports/missing.json", f"{REPORT_URL}/risk_report.json"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post("/api/sign", json=event)

    assert response.status_code == 409
    assert "reports/missing.json" in response.json()["detail"]
    assert (
        f"risk-reports/{MODEL_UUID}/{MODEL_VERSION}/risk_report.json"
        in get_mock_storage.data
    )


@pytest.mark.anyio
async def test_sign_report_invalid_file(get_mock_storage):
    download_url = "reports/not_an_object.json"
    get_mock_storage.data[download_url] = ["not", "an", "object"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post("/api/sign", json=get_signing_event(download_url))

    assert response.status_code == 422


@pytest.mark.anyio
async def test_sign_report_missing_original_file_id_is_invalid():
    event = get_signing_event(f"{REPORT_URL}/risk_report.json")
    del event["files"][0]["_id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post("/api/sign", json=event)

    assert response.status_code == 422


@pytest.mark.anyio
async def test_generate_aimbom_success():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/generate",
            json=get_generation_metadata(model_uuid, model_version),
        )

    assert response.status_code == 201
    data = response.json()
    assert data["model_uuid"] == model_uuid
    assert "aimbom_uuid" in data
    assert data["aimbom_version"] == 1


@pytest.mark.anyio
async def test_generate_aimbom_no_reports():
    model_uuid = "nonexistent_model"
    model_version = MODEL_VERSION

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/generate",
            json=get_generation_metadata(model_uuid, model_version),
        )
    assert response.status_code == 409


@pytest.mark.anyio
async def test_generate_aimbom_storage_error():
    mock_generator = MagicMock(spec=AIMBOMGenerator)
    mock_generator.generate = AsyncMock(
        side_effect=GeneratorStorageError("Failed to retrieve reports from MinIO")
    )
    app.dependency_overrides[get_generator] = lambda: mock_generator

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/generate",
            json=get_generation_metadata(MODEL_UUID, MODEL_VERSION),
        )

    assert response.status_code == 503


@pytest.mark.anyio
async def test_generate_aimbom_signing_error():
    mock_generator = MagicMock(spec=AIMBOMGenerator)
    mock_generator.generate = AsyncMock(
        side_effect=GeneratorSigningError("Signing key and certificate do not match")
    )
    app.dependency_overrides[get_generator] = lambda: mock_generator

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/generate",
            json=get_generation_metadata(MODEL_UUID, MODEL_VERSION),
        )

    assert response.status_code == 503


@pytest.mark.anyio
async def test_generate_aimbom_generation_error():
    mock_generator = MagicMock(spec=AIMBOMGenerator)
    mock_generator.generate = AsyncMock(
        side_effect=GeneratorGenerationError("Generated AIMBOM is invalid")
    )
    app.dependency_overrides[get_generator] = lambda: mock_generator

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/generate",
            json=get_generation_metadata(MODEL_UUID, MODEL_VERSION),
        )

    assert response.status_code == 500


@pytest.mark.anyio
async def test_generate_aimbom_invalid_report_error():
    mock_generator = MagicMock(spec=AIMBOMGenerator)
    mock_generator.generate = AsyncMock(
        side_effect=GeneratorInvalidReportError("Report risk_report is invalid")
    )
    app.dependency_overrides[get_generator] = lambda: mock_generator

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/generate",
            json=get_generation_metadata(MODEL_UUID, MODEL_VERSION),
        )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_generate_aimbom_unexpected_error():
    mock_generator = MagicMock(spec=AIMBOMGenerator)
    mock_generator.generate = AsyncMock(side_effect=RuntimeError("boom"))
    app.dependency_overrides[get_generator] = lambda: mock_generator

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/generate",
            json=get_generation_metadata(MODEL_UUID, MODEL_VERSION),
        )

    assert response.status_code == 500


@pytest.mark.anyio
async def test_deprecate_aimbom_success():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/generate",
            json=get_generation_metadata_deprecation(model_uuid, model_version),
        )

    assert response.status_code == 201
    data = response.json()
    assert data["model_uuid"] == model_uuid
    assert "aimbom_uuid" in data
    assert data["aimbom_version"] == 2


@pytest.mark.anyio
async def test_deprecate_aimbom_with_gadgets_report_success():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/generate",
            json=get_generation_metadata_deprecation_with_gadgets(
                model_uuid, model_version
            ),
        )

    assert response.status_code == 201
    data = response.json()
    assert data["model_uuid"] == model_uuid
    assert "aimbom_uuid" in data
    assert data["aimbom_version"] == 2


# ============ /api/validation ============

VALIDATION_URL = f"/api/validation/{MODEL_UUID}/{MODEL_VERSION}"
AIMBOM_URL = f"aimboms/{MODEL_UUID}/{MODEL_VERSION}/aimbom.json"


async def get_validation(url: str = VALIDATION_URL):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        return await ac.get(url)


@pytest.mark.anyio
async def test_validate_aimbom_valid():
    response = await get_validation()

    assert response.status_code == 200
    assert response.json() == {"detail": "AIMBOM is valid", "valid": True}


@pytest.mark.anyio
async def test_validate_aimbom_not_found():
    response = await get_validation("/api/validation/unknown/v1.0")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_validate_aimbom_invalid_aimbom_schema(get_mock_storage):
    get_mock_storage.data[AIMBOM_URL].pop("bomFormat")

    response = await get_validation()

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert "aimbom" in response.json()["detail"]


@pytest.mark.anyio
async def test_validate_aimbom_invalid_report(get_mock_storage):
    get_mock_storage.data[f"{REPORT_URL}/risk_report.json"] = {}

    response = await get_validation()

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert "risk_report" in response.json()["detail"]


@pytest.mark.anyio
async def test_validate_aimbom_missing_report(get_mock_storage):
    del get_mock_storage.data[f"{REPORT_URL}/risk_report.json"]

    response = await get_validation()

    assert response.status_code == 200
    assert response.json()["valid"] is False


@pytest.mark.anyio
async def test_validate_aimbom_wrong_reference(get_mock_storage):
    get_mock_storage.data[AIMBOM_URL]["externalReferences"][0]["url"] = (
        "urn:cdx:00000000-0000-0000-0000-000000000000/1"
    )

    response = await get_validation()

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert "references" in response.json()["detail"]


@pytest.mark.anyio
async def test_validate_aimbom_storage_unavailable(get_mock_storage):
    get_mock_storage.get_aimbom = AsyncMock(
        side_effect=StorageConnectionError("storage down")
    )

    response = await get_validation()

    assert response.status_code == 503

