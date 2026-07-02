import logging
import uuid

from fastapi import Depends
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from app.clients.base import (
    StorageClient,
    StorageConnectionError,
    StorageError,
    StorageOperationError,
    get_storage_client,
)
from app.core.config import settings
from app.models.aimbom import (
    AIMBOM,
    Component,
    ExternalReference,
    Metadata,
    Supplier,
    Tool,
)
from app.models.requests import GenerationMetadata
from app.services import signing
from app.services.validation import validate_report
from app.utils.utils import (
    REPORT_MODELS,
    REPORT_TO_COMMENT,
    AIMBOMTier,
    ReportComment,
    ReportModel,
    ReportType,
    utc_now_datetime,
    uuid_from_serial_number,
)

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
    def __init__(self, client: StorageClient):
        """Initialize the AIMBOM generator.

        Args:
            client: A `StorageClient` implementation used to retrieve
                reports and persist generated AIMBOMs.

        Returns:
            None
        """

        self.client = client

    async def generate(
        self,
        model_uuid: str,
        model_version: str,
        generation_metadata: GenerationMetadata | None,
    ) -> AIMBOM:
        """Run the full AIMBOM generation pipeline.

        This retrieves reports for the given model, constructs an AIMBOM from
        those reports, signs and validates it, and persists tiered AIMBOMs to
        the configured storage backend.

        Args:
            model_uuid: Unique identifier of the AI model.
            model_version: Version string of the AI model.
            generation_metadata: Optional metadata used to fetch reports from an
                external orchestrator.

        Returns:
            The generated `AIMBOM` instance.
        """
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

        reports = await self._retrieve_reports(
            model_uuid, model_version, generation_metadata
        )
        aimbom = self._create_aimbom_from_reports(reports)
        await self._save_aimbom_to_bucket(model_uuid, model_version, aimbom)

        logger.debug(
            "Generation completed model_uuid=%s, model_version=%s",
            model_uuid,
            model_version,
        )
        return aimbom

    async def _retrieve_reports(
        self,
        model_uuid: str,
        model_version: str,
        generation_metadata: GenerationMetadata | None,
    ) -> dict[ReportType, ReportModel]:
        """Retrieve and validate the set of required reports for a model.

        Args:
            model_uuid: Model UUID to fetch reports for.
            model_version: Model version to fetch reports for.
            generation_metadata: Optional metadata used by orchestrator-backed storage.

        Returns:
            A mapping of `ReportType` to validated report model instances.

        Raises:
            GeneratorMissingReportError: When required reports are missing.
            GeneratorStorageError: When storage operations fail.
        """
        logger.debug(
            "Retrieving reports for model_uuid=%s, model_version=%s",
            model_uuid,
            model_version,
        )
        reports: dict[ReportType, ReportModel | None] = {
            ReportType.AI_MODEL_INFO: None,
            ReportType.ASSESSMENTS: None,
            ReportType.DATASETS: None,
            ReportType.DEFENCES: None,
            ReportType.EU_AI_ACT: None,
            ReportType.GADGETS: None,
            ReportType.RISK_REPORT: None,
        }

        # NOTE: Verify how are we going to find the latest reports,
        # if we have new reports for the same model_uuid and model_version.
        try:
            retrieved_reports = await self.client.get_reports_for_model(
                model_uuid, model_version, generation_metadata
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

        # Validate and parse each retrieved report, ensuring they are compliant with the CycloneDX schema
        # and our specific report models.
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

            try:
                # Generic CycloneDX validation
                validate_report(report)

                # Schema-specific validation
                model_cls = REPORT_MODELS[report_type]
                validated_report = model_cls.model_validate(report)
            except ValueError as e:
                logger.warning(
                    "Invalid CycloneDX report %s for model_uuid=%s, model_version=%s: %s",
                    report_type.value,
                    model_uuid,
                    model_version,
                    str(e),
                )
                raise GeneratorGenerationError(
                    f"Report {report_type.value} is invalid for "
                    f"model_uuid={model_uuid}, model_version={model_version}: {str(e)}"
                ) from e
            except ValidationError as e:
                logger.warning(
                    "Schema validation failed for report %s "
                    "for model_uuid=%s, model_version=%s: %s",
                    report_type.value,
                    model_uuid,
                    model_version,
                    str(e),
                )
                raise GeneratorGenerationError(
                    f"Report {report_type.value} failed schema validation "
                    f"for model_uuid={model_uuid}, "
                    f"model_version={model_version}: {str(e)}"
                ) from e

            reports[report_type] = validated_report

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

    def _create_aimbom_from_reports(
        self, reports: dict[ReportType, ReportModel]
    ) -> AIMBOM:
        """Construct an `AIMBOM` object from validated reports.

        Args:
            reports: Mapping of `ReportType` to validated report model instances.

        Returns:
            A signed and validated `AIMBOM` instance.

        Raises:
            GeneratorGenerationError: If signing or validation fails.
        """
        logger.debug("Creating AIMBOM from reports")
        try:
            # model_info = AIModelInfo(**reports[ReportType.AI_MODEL_INFO])
            model_info = reports[ReportType.AI_MODEL_INFO]
            model_info_component = model_info.metadata.component

            metadata = Metadata(
                timestamp=utc_now_datetime(),
                component=Component(
                    bom_ref=model_info_component.bom_ref,
                    type=model_info_component.type,
                    name=model_info_component.name,
                    version=model_info_component.version,
                    description=model_info_component.description,
                    hashes=model_info_component.hashes,
                    licenses=model_info_component.licenses,
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
                    url=f"urn:cdx:{uuid_from_serial_number(r.serial_number)}/{r.version}",
                    comment=REPORT_TO_COMMENT.get(o.value),
                )
                for o, r in reports.items()
                if r is not None
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
            validate_report(jsonable_encoder(aimbom, exclude_none=True))
            logger.debug("AIMBOM validation successful")
        except ValueError as e:
            logger.error("AIMBOM validation failed: %s", str(e))
            raise GeneratorGenerationError(
                f"Generated AIMBOM is invalid: {str(e)}"
            ) from e

        return aimbom

    def _create_tier2_aimbom(self, aimbom: AIMBOM) -> AIMBOM:
        """Create a Tier 2 AIMBOM by removing model & dataset external refs.

        Returns a new `AIMBOM` instance suitable for Tier 2 disclosure.
        """
        # Tier 2: Remove AI Model & Dataset Info from AIMBOM external references
        return aimbom.model_copy(
            update={
                "external_references": [
                    ref
                    for ref in aimbom.external_references
                    if ref.comment
                    not in {ReportComment.AI_MODEL_INFO, ReportComment.DATASETS}
                ]
            }
        )

    def _create_tier1_aimbom(self, aimbom: AIMBOM) -> AIMBOM:
        """Create a Tier 1 AIMBOM keeping only development-guideline refs.

        Returns a new `AIMBOM` instance suitable for Tier 1 disclosure.
        """
        # Tier 1: Remove all AIMBOM external references except Model Development Guidelines
        return aimbom.model_copy(
            update={
                "external_references": [
                    ref
                    for ref in aimbom.external_references
                    if ref.comment in {ReportComment.EU_AI_ACT}
                ]
            }
        )

    async def _save_aimbom_to_bucket(
        self, model_uuid: str, model_version: str, aimbom: AIMBOM
    ):
        """Persist tiered AIMBOMs to the configured storage backend.

        Args:
            model_uuid: Model UUID to associate with stored AIMBOMs.
            model_version: Model version to associate with stored AIMBOMs.
            aimbom: The full Tier 3 `AIMBOM` to derive tiered variants from.

        Returns:
            None

        Raises:
            GeneratorStorageError: If storage operations fail.
        """
        logger.debug(
            "Creating tiered AIMBOM for model_uuid=%s, model_version=%s, serial_number=%s",
            model_uuid,
            model_version,
            aimbom.serial_number,
        )
        try:
            tiered_aimbom = {
                AIMBOMTier.Tier_1: self._create_tier1_aimbom(aimbom),
                AIMBOMTier.Tier_2: self._create_tier2_aimbom(aimbom),
                AIMBOMTier.Tier_3: aimbom,
            }
        except Exception as e:
            logger.error("Error creating tiered AIMBOM", exc_info=True)
            raise GeneratorGenerationError(
                f"Failed to create tiered AIMBOM: {str(e)}"
            ) from e

        logger.debug(
            "Saving AIMBOM to bucket for model_uuid=%s, model_version=%s, serial_number=%s",
            model_uuid,
            model_version,
            aimbom.serial_number,
        )
        try:
            await self.client.save_aimbom(
                model_uuid=model_uuid,
                model_version=model_version,
                tiered_aimbom=tiered_aimbom,
            )
            logger.debug("AIMBOM saved successfully")
        except StorageError as e:
            logger.error("Error saving AIMBOM to bucket", exc_info=True)
            raise GeneratorStorageError(
                f"Storage error while saving AIMBOM: {e}"
            ) from e


# AIMBOMGenerator dependency
async def get_generator(
    client: StorageClient = Depends(get_storage_client),
) -> AIMBOMGenerator:
    """FastAPI dependency that constructs an `AIMBOMGenerator`.

    Args:
        client: Injected `StorageClient` dependency.

    Returns:
        An `AIMBOMGenerator` instance ready for use by request handlers.
    """

    return AIMBOMGenerator(client=client)
