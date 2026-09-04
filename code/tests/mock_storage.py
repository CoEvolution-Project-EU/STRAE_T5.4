from typing import Dict

from app.clients.storage_client import StorageClient, StorageOperationError
from app.models.aimbom import AIMBOM
from app.models.requests import GenerationMetadata
from app.utils.utils import AIMBOMTier, ReportType


class MockStorageClient(StorageClient):
    def __init__(self):
        self.reports = {}
        self.aimboms = {}

    async def get_file_from_url(self, download_url: str) -> Dict:
        pass

    async def get_reports_for_model(
        self,
        generation_metadata: GenerationMetadata,
    ):
        download_url = generation_metadata.reports.risk_report.download_url

        _, model_uuid, model_version, _ = download_url.split("/")

        key = (model_uuid, model_version)

        if key not in self.reports:
            raise StorageOperationError("No reports found")

        return self.reports[key]

    async def save_aimbom(
        self,
        model_uuid: str,
        model_version: str,
        tiered_aimbom: Dict[AIMBOMTier, AIMBOM],
    ):
        self.aimboms[(model_uuid, model_version)] = tiered_aimbom
