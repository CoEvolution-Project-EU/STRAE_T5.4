import logging
import uuid
from typing import Dict

from fastapi import Depends
from fastapi.encoders import jsonable_encoder

from app import signing
from app.config import settings
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
from app.storage import (
    StorageConnectionError,
    StorageError,
    StorageInterface,
    StorageOperationError,
    get_storage,
)
from app.utils import utc_now_datetime
from app.validation import validate_aimbom

logger = logging.getLogger(__name__)


class GeneratorError(Exception):
    """Base exception for AIMBOM generation errors."""

    pass


class GeneratorMissingReportError(GeneratorError):
    """Raised when a required security report is missing."""

    pass


class GeneratorStorageError(GeneratorError):
    """Raised when an operation with MinIO fails."""

    pass


class GeneratorGenerationError(GeneratorError):
    """Raised when AIMBOM generation fails due to unexpected issues."""

    pass


class AIMBOMGenerator:
    def __init__(self, storage: StorageInterface):
        self.storage = storage

    async def generate(self, model_uuid: str, model_version: str) -> AIMBOM:
        logger.debug(
            "Starting generation pipeline model_uuid=%s, model_version=%s",
            model_uuid,
            model_version,
        )

        # TODO: Check if an AIMBOM already exists for the given model_uuid and
        # model_version before starting the generation process.
        # 1 -> If it exists, we have AIMBOM deprecation and we need to generate a
        # new AIMBOM with the new reports that includes the deprecated one.
        # 2 -> If it doesn't exist, we proceed with the generation as normal.

        reports = await self._retrieve_reports(model_uuid, model_version)
        aimbom = self._create_aimbom_from_reports(reports)
        await self._save_aimbom_to_bucket(model_uuid, model_version, aimbom)

        logger.debug(
            "Generation completed model_uuid=%s, model_version=%s",
            model_uuid,
            model_version,
        )
        return aimbom

    async def _retrieve_reports(self, model_uuid: str, model_version: str) -> dict:
        logger.debug(
            "Retrieving reports for model_uuid=%s, model_version=%s",
            model_uuid,
            model_version,
        )
        reports: dict[ReportType, Dict | None] = {
            ReportType.AI_MODEL_INFO: None,
            ReportType.ASSESSMENTS: None,
            ReportType.DATASETS: None,
            ReportType.EU_AI_ACT: None,
            ReportType.GADGETS: None,
        }

        # NOTE: Verify how are we going to find the latest reports,
        # if we have new reports for the same model_uuid and model_version.
        try:
            retrieved_reports = await self.storage.get_reports_for_model(
                model_uuid, model_version
            )
        except StorageConnectionError as e:
            logger.error(
                "Storage connection error retrieving reports for model_uuid=%s, model_version=%s",
                model_uuid,
                model_version,
                exc_info=True,
            )
            raise GeneratorStorageError(
                f"Failed to retrieve reports for model_uuid={model_uuid}, model_version={model_version} from MinIO storage: {str(e)}"
            ) from e
        except StorageOperationError as e:
            logger.warning(
                "Missing reports for model_uuid=%s, model_version=%s",
                model_uuid,
                model_version,
            )
            raise GeneratorMissingReportError(
                f"Required reports are missing for model_uuid={model_uuid}, model_version={model_version}: {str(e)}"
            ) from e

        # TODO: Validate the retrieved reports against their respective schemas
        # to ensure data integrity before processing.
        for report_type in reports.keys():
            report = retrieved_reports.get(report_type.value)

            if report is None:
                logger.warning(
                    "Missing report %s for model_uuid=%s, model_version=%s",
                    report_type.value,
                    model_uuid,
                    model_version,
                )
                raise GeneratorMissingReportError(
                    f"Required report {report_type.value} is missing for "
                    f"model_uuid={model_uuid}, model_version={model_version}"
                )

            reports[report_type] = report

            logger.debug(
                "Retrieved report %s for model_uuid=%s, model_version=%s",
                report_type.value,
                model_uuid,
                model_version,
            )

        logger.debug(
            "All reports retrieved for model_uuid=%s, model_version=%s",
            model_uuid,
            model_version,
        )
        return reports

    def _create_aimbom_from_reports(self, reports: dict[ReportType, Dict]) -> AIMBOM:
        logger.debug("Creating AIMBOM from reports")
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
                    hashes=[Hash(**h) for h in model_info_component.get("hashes", [])],
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
                version=1,
                metadata=metadata,
                external_references=external_references,
            )
            logger.debug("AIMBOM created with serial_number=%s", aimbom.serial_number)
        except Exception as e:
            logger.error("Error creating AIMBOM from reports", exc_info=True)
            raise GeneratorGenerationError(
                f"Failed to generate AIMBOM from reports: {str(e)}"
            ) from e

        # Sign the AIMBOM to ensure its integrity and authenticity.
        try:
            logger.debug("Signing AIMBOM")
            signed_aimbom = signing.sign_report(
                jsonable_encoder(aimbom, exclude_none=True)
            )
            aimbom = AIMBOM(**signed_aimbom)
            logger.debug("AIMBOM signed successfully")
        except Exception as e:
            logger.error("Error signing AIMBOM", exc_info=True)
            raise GeneratorGenerationError(f"Failed to sign AIMBOM: {str(e)}") from e

        # Validate the generated AIMBOM against the CycloneDX schema to ensure it is compliant.
        try:
            logger.debug("Validating AIMBOM")
            validate_aimbom(jsonable_encoder(aimbom, exclude_none=True))
            logger.debug("AIMBOM validation successful")
        except ValueError as e:
            logger.error("AIMBOM validation failed: %s", str(e))
            raise GeneratorGenerationError(
                f"Generated AIMBOM is invalid: {str(e)}"
            ) from e

        return aimbom

    async def _save_aimbom_to_bucket(
        self, model_uuid: str, model_version: str, aimbom: AIMBOM
    ):
        logger.debug(
            "Saving AIMBOM to bucket for model_uuid=%s, model_version=%s, serial_number=%s",
            model_uuid,
            model_version,
            aimbom.serial_number,
        )
        try:
            await self.storage.save_aimbom(
                model_uuid=model_uuid,
                model_version=model_version,
                aimbom=aimbom,
            )
            logger.debug("AIMBOM saved successfully")
        except StorageError as e:
            logger.error("Error saving AIMBOM to bucket", exc_info=True)
            raise GeneratorStorageError(
                f"Storage error while saving AIMBOM: {e}"
            ) from e


# AIMBOMGenerator dependency
def get_generator(storage: StorageInterface = Depends(get_storage)) -> AIMBOMGenerator:
    return AIMBOMGenerator(storage)
