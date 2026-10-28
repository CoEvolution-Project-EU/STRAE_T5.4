from typing import Dict

from app.clients.storage_client import (
    StorageClient,
    StorageOperationError,
    UploadedFile,
)
from app.models.aimbom import AIMBOM
from app.models.requests import GenerationMetadata, UploadReportMetadata


class MockStorageClient(StorageClient):
    def __init__(self):
        self.data = {}

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
    ) -> UploadedFile:
        self.data[
            f"{upload_report_metadata.bucket}/{upload_report_metadata.model_uuid}/"
            f"{upload_report_metadata.version}/{filename}"
        ] = file

        return UploadedFile(
            filename=filename,
            pool=upload_report_metadata.pool,
            bucket=upload_report_metadata.bucket,
        )

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
        self.data[f"aimboms/{model_uuid}/{model_version}/aimbom"] = aimbom.model_dump()
