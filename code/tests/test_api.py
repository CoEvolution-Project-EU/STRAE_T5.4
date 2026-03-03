import pytest
from fastapi.testclient import TestClient

from app.db import get_minio_client
from app.main import app
from tests.utils import create_new_mock_minio


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


def test_generate_aimbom_success():
    model_id = "model-123"

    response = client.post(f"/api/generate/{model_id}")

    assert response.status_code == 201
    data = response.json()
    assert data["model_id"] == model_id
    assert "id" in data


def test_generate_aimbom_no_reports():
    model_id = "nonexistent_model"
    response = client.post(f"/api/generate/{model_id}")
    assert response.status_code == 409
