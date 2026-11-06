import json
from unittest.mock import MagicMock

import pytest
from app.clients.minio_client import MinioClient
from app.clients.storage_client import (
    StorageConnectionError,
    StorageNotFoundError,
    StorageOperationError,
)
from app.utils.utils import ReportType
from minio import S3Error

from tests.utils import MODEL_UUID, MODEL_VERSION

RISK_REPORT_KEY = f"{MODEL_UUID}/{MODEL_VERSION}/risk_report.json"


def s3_error(code: str) -> S3Error:
    return S3Error(MagicMock(), code, code, None, None, None)


def make_client(failures=None) -> MinioClient:
    """Client against a fake MinIO with one AIMBOM. Downloads return
    `{"id": <object name>}`, unless `failures` has an error for that object.
    """

    failures = failures or {}

    def get_object(bucket_name, object_name):
        if object_name in failures:
            raise failures[object_name]
        response = MagicMock()
        response.read.return_value = json.dumps({"id": object_name})
        return response

    minio = MagicMock()
    minio.get_object.side_effect = get_object
    minio.list_objects.return_value = [
        MagicMock(
            is_dir=False,
            object_name=f"{MODEL_UUID}/{MODEL_VERSION}/aimbom-v1.json",
            last_modified=1,
        )
    ]
    return MinioClient(client=minio)


@pytest.mark.anyio
async def test_get_aimbom_returns_aimbom_and_reports_by_type():
    aimbom, reports = await make_client().get_aimbom(MODEL_UUID, MODEL_VERSION)

    assert aimbom == {"id": f"{MODEL_UUID}/{MODEL_VERSION}/aimbom-v1.json"}
    assert set(reports) == {report_type.value for report_type in ReportType}


@pytest.mark.anyio
async def test_get_aimbom_leaves_out_report_that_does_not_exist():
    client = make_client({RISK_REPORT_KEY: s3_error("NoSuchKey")})

    _, reports = await client.get_aimbom(MODEL_UUID, MODEL_VERSION)

    assert "risk_report" not in reports
    assert len(reports) == len(ReportType) - 1


@pytest.mark.anyio
async def test_get_aimbom_without_aimbom_raises_not_found():
    client = make_client()
    client.client.list_objects.return_value = []

    with pytest.raises(StorageNotFoundError):
        await client.get_aimbom(MODEL_UUID, MODEL_VERSION)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure, expected_error",
    [
        (s3_error("AccessDenied"), StorageOperationError),
        (OSError("connection refused"), StorageConnectionError),
    ],
)
async def test_get_aimbom_report_download_failure_raises(failure, expected_error):
    client = make_client({RISK_REPORT_KEY: failure})

    with pytest.raises(expected_error) as exc_info:
        await client.get_aimbom(MODEL_UUID, MODEL_VERSION)

    assert not isinstance(exc_info.value, StorageNotFoundError)
