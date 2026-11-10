from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.clients.storage_client import (
    StorageAuthError,
    StorageConnectionError,
    StorageInvalidFileError,
    StorageOperationError,
    get_storage_client,
)
from app.core.security import require_token
from app.main import app
from app.services.generator import (
    AIMBOMGenerator,
    GeneratorInvalidReportError,
    GeneratorStorageError,
    GeneratorUploadRejectedError,
    get_generator,
)
from app.services.report_signer import (
    ReportSigner,
    ReportSignerStorageError,
    ReportSignerUploadRejectedError,
    get_signer,
)
from app.services.signing import verify_report
from app.services.validator import get_validator
from httpx import ASGITransport, AsyncClient

from tests.utils import (
    MODEL_UUID,
    MODEL_VERSION,
    create_new_mock_storage,
    get_generation_metadata,
    get_generation_metadata_deprecation,
    get_signing_event,
)


@pytest.fixture
def get_mock_storage():
    return create_new_mock_storage()


@pytest.fixture(autouse=True)
def override_storage(get_mock_storage):
    app.dependency_overrides[get_storage_client] = lambda: get_mock_storage
    # Authentication is tested in test_security.py.
    app.dependency_overrides[require_token] = lambda: {}
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.anyio
async def test_get_status(client):
    response = await client.get("/api/status")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "operational"
    assert "version" in data


REPORT_URL = f"reports/{MODEL_UUID}/{MODEL_VERSION}"


@pytest.mark.anyio
async def test_sign_report(client, get_mock_storage):
    download_url = f"{REPORT_URL}/risk_report.json"

    response = await client.post("/api/sign", json=get_signing_event(download_url))

    assert response.status_code == 201
    data = response.json()
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
    verify_report(
        get_mock_storage.data[
            f"risk-reports/{MODEL_UUID}/{MODEL_VERSION}/risk_report.json"
        ]
    )


@pytest.mark.anyio
async def test_sign_report_missing_report(client):
    response = await client.post(
        "/api/sign", json=get_signing_event("reports/missing.json")
    )

    assert response.status_code == 409


@pytest.mark.anyio
async def test_sign_report_invalid_file(client, get_mock_storage):
    download_url = "reports/not_an_object.json"
    get_mock_storage.data[download_url] = ["not", "an", "object"]

    response = await client.post("/api/sign", json=get_signing_event(download_url))

    assert response.status_code == 422


@pytest.mark.anyio
async def test_sign_report_missing_original_file_id_is_invalid(client):
    event = get_signing_event(f"{REPORT_URL}/risk_report.json")
    del event["files"][0]["_id"]

    response = await client.post("/api/sign", json=event)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "error, expected_status",
    [
        (ReportSignerUploadRejectedError("rejected"), 422),
        (ReportSignerStorageError("storage down"), 503),
    ],
)
@pytest.mark.anyio
async def test_sign_report_error_status(client, error, expected_status):
    mock_signer = MagicMock(spec=ReportSigner)
    mock_signer.sign_and_upload = AsyncMock(side_effect=error)
    app.dependency_overrides[get_signer] = lambda: mock_signer

    response = await client.post(
        "/api/sign", json=get_signing_event(f"{REPORT_URL}/risk_report.json")
    )

    assert response.status_code == expected_status


@pytest.mark.anyio
async def test_generate_aimbom_success(client):
    response = await client.post(
        "/api/generate",
        json=get_generation_metadata(MODEL_UUID, MODEL_VERSION),
    )

    assert response.status_code == 201
    data = response.json()
    assert data["model_uuid"] == MODEL_UUID
    assert "aimbom_uuid" in data
    assert data["aimbom_version"] == 1


@pytest.mark.anyio
async def test_generate_aimbom_no_reports(client):
    response = await client.post(
        "/api/generate",
        json=get_generation_metadata("nonexistent_model", MODEL_VERSION),
    )

    assert response.status_code == 409


@pytest.mark.parametrize(
    "error, expected_status",
    [
        (GeneratorInvalidReportError("invalid"), 422),
        (GeneratorUploadRejectedError("rejected"), 422),
        (GeneratorStorageError("storage down"), 503),
    ],
)
@pytest.mark.anyio
async def test_generate_aimbom_error_status(client, error, expected_status):
    mock_generator = MagicMock(spec=AIMBOMGenerator)
    mock_generator.generate = AsyncMock(side_effect=error)
    app.dependency_overrides[get_generator] = lambda: mock_generator

    response = await client.post(
        "/api/generate",
        json=get_generation_metadata(MODEL_UUID, MODEL_VERSION),
    )

    assert response.status_code == expected_status


@pytest.mark.anyio
async def test_deprecate_aimbom_success(client):
    response = await client.post(
        "/api/generate",
        json=get_generation_metadata_deprecation(MODEL_UUID, MODEL_VERSION),
    )

    assert response.status_code == 201
    data = response.json()
    assert data["model_uuid"] == MODEL_UUID
    assert "aimbom_uuid" in data
    assert data["aimbom_version"] == 2


