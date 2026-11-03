from typing import Dict, Tuple

from app.clients.storage_client import (
    StorageClient,
    StorageNotFoundError,
    StorageOperationError,
)
from app.models.aimbom import AIMBOM
from app.models.requests import GenerationMetadata
from app.models.storage import UploadReportMetadata
from app.utils.utils import ReportType
from fastapi.encoders import jsonable_encoder


class MockStorageClient(StorageClient):
    def __init__(self):
        self.data = {}
        self.uploads: list[UploadReportMetadata] = []

    async def get_file_from_url(self, download_url: str) -> Dict:
        report = self.data.get(download_url)
        if report is None:
            raise StorageOperationError(f"Report not found for URL: {download_url}")
        return report

    async def save_file(
        self,
        file: Dict,
        filename: str,
        upload_report_metadata: UploadReportMetadata,
    ):
        self.data[
            f"{upload_report_metadata.bucket}/{upload_report_metadata.model_uuid}/"
            f"{upload_report_metadata.version}/{filename}"
        ] = file
        self.uploads.append(upload_report_metadata)

    async def get_reports_for_model(
        self,
        generation_metadata: GenerationMetadata,
    ):
        reports = {}

        for report_type, metadata in generation_metadata.reports.model_dump().items():
            if metadata is None:
                continue

            download_url = metadata.get("download_url")
            if not download_url:
                continue

            reports[report_type] = await self.get_file_from_url(
                download_url=download_url
            )

        return reports

    async def save_aimbom(
        self,
        model_uuid: str,
        model_version: str,
        aimbom: AIMBOM,
    ):
        self.data[f"aimboms/{model_uuid}/{model_version}/aimbom.json"] = (
            jsonable_encoder(aimbom, exclude_none=True)
        )

    async def get_aimbom(
        self,
        model_uuid: str,
        model_version: str,
    ) -> Tuple[Dict, Dict[str, Dict]]:
        # Same layout as `MinioClient`: the AIMBOM saved by `save_aimbom`, and
        # the version 1 report of each type, keyed by report type value.
        aimbom = self.data.get(f"aimboms/{model_uuid}/{model_version}/aimbom.json")
        if aimbom is None:
            raise StorageNotFoundError(
                f"No AIMBOM found for model_uuid='{model_uuid}', "
                f"model_version='{model_version}'"
            )

        reports = {
            report_type.value: await self.get_file_from_url(
                f"reports/{model_uuid}/{model_version}/{report_type.value}.json"
            )
            for report_type in ReportType
        }

        return aimbom, reports
