import logging
from typing import Dict, Iterable

from fastapi import Depends
from pydantic import ValidationError

from app.clients.storage_client import (
    StorageAuthError,
    StorageClient,
    StorageConnectionError,
    StorageError,
    StorageInvalidFileError,
    StorageNotFoundError,
    get_storage_client,
)
from app.models.aimbom import AIMBOM
from app.services import cyclonedx_validation, signing
from app.utils.utils import (
    COMMENT_TO_REPORT,
    DOCUMENT_MODELS,
    REPORT_TYPES,
    BOMType,
    DocumentType,
    ReportModel,
    ReportType,
    bom_link,
)

logger = logging.getLogger(__name__)


class ValidatorError(Exception):
    """Base exception for validation errors."""

    pass


class ValidatorInvalidAIMBOMError(ValidatorError):
    """Raised when the AIMBOM or one of its reports is invalid."""

    pass


class ValidatorMissingReportError(ValidatorInvalidAIMBOMError):
    """Raised when a required report does not exist."""

    pass


class ValidatorSchemaValidationError(ValidatorInvalidAIMBOMError):
    """Raised when a report fails schema validation."""

    pass


class ValidatorSignatureError(ValidatorInvalidAIMBOMError):
    """Raised when the signature of the AIMBOM or a report is missing,
    malformed or invalid.
    """

    pass


class ValidatorLinkValidationError(ValidatorInvalidAIMBOMError):
    """Raised when the AIMBOM does not reference exactly its reports."""

    pass


class ValidatorNotFoundError(ValidatorError):
    """Raised when the model version has no AIMBOM."""

    pass


class ValidatorStorageError(ValidatorError):
    """Raised when the storage backend is unavailable, so nothing can be
    said about the AIMBOM.
    """

    pass


class ValidatorReadError(ValidatorError):
    """Raised when the storage backend refuses to return the files (e.g. a
    403, or a malformed response), so nothing can be said about the AIMBOM,
    and retrying won't help.
    """

    pass


class AIMBOMValidator:
    def __init__(self, client: StorageClient):
        """
        Initialize the AIMBOMValidator.

        Args:
            client (StorageClient): An instance of StorageClient to interact with the storage backend.
        """

        self.client = client

    async def validate_aimbom(self, model_uuid: str, model_version: str) -> bool:
        """
        Validate the AIMBOM for the given model UUID and version.

        Stops at the first problem found.

        Args:
            model_uuid (str): The UUID of the model.
            model_version (str): The version of the model.

        Returns:
            Whether the AIMBOM and every report are signed by CoEvolution
            (with a key in the trust list).

        Raises:
            ValidatorInvalidAIMBOMError: If the AIMBOM or one of its reports is
                invalid, missing or not valid JSON, or the AIMBOM does not
                reference exactly its reports.
            ValidatorNotFoundError: If the model version has no AIMBOM.
            ValidatorStorageError: If the storage backend is unavailable.
            ValidatorReadError: If the storage backend refuses to return the
                files for any other reason.
            signing.TrustListError: If the trust list is missing or malformed.
        """

        try:
            raw_aimbom, raw_reports = await self.client.get_aimbom(
                model_uuid, model_version
            )
        except StorageNotFoundError as e:
            raise ValidatorNotFoundError(str(e)) from e
        except StorageInvalidFileError as e:
            raise ValidatorInvalidAIMBOMError(str(e)) from e
        # Any other failure says nothing about the AIMBOM, so it must not be
        # reported as invalid.
        except (StorageConnectionError, StorageAuthError) as e:
            raise ValidatorStorageError(str(e)) from e
        # Another 4xx, a malformed response or an S3 error: retrying won't fix
        # it. Must come after the subclasses above.
        except StorageError as e:
            raise ValidatorReadError(str(e)) from e

        aimbom, aimbom_signed_by_coevolution = validate_report(
            BOMType.AIMBOM, raw_aimbom
        )

        reports, reports_signed_by_coevolution = validate_reports(
            raw_reports, REPORT_TYPES
        )

        # Check that the AIMBOM references exactly the given reports.
        check_links(aimbom, reports)

        # The reports count too: an AIMBOM signed by CoEvolution that links to
        # foreign reports is not signed by CoEvolution as a whole.
        signed_by_coevolution = aimbom_signed_by_coevolution and all(
            reports_signed_by_coevolution.values()
        )

        logger.info(
            "AIMBOM is valid for model_uuid=%s, model_version=%s, "
            "signed_by_coevolution=%s",
            model_uuid,
            model_version,
            signed_by_coevolution,
        )

        return signed_by_coevolution