# ============ /api/validation ============

VALIDATION_URL = f"/api/validation/{MODEL_UUID}/{MODEL_VERSION}"
AIMBOM_URL = f"aimboms/{MODEL_UUID}/{MODEL_VERSION}/aimbom.json"
RISK_REPORT_URL = f"{REPORT_URL}/risk_report.json"


def assert_invalid(response):
    assert response.status_code == 200
    assert response.json()["status"] == "INVALID"
    assert response.json()["model_uuid"] == MODEL_UUID
    assert response.json()["model_version"] == MODEL_VERSION


@pytest.mark.anyio
async def test_validate_aimbom_valid(client):
    response = await client.get(VALIDATION_URL)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "VALID"
    assert data["model_uuid"] == MODEL_UUID
    assert data["model_version"] == MODEL_VERSION


@pytest.mark.anyio
async def test_validate_aimbom_not_found(client):
    response = await client.get("/api/validation/unknown/v1.0")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_validate_aimbom_invalid_aimbom_schema(client, get_mock_storage):
    get_mock_storage.data[AIMBOM_URL].pop("bomFormat")

    response = await client.get(VALIDATION_URL)

    assert_invalid(response)
    # Removing a field also breaks the signature, so check that the schema
    # check is what rejected it.
    assert "aimbom is invalid" in response.json()["detail"]


@pytest.mark.anyio
async def test_validate_aimbom_invalid_report(client, get_mock_storage):
    get_mock_storage.data[RISK_REPORT_URL] = {}

    response = await client.get(VALIDATION_URL)

    assert_invalid(response)
    assert "risk_report" in response.json()["detail"]


@pytest.mark.anyio
async def test_validate_aimbom_missing_report(client, get_mock_storage):
    del get_mock_storage.data[RISK_REPORT_URL]

    response = await client.get(VALIDATION_URL)

    assert_invalid(response)
    assert "risk_report" in response.json()["detail"]


@pytest.mark.anyio
async def test_validate_aimbom_wrong_reference(client, get_mock_storage):
    get_mock_storage.data[AIMBOM_URL]["externalReferences"][0]["url"] = (
        "urn:cdx:00000000-0000-0000-0000-000000000000/1"
    )

    # Skip signature verification, so the edited AIMBOM fails on the
    # reference and not on its signature.
    with patch("app.services.validator.signing.verify_report"):
        response = await client.get(VALIDATION_URL)

    assert_invalid(response)


@pytest.mark.anyio
async def test_validate_aimbom_tampered_aimbom(client, get_mock_storage):
    # Still a valid AIMBOM, so only its signature can reject it.
    get_mock_storage.data[AIMBOM_URL]["version"] = 2

    response = await client.get(VALIDATION_URL)

    assert_invalid(response)


@pytest.mark.anyio
async def test_validate_aimbom_tampered_report(client, get_mock_storage):
    # Still a valid report, so only its signature can reject it.
    get_mock_storage.data[RISK_REPORT_URL]["metadata"]["timestamp"] = (
        "2000-01-01T00:00:00Z"
    )

    response = await client.get(VALIDATION_URL)

    assert_invalid(response)


@pytest.mark.anyio
async def test_validate_aimbom_file_not_json(client, get_mock_storage):
    get_mock_storage.get_aimbom = AsyncMock(
        side_effect=StorageInvalidFileError("File is not valid JSON")
    )

    response = await client.get(VALIDATION_URL)

    assert_invalid(response)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error, expected_status",
    [
        (StorageConnectionError("Orchestrator returned 500"), 503),
        (StorageAuthError("token request failed"), 503),
        (StorageOperationError("Orchestrator returned 403"), 500),
    ],
)
async def test_validate_aimbom_storage_failure_is_not_invalid(
    client, get_mock_storage, error, expected_status
):
    get_mock_storage.get_aimbom = AsyncMock(side_effect=error)

    response = await client.get(VALIDATION_URL)

    assert response.status_code == expected_status
    assert "status" not in response.json()


@pytest.mark.parametrize(
    "dependency, method, send",
    [
        (
            get_signer,
            "sign_and_upload",
            lambda client: client.post(
                "/api/sign", json=get_signing_event(f"{REPORT_URL}/risk_report.json")
            ),
        ),
        (
            get_generator,
            "generate",
            lambda client: client.post(
                "/api/generate",
                json=get_generation_metadata(MODEL_UUID, MODEL_VERSION),
            ),
        ),
        (
            get_validator,
            "validate_aimbom",
            lambda client: client.get(VALIDATION_URL),
        ),
    ],
)
@pytest.mark.anyio
async def test_unexpected_error_does_not_expose_its_message(
    client, dependency, method, send
):
    service = MagicMock()
    setattr(service, method, AsyncMock(side_effect=KeyError("secret internals")))
    app.dependency_overrides[dependency] = lambda: service

    response = await send(client)

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
