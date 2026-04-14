import pytest
from app.db import get_minio_client
from app.main import app
from fastapi.testclient import TestClient

from tests.utils import MODEL_UUID, create_new_mock_minio


@pytest.fixture
def get_mock_minio():
    return create_new_mock_minio()


@pytest.fixture(autouse=True)
def override_minio(get_mock_minio):
    app.dependency_overrides[get_minio_client] = lambda: get_mock_minio
    yield
    app.dependency_overrides.clear()


client = TestClient(app)


def test_get_status():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "operational"
    assert "version" in data


def test_sign_report():
    report = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "serialNumber": "urn:uuid:test",
        "version": 1,
    }
    response = client.post("/api/sign", json=report)

    assert response.status_code == 200
    data = response.json()
    assert data["detail"] == "Report signed successfully"
    assert "signed_report" in data
    assert data["signed_report"]["signature"]["algorithm"] == "ES256"
    assert data["signed_report"]["signature"]["value"]


def test_generate_aimbom_success():
    model_uuid = MODEL_UUID

    response = client.post(f"/api/generate/{model_uuid}")

    assert response.status_code == 201
    data = response.json()
    assert data["model_uuid"] == model_uuid
    assert "id" in data


def test_generate_aimbom_no_reports():
    model_uuid = "nonexistent_model"
    response = client.post(f"/api/generate/{model_uuid}")
    assert response.status_code == 409
