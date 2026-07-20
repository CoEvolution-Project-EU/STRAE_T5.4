import logging
import uuid
from typing import Dict

from fastapi import Depends
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from app.clients.storage_client import (
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
from app.services import signing, validation
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
        generation_metadata: GenerationMetadata,
    ) -> Dict[AIMBOMTier, AIMBOM]:
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
        # model_version before starting the generation process (should be inlcuded
        # in the generation_metadata).
        # 1 -> If it exists, we have AIMBOM deprecation and we need to generate a
        # new AIMBOM with the new reports that includes a link to the deprecated one.
        # 2 -> If it doesn't exist, we proceed with the generation as normal.

        reports = await self._load_reports(
            model_uuid, model_version, generation_metadata
        )
        tiered_aimbom = self._create_aimbom_from_reports(reports)
        await self._save_aimbom(model_uuid, model_version, tiered_aimbom)

        logger.debug(
            "Generation completed model_uuid=%s, model_version=%s",
            model_uuid,
            model_version,
        )
        return tiered_aimbom

    async def _fetch_raw_reports(
        self,
        model_uuid: str,
        model_version: str,
        generation_metadata: GenerationMetadata,
    ) -> Dict[ReportType, Dict]:
        """Fetch reports for a given model UUID and version.

        Args:
            model_uuid: Model UUID to fetch reports for.
            model_version: Model version to fetch reports for.
            generation_metadata: Optional metadata used to fetch reports from an
                external orchestrator.

        Returns:
            A mapping of `ReportType` to json dictionaries.

        Raises:
            GeneratorMissingReportError: When required reports are missing.
            GeneratorStorageError: When storage operations fail.
        """

        try:
            return await self.client.get_reports_for_model(
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

    def _validate_reports(
        self, model_uuid: str, model_version: str, raw_reports: Dict[ReportType, Dict]
    ) -> Dict[ReportType, ReportModel]:
        """
        Validate the retrieved reports for a given model UUID and version.

        Args:
            model_uuid: Model UUID to validate reports for.
            model_version: Model version to validate reports for.
            raw_reports: A mapping of `ReportType` to raw JSON dictionaries.

        Returns:
            A mapping of `ReportType` to validated `ReportModel` instances.

        Raises:
            GeneratorMissingReportError: When required reports are missing.
            GeneratorGenerationError: When report validation fails.
        """

        reports: Dict[ReportType, ReportModel | None] = {}

        # Validate and parse each retrieved report, ensuring they are compliant with the CycloneDX schema
        # and our specific report models.
        for report_type in REPORT_MODELS.keys():
            report = raw_reports.get(report_type.value)

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
                validation.cdx_validate_dict(report)

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
        return reports

    async def _load_reports(
        self,
        model_uuid: str,
        model_version: str,
        generation_metadata: GenerationMetadata,
    ) -> Dict[ReportType, ReportModel]:
        """Load and validate the set of required reports for a model.

        Args:
            model_uuid: Model UUID to fetch reports for.
            model_version: Model version to fetch reports for.
            generation_metadata: Optional metadata used by orchestrator-backed storage.

        Returns:
            A mapping of `ReportType` to validated report model instances.
        """
        logger.debug(
            "Retrieving reports for model_uuid=%s, model_version=%s",
            model_uuid,
            model_version,
        )

        # Fetch reports from the storage backend using the provided model UUID, version and generation metadata.
        raw_reports = await self._fetch_raw_reports(
            model_uuid, model_version, generation_metadata
        )

        # Validate and parse each retrieved report, ensuring they are compliant with the CycloneDX schema
        # and our specific report models.
        validated_reports = self._validate_reports(
            model_uuid, model_version, raw_reports
        )

        logger.debug(
            "All reports retrieved for model_uuid=%s, model_version=%s",
            model_uuid,
            model_version,
        )
        return validated_reports

    def _build_metadata(self, reports: Dict[ReportType, ReportModel]) -> Metadata:
        """Construct the `Metadata` section of the AIMBOM from the reports.

        Args:
            reports: Mapping of `ReportType` to validated report model instances.

        Returns:
            A `Metadata` instance populated with information from the reports.

        Raises:
            GeneratorGenerationError: If metadata construction fails.
        """

        try:
            # model_info = AIModelInfo(**reports[ReportType.AI_MODEL_INFO])
            model_info = reports[ReportType.AI_MODEL_INFO]
            model_info_component = model_info.metadata.component

            return Metadata(
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
        except Exception as e:
            logger.error("Error creating AIMBOM metadata from reports", exc_info=True)
            raise GeneratorGenerationError(
                f"Failed to generate AIMBOM metadata from reports: {str(e)}"
            ) from e

    def _build_external_references(
        self, reports: Dict[ReportType, ReportModel]
    ) -> list[ExternalReference]:
        """Construct the `ExternalReference` section of the AIMBOM from the reports.

        Args:
            reports: Mapping of `ReportType` to validated report model instances.

        Returns:
            A list of `ExternalReference` instances populated with information from the reports.

        Raises:
            GeneratorGenerationError: If external reference construction fails.
        """

        try:
            # Create external references for each report
            return [
                ExternalReference(
                    type="bom",
                    url=f"urn:cdx:{uuid_from_serial_number(r.serial_number)}/{r.version}",
                    comment=REPORT_TO_COMMENT.get(o.value),
                )
                for o, r in reports.items()
                if r is not None
            ]
        except Exception as e:
            logger.error(
                "Error creating AIMBOM external references from reports", exc_info=True
            )
            raise GeneratorGenerationError(
                f"Failed to generate AIMBOM external references from reports: {str(e)}"
            ) from e

    def _sign_aimbom(self, aimbom: AIMBOM) -> AIMBOM:
        """Sign the AIMBOM to ensure its integrity and authenticity.

        Args:
            aimbom: The `AIMBOM` instance to sign.

        Returns:
            A signed `AIMBOM` instance.

        Raises:
            GeneratorGenerationError: If signing fails.
        """

        try:
            logger.debug("Signing AIMBOM")
            signed_aimbom = signing.sign_report(
                jsonable_encoder(aimbom, exclude_none=True)
            )
            aimbom = AIMBOM(**signed_aimbom)
            logger.debug("AIMBOM signed successfully")

            return aimbom
        except Exception as e:
            logger.error("Error signing AIMBOM", exc_info=True)
            raise GeneratorGenerationError(f"Failed to sign AIMBOM: {str(e)}") from e

    def _validate_aimbom(self, aimbom: AIMBOM) -> None:
        """Validate the AIMBOM against the CycloneDX schema.

        Args:
            aimbom: The `AIMBOM` instance to validate.

        Raises:
            GeneratorGenerationError: If validation fails.
        """

        try:
            logger.debug("Validating AIMBOM")
            validation.cdx_validate_dict(jsonable_encoder(aimbom, exclude_none=True))
            logger.debug("AIMBOM validation successful")
        except ValueError as e:
            logger.error("AIMBOM validation failed: %s", str(e))
            raise GeneratorGenerationError(
                f"Generated AIMBOM is invalid: {str(e)}"
            ) from e

    def _filter_aimbom_references(
        self, aimbom: AIMBOM, references_to_keep: set[ReportComment]
    ) -> AIMBOM:
        """Filter AIMBOM external references based on specified references.

        Args:
            aimbom: The original `AIMBOM` instance.
            references_to_keep: A set of `ReportComment` values to retain in the external references.

        Returns:
            A new `AIMBOM` instance with filtered external references.
        """

        return aimbom.model_copy(
            update={
                "external_references": [
                    ref
                    for ref in aimbom.external_references
                    if ref.comment in references_to_keep
                ]
            }
        )

    def _create_tiered_aimbom(self, aimbom: AIMBOM) -> Dict[AIMBOMTier, AIMBOM]:
        """Create a dictionary of tiered AIMBOMs from the full AIMBOM.

        Args:
            aimbom: The full Tier 3 `AIMBOM` instance.

        Returns:
            A dictionary mapping `AIMBOMTier` to the corresponding tiered `AIMBOM` instances.

        Raises:
            GeneratorGenerationError: If tiered AIMBOM creation fails.
        """

        logger.debug(
            "Creating tiered AIMBOMs from full AIMBOM with serial_number=%s",
            aimbom.serial_number,
        )

        try:
            return {
                AIMBOMTier.TIER_1: self._filter_aimbom_references(
                    aimbom, {ReportComment.EU_AI_ACT}
                ),
                AIMBOMTier.TIER_2: self._filter_aimbom_references(
                    aimbom,
                    {
                        ReportComment.EU_AI_ACT,
                        ReportComment.RISK_REPORT,
                        ReportComment.ASSESSMENTS,
                        ReportComment.DEFENCES,
                        ReportComment.GADGETS,
                    },
                ),
                AIMBOMTier.TIER_3: aimbom,
            }
        except Exception as e:
            logger.error("Error creating tiered AIMBOM", exc_info=True)
            raise GeneratorGenerationError(
                f"Failed to create tiered AIMBOM: {str(e)}"
            ) from e

    def _create_aimbom_from_reports(
        self, reports: Dict[ReportType, ReportModel]
    ) -> Dict[AIMBOMTier, AIMBOM]:
        """Construct an `AIMBOM` object from validated reports.

        Args:
            reports: Mapping of `ReportType` to validated report model instances.

        Returns:
            A signed and validated `AIMBOM` instance.

        Raises:
            GeneratorGenerationError: If AIMBOM generation fails.
        """
        logger.debug("Creating AIMBOM from reports")

        metadata = self._build_metadata(reports)
        external_references = self._build_external_references(reports)

        # Create the AIMBOM
        try:
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
        # NOTE: We sign the AIMBOM before creating the Tiers. In Tiers 1-2 the signature cannot be validated.
        # Maybe sign each Tier separately, but this would require a new signature for each Tier and the signature would be different for each Tier.
        aimbom = self._sign_aimbom(aimbom)

        # Validate the generated AIMBOM against the CycloneDX schema to ensure it is compliant.
        self._validate_aimbom(aimbom)

        return self._create_tiered_aimbom(aimbom)

    async def _save_aimbom(
        self,
        model_uuid: str,
        model_version: str,
        tiered_aimbom: Dict[AIMBOMTier, AIMBOM],
    ):
        """Persist tiered AIMBOMs to the configured storage backend.

        Args:
            model_uuid: Model UUID to associate with stored AIMBOMs.
            model_version: Model version to associate with stored AIMBOMs.
            tiered_aimbom: The tiered `AIMBOM` instances to store.

        Returns:
            None

        Raises:
            GeneratorStorageError: If storage operations fail.
        """

        logger.debug(
            "Saving AIMBOM to bucket for model_uuid=%s, model_version=%s",
            model_uuid,
            model_version,
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
