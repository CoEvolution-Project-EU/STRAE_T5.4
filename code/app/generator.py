import logging
import uuid

from fastapi import Depends
from fastapi.encoders import jsonable_encoder

from app.config import settings
from app.db import MinioConnectionError, MinioDB, get_minio_client
from app.models.cyclonedx import (
    AIMBOM,
    AssessmentReport,
    DefenceReport,
    Metadata,
    ReportOrigin,
    RiskAssessmentReport,
    SecurityReport,
    ServiceProvider,
    Tools,
    ToolService,
)
from app.utils import utc_now_datetime

logger = logging.getLogger(__name__)


class GeneratorError(Exception):
    """Base exception for AIMBOM generation errors."""

    pass


class MissingReportsError(GeneratorError):
    """Raised when some required security reports are missing."""

    pass


class MinioStorageError(GeneratorError):
    """Raised when saving AIMBOM to storage fails."""

    pass


class GenerationError(GeneratorError):
    """Raised when AIMBOM generation fails due to unexpected issues."""

    pass


class AIMBOMGenerator:
    def __init__(self, minio: MinioDB):
        self.minio = minio

    def generate(self, model_id: str) -> AIMBOM:
        logger.debug("Starting generation pipeline model_id=%s", model_id)

        matched_reports = self._retrieve_reports(model_id)
        aimbom = self._create_aimbom_from_reports(matched_reports)
        self._save_aimbom_to_bucket(aimbom)

        logger.debug("Generation completed model_id=%s", model_id)
        return aimbom

    def _retrieve_reports(self, model_id: str) -> dict:
        matched_reports: dict[ReportOrigin, SecurityReport | None] = {
            ReportOrigin.STR_Defence_Framework: None,
            ReportOrigin.STAE: None,
            ReportOrigin.RAGRE: None,
        }

        prefix = f"{model_id}/"

        try:
            # TODO: Optimize by getting each report directly if object names are known
            # TODO: Get the reports concurrently to improve performance
            # Minio's Python SDK does not support async natively, so consider using threads.

            objects = self.minio.list_objects_in_bucket(
                bucket_name=settings.REPORTS_BUCKET, prefix=prefix
            )

            for obj in objects:
                if not obj.object_name.endswith(".json"):
                    continue

                data = self.minio.get_json(settings.REPORTS_BUCKET, obj.object_name)
                self._parse_report_data(data, matched_reports)
        except MinioConnectionError as e:
            logger.error(
                "MinIO failure while retrieving reports model_id=%s",
                model_id,
                exc_info=True,
            )
            raise MinioStorageError(f"MinIO error while retrieving reports: {e}") from e
        except GenerationError:
            raise

        # Check for missing reports
        missing_reports = [
            origin.value if hasattr(origin, "value") else str(origin)
            for origin, report in matched_reports.items()
            if report is None
        ]

        if missing_reports:
            raise MissingReportsError(
                f"Missing reports for model_id {model_id} from: {', '.join(missing_reports)}"
            )

        return matched_reports

    def _parse_report_data(
        self, report_data: dict, matched_reports: dict[ReportOrigin, SecurityReport]
    ) -> None:
        try:
            # TODO: Additional check if model_id from report matches the expected one
            tools = report_data.get("metadata").get("tools")

            # Check services first
            services = tools.get("services")
            if services:
                first_service = services[0]
                service_name = first_service.get("name")
                if service_name == ReportOrigin.RAGRE:
                    matched_reports[ReportOrigin.RAGRE] = RiskAssessmentReport(
                        **report_data
                    )
                    return
                elif service_name == ReportOrigin.STAE:
                    matched_reports[ReportOrigin.STAE] = AssessmentReport(**report_data)
                    return

            # Check components
            components = tools.get("components")
            if components:
                first_component = components[0]
                component_name = first_component.get("name")
                if component_name == ReportOrigin.STR_Defence_Framework:
                    matched_reports[ReportOrigin.STR_Defence_Framework] = DefenceReport(
                        **report_data
                    )
                    return
        except Exception as e:
            raise GenerationError(f"Failed to parse report data: {str(e)}") from e

    def _create_aimbom_from_reports(
        self, matched_reports: dict[ReportOrigin, SecurityReport]
    ) -> AIMBOM:
        try:
            # Create AIMBOM metadata
            metadata = Metadata(
                timestamp=utc_now_datetime(),
                tools=Tools(
                    services=[
                        ToolService(
                            name=settings.NAME,
                            version=settings.VERSION,
                            provider=ServiceProvider(name=settings.PROVIDER_NAME),
                        )
                    ]
                ),
                component=matched_reports[ReportOrigin.STAE].metadata.component,
            )

            # Flatten external references
            external_references = [
                ref
                for report_origin in [ReportOrigin.STAE, ReportOrigin.RAGRE]
                for ref in matched_reports[report_origin].external_references
            ]

            # Flatten annotations
            annotations = [
                ann
                for report_origin in [
                    ReportOrigin.STR_Defence_Framework,
                    ReportOrigin.STAE,
                    ReportOrigin.RAGRE,
                ]
                for ann in matched_reports[report_origin].annotations
            ]

            # Create the AIMBOM
            aimbom = AIMBOM(
                bom_format="CycloneDX",
                spec_version="1.7",
                serial_number=f"urn:uuid:{str(uuid.uuid4())}",
                version=1,  # TODO Handle versioning properly
                metadata=metadata,
                components=matched_reports[
                    ReportOrigin.STR_Defence_Framework
                ].components,
                vulnerabilities=matched_reports[ReportOrigin.RAGRE].vulnerabilities,
                external_references=external_references,
                properties=matched_reports[ReportOrigin.STAE].properties,
                annotations=annotations,
            )
        except Exception as e:
            raise GenerationError(
                f"Failed to generate AIMBOM from reports: {str(e)}"
            ) from e

        # TODO: Sign the AIMBOM for future verification

        return aimbom

    def _save_aimbom_to_bucket(self, aimbom: AIMBOM):
        try:
            self.minio.upload_json(
                bucket_name=settings.AIMBOMS_BUCKET,
                object_name=f"{aimbom.get_model_id()}/{aimbom.serial_number}.json",
                data=jsonable_encoder(aimbom, exclude_none=True),
            )
        except MinioConnectionError as e:
            raise MinioStorageError(f"MinIO error while saving AIMBOM: {e}") from e


# AIMBOMGenerator dependency
def get_generator(minio: MinioDB = Depends(get_minio_client)) -> AIMBOMGenerator:
    return AIMBOMGenerator(minio)
