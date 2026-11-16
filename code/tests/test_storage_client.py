import pytest
from app.clients.storage_client import (
    StorageConnectionError,
    get_reports_concurrently,
)
from app.models.requests import GenerationMetadata
from app.utils.utils import ReportType

from tests.mock_storage import MockStorageClient
from tests.utils import (
    MODEL_UUID,
    MODEL_VERSION,
    Rendezvous,
    get_generation_metadata,
    get_generation_metadata_deprecation,
    get_url_for_report_type,
)


class RendezvousStorage(MockStorageClient):
    """Returns `{"url": <download URL>}` for every download, once all
    `rendezvous.parties` downloads have started.
    """

    def __init__(self, rendezvous: Rendezvous, failures=None):
        super().__init__()
        self.rendezvous = rendezvous
        self.failures = failures or {}

    async def get_file_from_url(self, download_url: str):
        await self.rendezvous.arrive()
        if download_url in self.failures:
            raise self.failures[download_url]
        return {"url": download_url}


@pytest.mark.anyio
async def test_get_reports_concurrently_downloads_all_reports_at_once():
    storage = RendezvousStorage(Rendezvous(len(ReportType)))
    metadata = GenerationMetadata(**get_generation_metadata(MODEL_UUID, MODEL_VERSION))

    reports = await get_reports_concurrently(storage, metadata)

    # Each report is keyed by its own report type, not shifted by the
    # concurrent downloads.
    assert reports == {
        report_type.value: {
            "url": get_url_for_report_type(MODEL_UUID, MODEL_VERSION, report_type)
        }
        for report_type in ReportType
    }


@pytest.mark.anyio
async def test_get_reports_concurrently_leaves_out_reports_without_metadata():
    storage = RendezvousStorage(Rendezvous(2))
    metadata = GenerationMetadata(
        **get_generation_metadata_deprecation(MODEL_UUID, MODEL_VERSION)
    )

    reports = await get_reports_concurrently(storage, metadata)

    assert set(reports) == {"assessment_report", "risk_report"}


@pytest.mark.anyio
async def test_get_reports_concurrently_raises_failed_download():
    failed_url = get_url_for_report_type(
        MODEL_UUID, MODEL_VERSION, ReportType.RISK_REPORT
    )
    storage = RendezvousStorage(
        Rendezvous(len(ReportType)),
        failures={failed_url: StorageConnectionError("storage down")},
    )
    metadata = GenerationMetadata(**get_generation_metadata(MODEL_UUID, MODEL_VERSION))

    with pytest.raises(StorageConnectionError, match="storage down"):
        await get_reports_concurrently(storage, metadata)
