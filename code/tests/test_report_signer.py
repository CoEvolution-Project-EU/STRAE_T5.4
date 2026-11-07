from unittest.mock import AsyncMock, patch

import pytest
from app.clients.storage_client import (
    StorageAuthError,
    StorageBadRequestError,
    StorageConflictError,
    StorageConnectionError,
    StorageOperationError,
)
from app.models.requests import SigningMetadata
from app.services.report_signer import (
    ReportSigner,
    ReportSignerMissingReportError,
    ReportSignerProcessingError,
    ReportSignerSigningError,
    ReportSignerStorageError,
    ReportSignerUploadRejectedError,
    SigningResult,
)
from app.services.signing import SigningError, verify_report

from tests.utils import (
    MODEL_UUID,
    MODEL_VERSION,
    create_new_mock_storage,
    get_signing_event,
)

REPORT_URL = f"reports/{MODEL_UUID}/{MODEL_VERSION}"


def _signing_metadata(*download_urls: str) -> SigningMetadata:
    return SigningMetadata.model_validate(get_signing_event(*download_urls))


@pytest.mark.anyio
async def test_sign_and_upload_multiple_files():
    storage = create_new_mock_storage()
    signer = ReportSigner(storage)

    result = await signer.sign_and_upload(
        _signing_metadata(
            f"{REPORT_URL}/risk_report.json", f"{REPORT_URL}/assessment_report.json"
        )
    )

    assert result == SigningResult(signed=2, already_signed=0)

    # One upload per file, each with the ID of its original
    assert [upload.original_file_id for upload in storage.uploads] == [
        "original-0",
        "original-1",
    ]
    for upload in storage.uploads:
        assert upload.pool == "RP"
        assert upload.bucket == "risk-reports"

    for filename in ("risk_report.json", "assessment_report.json"):
        verify_report(
            storage.data[f"risk-reports/{MODEL_UUID}/{MODEL_VERSION}/{filename}"]
        )


@pytest.mark.anyio
async def test_tags_are_uploaded_comma_separated():
    storage = create_new_mock_storage()
    signer = ReportSigner(storage)
    event = get_signing_event(f"{REPORT_URL}/risk_report.json")
    event["tags"] = ["assessment", "security"]

    await signer.sign_and_upload(SigningMetadata.model_validate(event))

    assert storage.uploads[0].tags == "assessment,security"


@pytest.mark.anyio
async def test_empty_tags_are_uploaded_as_none():
    storage = create_new_mock_storage()
    signer = ReportSigner(storage)

    await signer.sign_and_upload(_signing_metadata(f"{REPORT_URL}/risk_report.json"))

    assert storage.uploads[0].tags is None


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
async def test_refused_download_does_not_stop_other_files():
    storage = create_new_mock_storage()
    get_file = storage.get_file_from_url

    async def get_file_from_url(download_url):
        if download_url == "reports/forbidden.json":
            raise StorageOperationError("Orchestrator returned 403")
        return await get_file(download_url)

    storage.get_file_from_url = get_file_from_url
    signer = ReportSigner(storage)

    with pytest.raises(ReportSignerProcessingError, match="403"):
        await signer.sign_and_upload(
            _signing_metadata(
                "reports/forbidden.json",
                f"{REPORT_URL}/risk_report.json",
            )
        )

    # Not reported as missing, and the other file is still signed.
    assert len(storage.uploads) == 1



@pytest.mark.anyio
@pytest.mark.parametrize(
    "download_urls",
    [
        ("reports/missing.json", "reports/forbidden.json"),
        ("reports/forbidden.json", "reports/missing.json"),
    ],
)
async def test_most_serious_failure_decides_the_error(download_urls):
    storage = create_new_mock_storage()
    get_file = storage.get_file_from_url

    async def get_file_from_url(download_url):
        if download_url == "reports/forbidden.json":
            raise StorageOperationError("Orchestrator returned 403")
        return await get_file(download_url)

    storage.get_file_from_url = get_file_from_url
    signer = ReportSigner(storage)

    # Whatever the order of the files, the refused download (500) outranks
    # the missing file (409), and both are listed.
    with pytest.raises(ReportSignerProcessingError) as exc_info:
        await signer.sign_and_upload(_signing_metadata(*download_urls))

    assert "reports/missing.json" in str(exc_info.value)
    assert "reports/forbidden.json" in str(exc_info.value)

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


@pytest.mark.anyio
async def test_storage_error_reports_progress_and_earlier_failures():
    storage = create_new_mock_storage()
    save_file = storage.save_file
    calls = 0

    # The first upload succeeds, the second finds storage down.
    async def save_file_then_fail(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise StorageConnectionError("down")
        await save_file(**kwargs)

    storage.save_file = save_file_then_fail
    signer = ReportSigner(storage)

    with pytest.raises(ReportSignerStorageError) as exc_info:
        await signer.sign_and_upload(
            _signing_metadata(
                "reports/missing-1.json",
                f"{REPORT_URL}/risk_report.json",
                f"{REPORT_URL}/assessment_report.json",
                f"{REPORT_URL}/defence_report.json",
            )
        )

    message = str(exc_info.value)
    assert "after 1 signed, 0 already signed" in message
    assert "earlier failures" in message
    assert "reports/missing-1.json" in message
    # Processing stopped at the storage error.
    assert calls == 2


@pytest.mark.anyio
async def test_signing_material_error_reports_progress():
    storage = create_new_mock_storage()
    signer = ReportSigner(storage)

    with patch(
        "app.services.signing.sign_report",
        side_effect=SigningError("Signing key and certificate do not match"),
    ):
        with pytest.raises(ReportSignerSigningError) as exc_info:
            await signer.sign_and_upload(
                _signing_metadata(f"{REPORT_URL}/risk_report.json")
            )

    message = str(exc_info.value)
    assert "after 0 signed, 0 already signed" in message
    assert "earlier failures" not in message
    assert storage.uploads == []


@pytest.mark.anyio
async def test_auth_error_on_upload_stops_remaining_files():
    storage = create_new_mock_storage()
    storage.save_file = AsyncMock(side_effect=StorageAuthError("login failed"))
    signer = ReportSigner(storage)

    with pytest.raises(ReportSignerStorageError):
        await signer.sign_and_upload(
            _signing_metadata(
                f"{REPORT_URL}/risk_report.json",
                f"{REPORT_URL}/assessment_report.json",
            )
        )

    storage.save_file.assert_awaited_once()


@pytest.mark.anyio
async def test_other_upload_failure_does_not_stop_other_files():
    storage = create_new_mock_storage()
    storage.save_file = AsyncMock(
        side_effect=[StorageOperationError("Orchestrator returned 403"), None]
    )
    signer = ReportSigner(storage)

    with pytest.raises(ReportSignerProcessingError, match="403"):
        await signer.sign_and_upload(
            _signing_metadata(
                f"{REPORT_URL}/risk_report.json",
                f"{REPORT_URL}/assessment_report.json",
            )
        )

    assert storage.save_file.await_count == 2


@pytest.mark.anyio
async def test_signed_and_already_signed_files_are_counted_separately():
    storage = create_new_mock_storage()
    storage.save_file = AsyncMock(side_effect=[StorageConflictError("409"), None])
    signer = ReportSigner(storage)

    result = await signer.sign_and_upload(
        _signing_metadata(
            f"{REPORT_URL}/risk_report.json", f"{REPORT_URL}/assessment_report.json"
        )
    )

    assert result == SigningResult(signed=1, already_signed=1)
