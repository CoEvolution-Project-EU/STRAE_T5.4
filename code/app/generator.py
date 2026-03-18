import logging
import uuid
from typing import Dict

from fastapi import Depends
from fastapi.encoders import jsonable_encoder

from app.config import settings
from app.db import (
    MinioConnectionError,
    MinioDB,
    MinioError,
    MinioOperationError,
    get_minio_client,
)
from app.models.aimbom import (
    AIMBOM,
    Component,
    ExternalReference,
    Hash,
    Metadata,
    ReportType,
    Supplier,
    Tool,
)
from app.utils import utc_now_datetime

logger = logging.getLogger(__name__)


class GeneratorError(Exception):
    """Base exception for AIMBOM generation errors."""

    pass


class GeneratorMissingReportError(GeneratorError):
    """Raised when a required security report is missing."""

    pass


class GeneratorMinioError(GeneratorError):
    """Raised when an operation with MinIO fails."""

    pass


class GeneratorGenerationError(GeneratorError):
    """Raised when AIMBOM generation fails due to unexpected issues."""

    pass


class AIMBOMGenerator:
    def __init__(self, minio: MinioDB):
        self.minio = minio

    def generate(self, model_id: str) -> AIMBOM:
        logger.debug("Starting generation pipeline model_id=%s", model_id)

        reports = self._retrieve_reports(model_id)
        aimbom = self._create_aimbom_from_reports(reports)
        self._save_aimbom_to_bucket(model_id, aimbom)

        logger.debug("Generation completed model_id=%s", model_id)
        return aimbom

    def _retrieve_reports(self, model_id: str) -> dict:
        reports: dict[ReportType, Dict | None] = {
            ReportType.AI_MODEL_INFO: None,
            ReportType.ASSESSMENTS: None,
            ReportType.DATASETS: None,
            ReportType.EU_AI_ACT: None,
            ReportType.GADGETS: None,
        }

        # NOTE: This is going to be a single API call to retrieve all the reports
        # from the CoEvolution Knowledge Base.

        # TODO: Verify how are we going to find the latest reports,
        # if we are going to have multiple versions of the same report.
        # TODO: Validate the retrieved reports against their respective schemas
        # to ensure data integrity before processing.

        for report_type in reports.keys():
            try:
                reports[report_type] = self.minio.get_json(
                    settings.REPORTS_BUCKET,
                    f"{model_id}/{report_type.value}.json",
                )
            except MinioConnectionError as e:
                raise GeneratorMinioError(
                    f"Failed to retrieve report {report_type.value} for model_id={model_id} from MinIO storage: {str(e)}"
                ) from e
            except MinioOperationError as e:
                raise GeneratorMissingReportError(
                    f"Required report {report_type.value} is missing for model_id={model_id}: {str(e)}"
                ) from e
            except Exception as e:
                raise GeneratorGenerationError(
                    f"Failed to retrieve/parse data for report {report_type.value} for model_id={model_id}: {str(e)}"
                ) from e

        return reports

    def _create_aimbom_from_reports(self, reports: dict[ReportType, Dict]) -> AIMBOM:
        try:
            model_info_metadata = reports[ReportType.AI_MODEL_INFO].get("metadata")
            model_info_component = model_info_metadata.get("component")

            metadata = Metadata(
                timestamp=utc_now_datetime(),
                component=Component(
                    bom_ref=model_info_component.get("bom-ref"),
                    type=model_info_component.get("type"),
                    name=model_info_component.get("name"),
                    version=model_info_component.get("version"),
                    supplier=Supplier(
                        name=model_info_component.get("supplier").get("name")
                    ),
                    hashes=[
                        Hash(**hash_dict)
                        for hash_dict in model_info_component.get("hashes", [])
                    ],
                ),
                supplier=Supplier(name="coevolution-project.eu"),
                tools=[
                    Tool(
                        vendor=settings.PROVIDER_NAME,
                        name=settings.NAME,
                        version=settings.VERSION,
                    )
                ],
            )

            # Create external references for each report
            external_references = [
                ExternalReference(
                    type="bom",
                    url=f"urn:cdx:{report.get('serialNumber').split('urn:uuid:')[1]}/{report.get('version', 1)}",
                    comment=origin.value,
                )
                for origin, report in reports.items()
                if report is not None
            ]

            # Create the AIMBOM
            aimbom = AIMBOM(
                bom_format="CycloneDX",
                spec_version="1.7",
                serial_number=f"urn:uuid:{str(uuid.uuid4())}",
                version=1,  # TODO Handle versioning properly
                metadata=metadata,
                external_references=external_references,
                signature={},  # TODO: Sign the AIMBOM for future verification
            )
        except Exception as e:
            raise GeneratorGenerationError(
                f"Failed to generate AIMBOM from reports: {str(e)}"
            ) from e

        return aimbom

    def _save_aimbom_to_bucket(self, model_id: str, aimbom: AIMBOM):
        try:
            self.minio.upload_json(
                bucket_name=settings.AIMBOMS_BUCKET,
                object_name=f"{model_id}/{aimbom.serial_number}.json",
                data=jsonable_encoder(aimbom, exclude_none=True),
            )
        except MinioError as e:
            raise GeneratorMinioError(f"MinIO error while saving AIMBOM: {e}") from e


# AIMBOMGenerator dependency
def get_generator(minio: MinioDB = Depends(get_minio_client)) -> AIMBOMGenerator:
    return AIMBOMGenerator(minio)