def check_links(aimbom: AIMBOM, reports: Dict[ReportType, ReportModel]) -> None:
    """Check that the AIMBOM references exactly the given reports.

    Each external reference must have a known report type (from its comment),
    appear once, and point at the BOM-Link (`urn:cdx:{serial}/{version}`) of
    the report of that type. Every report must be referenced.

    Stops at the first problem found.

    Args:
        aimbom: The validated AIMBOM.
        reports: Mapping of `ReportType` to validated report.

    Raises:
        ValidatorLinkValidationError: On the first problem found.
    """

    referenced = set()

    for ref in aimbom.external_references:
        report_type = COMMENT_TO_REPORT.get(ref.comment)
        if report_type is None:
            raise ValidatorLinkValidationError(
                f"AIMBOM references an unknown report type '{ref.comment}'"
            )
        if report_type in referenced:
            raise ValidatorLinkValidationError(
                f"AIMBOM references {report_type.value} more than once"
            )
        referenced.add(report_type)

        report = reports.get(report_type)
        if report is None:
            raise ValidatorLinkValidationError(
                f"AIMBOM references {report_type.value}, but it is missing"
            )

        expected = bom_link(report.serial_number, report.version)
        if ref.url != expected:
            raise ValidatorLinkValidationError(
                f"AIMBOM references {report_type.value} as '{ref.url}', "
                f"but the report is '{expected}'"
            )

    for report_type in reports:
        if report_type not in referenced:
            raise ValidatorLinkValidationError(
                f"AIMBOM does not reference {report_type.value}"
            )


def validate_report(
    report_type: DocumentType, raw_report: Dict
) -> tuple[ReportModel | AIMBOM, bool]:
    """Validate a single raw report, or an AIMBOM, against the CycloneDX schema
    and its Pydantic model, and verify its signature.

    Pass `BOMType.AIMBOM` as `report_type` to validate an AIMBOM against the
    `AIMBOM` model.

    A valid signature from a key that is not in the trust list is not an
    error: it is returned as `signed_by_coevolution == False`, and each caller
    decides what to do with it.

    Args:
        report_type: The type of report being validated, or `BOMType.AIMBOM`.
        raw_report: The raw JSON dict for the report.

    Returns:
        The validated `ReportModel` instance, or `AIMBOM` for `BOMType.AIMBOM`,
        and whether it is signed by CoEvolution.

    Raises:
        ValidatorSchemaValidationError: When report validation fails.
        ValidatorSignatureError: When the signature is missing, malformed or
            invalid.
        signing.TrustListError: When the trust list is missing or malformed.
    """

    try:
        # Generic CycloneDX validation
        cyclonedx_validation.cdx_validate_dict(raw_report)

        # Schema-specific validation
        model_cls = DOCUMENT_MODELS[report_type]
        report = model_cls.model_validate(raw_report)
    # `ValidationError` is a subclass of `ValueError`, so it must come first.
    except ValidationError as e:
        raise ValidatorSchemaValidationError(
            f"Report {report_type.value} failed schema validation: {str(e)}"
        ) from e
    except ValueError as e:
        raise ValidatorSchemaValidationError(
            f"Report {report_type.value} is invalid: {str(e)}"
        ) from e

    # Verified on the raw report: the model may drop or reformat fields,
    # which would change the signed content.
    try:
        signed_by_coevolution = signing.verify_report(raw_report)
    except signing.SignatureVerificationError as e:
        raise ValidatorSignatureError(
            f"Report {report_type.value} has an invalid signature: {str(e)}"
        ) from e

    if not signed_by_coevolution:
        # Shows which document it was, and helps when a key was simply never
        # added to the trust list.
        logger.info(
            "Report %s is not signed by CoEvolution: signing key %s is not in "
            "the trust list",
            report_type.value,
            signing.public_key_fingerprint(signing.load_signer_certificate(raw_report)),
        )

    return report, signed_by_coevolution


def validate_reports(
    raw_reports: Dict[str, Dict],
    report_types: Iterable[ReportType],
) -> tuple[Dict[ReportType, ReportModel], Dict[ReportType, bool]]:
    """
    Validate a set of raw reports for a given model UUID and version.

    Args:
        raw_reports: A mapping of report type value to raw JSON dictionaries.
        report_types: Which report types to validate -- `REPORT_TYPES`
            for a new generation (every report type), or the changed
            `UPDATABLE_REPORT_TYPES` for an AIMBOM update.

    Returns:
        A mapping of `ReportType` to validated `ReportModel` instances,
        one entry per `report_types`, and for each, whether it is signed by
        CoEvolution.

    Raises:
        ValidatorMissingReportError: When a report of `report_types` is missing.
        ValidatorSchemaValidationError: When report validation fails.
        ValidatorSignatureError: When a signature is missing, malformed or
            invalid.
        signing.TrustListError: When the trust list is missing or malformed.
    """

    reports: Dict[ReportType, ReportModel] = {}
    signed_by_coevolution: Dict[ReportType, bool] = {}

    for report_type in report_types:
        raw_report = raw_reports.get(report_type.value)
        if raw_report is None:
            logger.warning("Report %s is missing", report_type.value)
            raise ValidatorMissingReportError(f"Report {report_type.value} is missing")

        reports[report_type], signed_by_coevolution[report_type] = validate_report(
            report_type, raw_report
        )
        logger.debug("Retrieved report %s", report_type.value)

    return reports, signed_by_coevolution


async def get_validator(
    client: StorageClient = Depends(get_storage_client),
) -> AIMBOMValidator:
    """
    FastAPI dependency that constructs an AIMBOMValidator.

    Args:
        client (StorageClient): Injected StorageClient dependency.

    Returns:
        AIMBOMValidator: An instance of AIMBOMValidator ready for use by request handlers.
    """

    return AIMBOMValidator(client=client)
