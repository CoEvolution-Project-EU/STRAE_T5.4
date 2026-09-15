import pytest
from app.clients.storage_client import get_storage_client
from app.main import app
from httpx import ASGITransport, AsyncClient

from tests.utils import (
    MODEL_UUID,
    MODEL_VERSION,
    create_new_mock_storage,
    get_generation_metadata,
    get_generation_metadata_deprecation,
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
