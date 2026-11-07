import httpx
import pytest
from app.clients.orchestrator_client import OrchestratorClient
from app.clients.storage_client import (
    StorageBadRequestError,
    StorageConflictError,
    StorageConnectionError,
    StorageInvalidFileError,
    StorageNotFoundError,
    StorageOperationError,
)
from app.models.storage import UploadReportMetadata
from app.utils.utils import ReportType

from tests.utils import MODEL_UUID, MODEL_VERSION

BASE_URL = "https://orchestrator.test/api/v1/"
LATEST_PATH = f"/api/v1/models/{MODEL_UUID}/versions/{MODEL_VERSION}/latest"
DOWNLOAD_URL = "https://orchestrator.test/api/v1/files/download/"


def file_entry(file_id: str) -> dict:
    return {
        "_id": file_id,
        "bucket": "bucket",
        "filename": f"{file_id}.json",
        "download_url": f"{DOWNLOAD_URL}{file_id}",
        "createdAt": "2026-11-01T15:38:00.113Z",
    }


def latest_response(missing=()) -> dict:
    reports = {
        report_type.value: None
        if report_type.value in missing
        else file_entry(report_type.value)
        for report_type in ReportType
    }
    reports["aimbom_report"] = file_entry("aimbom")
    return {
        "model_name": "MySecurityModel",
        "model_uuid": MODEL_UUID,
        "version": MODEL_VERSION,
        "trusted": False,
        "reports": reports,
        "missing": list(missing),
    }


def make_client(
    latest_status=200, latest_json=None, download_responses=None
) -> tuple[OrchestratorClient, list]:
    """Client against a fake orchestrator. Downloads return `{"id": <file id>}`,
    unless `download_responses` has a response for that file id.
    """

    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == LATEST_PATH:
            return httpx.Response(latest_status, json=latest_json)
        file_id = request.url.path.rsplit("/", 1)[1]
        if download_responses and file_id in download_responses:
            return download_responses[file_id]
        return httpx.Response(200, json={"id": file_id})

    client = httpx.AsyncClient(
        base_url=BASE_URL, transport=httpx.MockTransport(handler)
    )
    # `/latest` and the downloads don't authenticate, so no auth is needed.
    return OrchestratorClient(client=client, auth=None), requests


@pytest.mark.anyio
async def test_get_aimbom_returns_aimbom_and_reports_by_type():
    client, _ = make_client(latest_json=latest_response())

    aimbom, reports = await client.get_aimbom(MODEL_UUID, MODEL_VERSION)

    assert aimbom == {"id": "aimbom"}
    assert reports == {
        report_type.value: {"id": report_type.value} for report_type in ReportType
    }


@pytest.mark.anyio
async def test_get_aimbom_leaves_out_missing_reports():
    client, _ = make_client(latest_json=latest_response(missing=["risk_report"]))

    _, reports = await client.get_aimbom(MODEL_UUID, MODEL_VERSION)

    assert "risk_report" not in reports
    assert len(reports) == len(ReportType) - 1


@pytest.mark.anyio
async def test_get_aimbom_without_aimbom_raises_not_found():
    latest = latest_response()
    latest["reports"]["aimbom_report"] = None
    client, _ = make_client(latest_json=latest)

    with pytest.raises(StorageNotFoundError, match="No AIMBOM"):
        await client.get_aimbom(MODEL_UUID, MODEL_VERSION)


@pytest.mark.anyio
async def test_get_aimbom_unknown_model_raises_not_found():
    client, _ = make_client(latest_status=404, latest_json={"detail": "not found"})

    with pytest.raises(StorageNotFoundError, match="Model not found"):
        await client.get_aimbom(MODEL_UUID, MODEL_VERSION)


@pytest.mark.anyio
async def test_get_aimbom_server_error_raises_connection_error():
    client, _ = make_client(latest_status=503, latest_json={})

    with pytest.raises(StorageConnectionError):
        await client.get_aimbom(MODEL_UUID, MODEL_VERSION)


