from unittest.mock import AsyncMock, MagicMock

import pytest
from app.clients.storage_client import get_storage_client
from app.main import app
from app.services.generator import (
    AIMBOMGenerator,
    GeneratorGenerationError,
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


@pytest.mark.anyio
async def test_sign_report():
    report = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "serialNumber": "urn:uuid:test",
        "version": 1,
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post("/api/sign", json=report)

    assert response.status_code == 200
    data = response.json()
    assert data["detail"] == "Report signed successfully"
    assert "signed_report" in data
    assert data["signed_report"]["signature"]["algorithm"] == "ES256"
    assert data["signed_report"]["signature"]["value"]


@pytest.mark.anyio
async def test_generate_aimbom_success():
    model_uuid = MODEL_UUID
    model_version = MODEL_VERSION

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            f"/api/generate/{model_uuid}/{model_version}",
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
            f"/api/generate/{model_uuid}/{model_version}",
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
            f"/api/generate/{MODEL_UUID}/{MODEL_VERSION}",
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
            f"/api/generate/{MODEL_UUID}/{MODEL_VERSION}",
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
            f"/api/generate/{MODEL_UUID}/{MODEL_VERSION}",
            json=get_generation_metadata(MODEL_UUID, MODEL_VERSION),
        )

    assert response.status_code == 500


@pytest.mark.anyio
async def test_generate_aimbom_unexpected_error():
    mock_generator = MagicMock(spec=AIMBOMGenerator)
    mock_generator.generate = AsyncMock(side_effect=RuntimeError("boom"))
    app.dependency_overrides[get_generator] = lambda: mock_generator

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            f"/api/generate/{MODEL_UUID}/{MODEL_VERSION}",
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
            f"/api/generate/{model_uuid}/{model_version}",
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
            f"/api/generate/{model_uuid}/{model_version}",
            json=get_generation_metadata_deprecation_with_gadgets(
                model_uuid, model_version
            ),
        )

    assert response.status_code == 201
    data = response.json()
    assert data["model_uuid"] == model_uuid
    assert "aimbom_uuid" in data
    assert data["aimbom_version"] == 2
