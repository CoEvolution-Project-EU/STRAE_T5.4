from unittest.mock import AsyncMock

import pytest
from app.clients.storage_client import (
    StorageBadRequestError,
    StorageConflictError,
    StorageConnectionError,
)
from app.models.requests import SigningMetadata
from app.services.report_signer import (
    ReportSigner,
    ReportSignerMissingReportError,
    ReportSignerStorageError,
    ReportSignerUploadRejectedError,
)

from tests.utils import (
    MODEL_UUID,
    MODEL_VERSION,
    create_new_mock_storage,
    get_signing_event,
    verify_signature,
)

REPORT_URL = f"reports/{MODEL_UUID}/{MODEL_VERSION}"


def _signing_metadata(*download_urls: str) -> SigningMetadata:
    return SigningMetadata.model_validate(get_signing_event(*download_urls))


@pytest.mark.anyio
async def test_sign_and_upload_multiple_files():
    storage = create_new_mock_storage()
    signer = ReportSigner(storage)

    await signer.sign_and_upload(
        _signing_metadata(
            f"{REPORT_URL}/risk_report.json", f"{REPORT_URL}/assessment_report.json"
        )
    )

    # One upload per file, each with the ID of its original
    assert [upload.original_file_id for upload in storage.uploads] == [
        "original-0",
        "original-1",
    ]
    for upload in storage.uploads:
        assert upload.pool == "RP"
        assert upload.bucket == "risk-reports"

    for filename in ("risk_report.json", "assessment_report.json"):
        signed_report = storage.data[
            f"risk-reports/{MODEL_UUID}/{MODEL_VERSION}/{filename}"
        ]
        assert verify_signature(signed_report) is True


@pytest.mark.anyio
async def test_already_signed_file_is_treated_as_done():
    storage = create_new_mock_storage()
    storage.save_file = AsyncMock(side_effect=StorageConflictError("409"))
    signer = ReportSigner(storage)

    await signer.sign_and_upload(_signing_metadata(f"{REPORT_URL}/risk_report.json"))

    storage.save_file.assert_awaited_once()


@pytest.mark.anyio
async def test_rejected_upload_raises_upload_rejected_error():
    storage = create_new_mock_storage()
    storage.save_file = AsyncMock(side_effect=StorageBadRequestError("400"))
    signer = ReportSigner(storage)

    with pytest.raises(ReportSignerUploadRejectedError):
        await signer.sign_and_upload(
            _signing_metadata(f"{REPORT_URL}/risk_report.json")
        )


@pytest.mark.anyio
async def test_missing_file_does_not_stop_other_files():
    storage = create_new_mock_storage()
    signer = ReportSigner(storage)

    with pytest.raises(ReportSignerMissingReportError) as exc_info:
        await signer.sign_and_upload(
            _signing_metadata(
                "reports/missing-1.json",
                f"{REPORT_URL}/risk_report.json",
                "reports/missing-2.json",
            )
        )

    # Both failures are reported, and the valid file in between is uploaded
    assert "reports/missing-1.json" in str(exc_info.value)
    assert "reports/missing-2.json" in str(exc_info.value)
    assert [upload.original_file_id for upload in storage.uploads] == ["original-1"]


@pytest.mark.anyio
async def test_storage_error_stops_remaining_files():
    storage = create_new_mock_storage()
    storage.save_file = AsyncMock(side_effect=StorageConnectionError("down"))
    signer = ReportSigner(storage)

    with pytest.raises(ReportSignerStorageError):
        await signer.sign_and_upload(
            _signing_metadata(
                f"{REPORT_URL}/risk_report.json",
                f"{REPORT_URL}/assessment_report.json",
            )
        )

    storage.save_file.assert_awaited_once()