@pytest.mark.anyio
async def test_get_aimbom_client_error_raises_operation_error():
    client, _ = make_client(latest_status=400, latest_json={})

    with pytest.raises(StorageOperationError, match="400"):
        await client.get_aimbom(MODEL_UUID, MODEL_VERSION)


@pytest.mark.anyio
async def test_get_aimbom_malformed_latest_response_is_not_an_invalid_file():
    client, _ = make_client(latest_json={"model_uuid": MODEL_UUID})

    with pytest.raises(StorageOperationError) as exc_info:
        await client.get_aimbom(MODEL_UUID, MODEL_VERSION)

    assert not isinstance(exc_info.value, StorageInvalidFileError)


@pytest.mark.anyio
async def test_get_aimbom_latest_response_not_an_object_raises_operation_error():
    client, _ = make_client(latest_json=[])

    with pytest.raises(StorageOperationError, match="no 'reports'"):
        await client.get_aimbom(MODEL_UUID, MODEL_VERSION)


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["aimbom_report", "risk_report"])
@pytest.mark.parametrize(
    "entry",
    [
        {"_id": "id", "filename": "file.json"},
        {"_id": "id", "download_url": None},
        {"_id": "id", "download_url": 1},
        "not an object",
    ],
)
async def test_get_aimbom_entry_without_download_url_raises_operation_error(
    name, entry
):
    latest = latest_response()
    latest["reports"][name] = entry
    client, _ = make_client(latest_json=latest)

    with pytest.raises(StorageOperationError, match=f"'download_url' for '{name}'"):
        await client.get_aimbom(MODEL_UUID, MODEL_VERSION)


@pytest.mark.anyio
async def test_get_aimbom_leaves_out_report_whose_file_does_not_exist():
    client, _ = make_client(
        latest_json=latest_response(),
        download_responses={"risk_report": httpx.Response(404)},
    )

    _, reports = await client.get_aimbom(MODEL_UUID, MODEL_VERSION)

    assert "risk_report" not in reports
    assert len(reports) == len(ReportType) - 1


@pytest.mark.anyio
async def test_get_aimbom_aimbom_file_does_not_exist_raises_not_found():
    client, _ = make_client(
        latest_json=latest_response(),
        download_responses={"aimbom": httpx.Response(404)},
    )

    with pytest.raises(StorageNotFoundError):
        await client.get_aimbom(MODEL_UUID, MODEL_VERSION)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status_code, expected_error",
    [(500, StorageConnectionError), (403, StorageOperationError)],
)
async def test_get_aimbom_report_download_failure_raises(status_code, expected_error):
    client, _ = make_client(
        latest_json=latest_response(),
        download_responses={"risk_report": httpx.Response(status_code)},
    )

    with pytest.raises(expected_error, match=str(status_code)):
        await client.get_aimbom(MODEL_UUID, MODEL_VERSION)


@pytest.mark.anyio
async def test_get_aimbom_report_not_json_raises_invalid_file():
    client, _ = make_client(
        latest_json=latest_response(),
        download_responses={"risk_report": httpx.Response(200, text="not json")},
    )

    with pytest.raises(StorageInvalidFileError):
        await client.get_aimbom(MODEL_UUID, MODEL_VERSION)


class FakeAuth:
    async def get_token(self) -> str:
        return "token"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status_code, expected_error",
    [
        (500, StorageConnectionError),
        (503, StorageConnectionError),
        (400, StorageBadRequestError),
        (409, StorageConflictError),
        (403, StorageOperationError),
    ],
)
async def test_upload_failure_raises(status_code, expected_error):
    client = OrchestratorClient(
        client=httpx.AsyncClient(
            base_url=BASE_URL,
            transport=httpx.MockTransport(lambda request: httpx.Response(status_code)),
        ),
        auth=FakeAuth(),
    )

    with pytest.raises(expected_error, match=str(status_code)):
        await client.save_file(
            file={"id": "signed"},
            filename="signed.json",
            upload_report_metadata=UploadReportMetadata(
                model_uuid=MODEL_UUID,
                version=MODEL_VERSION,
                pool="pool",
                bucket="bucket",
                original_file_id="original-1",
            ),
        )
