import logging
from typing import Dict

from fastapi import Depends

from app.clients.storage_client import (
    StorageClient,
    StorageConnectionError,
    StorageError,
    StorageInvalidFileError,
    StorageOperationError,
    get_storage_client,
)
from app.models.requests import SigningMetadata
from app.services import signing

logger = logging.getLogger(__name__)


class ReportSignerError(Exception):
    """Base exception for report signing errors."""

    pass


class ReportSignerMissingReportError(ReportSignerError):
    """Raised when the report to sign cannot be found in storage."""

    pass


class ReportSignerInvalidFileError(ReportSignerError):
    """Raised when the file to sign is not a JSON object."""

    pass


class ReportSignerStorageError(ReportSignerError):
    """Raised when an operation with the storage backend fails."""

    pass


class ReportSignerSigningError(ReportSignerError):
    """Raised when signing fails because the signing key and certificate do
    not match.
    """

    pass


class ReportSignerProcessingError(ReportSignerError):
    """Raised when signing fails due to unexpected issues."""

    pass


class ReportSigner:
    def __init__(self, client: StorageClient):
        self.client = client

    async def sign_and_upload(self, signing_metadata: SigningMetadata):
        """Download a report, sign it and upload the signed report to the
        configured storage backend.

        Args:
            signing_metadata: Metadata describing the report to sign and the
                destination where the signed report should be uploaded.

        Raises:
            ReportSignerMissingReportError: When the report cannot be found.
            ReportSignerInvalidFileError: When the report is not a JSON object.
            ReportSignerStorageError: When storage operations fail.
            ReportSignerSigningError: When the signing key and certificate
                currently loaded don't match.
            ReportSignerProcessingError: When signing fails for any other reason.
        """

        logger.debug(
            "Starting signing pipeline model_uuid=%s, model_version=%s",
            signing_metadata.model_uuid,
            signing_metadata.version,
        )

        # Only one file is expected in the list
        file = signing_metadata.files[0]
        filename = file.filename

        report = await self._fetch_report(file.download_url)
        signed_report = self._sign_report(report)
        await self._save_report(signed_report, filename, signing_metadata)

        logger.debug(
            "Signing completed model_uuid=%s, model_version=%s",
            signing_metadata.model_uuid,
            signing_metadata.version,
        )

    async def _fetch_report(self, download_url: str) -> Dict:
        """Retrieve the report to sign from the storage backend.

        Args:
            download_url: The download URL of the report.

        Returns:
            The report as a json dictionary.

        Raises:
            ReportSignerMissingReportError: When the report cannot be found.
            ReportSignerInvalidFileError: When the report is not a JSON object.
            ReportSignerStorageError: When storage operations fail.
        """

        try:
            report = await self.client.get_file_from_url(download_url=download_url)
        except StorageConnectionError as e:
            logger.error(
                "Storage connection error retrieving report to sign",
                exc_info=True,
            )
            raise ReportSignerStorageError(
                f"Failed to retrieve report from storage: {str(e)}"
            ) from e
        except StorageInvalidFileError as e:
            logger.warning(
                "Report to sign is not valid JSON download_url=%s",
                download_url,
                exc_info=True,
            )
            raise ReportSignerInvalidFileError(
                f"Report to sign is not valid JSON: {str(e)}"
            ) from e
        except StorageOperationError as e:
            logger.warning(
                "Report to sign not found download_url=%s",
                download_url,
                exc_info=True,
            )
            raise ReportSignerMissingReportError(
                f"Report to sign is missing: {str(e)}"
            ) from e

        if not isinstance(report, dict):
            logger.warning(
                "Report to sign is not a JSON object download_url=%s",
                download_url,
            )
            raise ReportSignerInvalidFileError(
                f"Report to sign must be a JSON object, got {type(report).__name__}"
            )

        return report

    def _sign_report(self, report: Dict) -> Dict:
        """Sign the report to ensure its integrity and authenticity.

        Args:
            report: The report to sign.

        Returns:
            The signed report.

        Raises:
            ReportSignerSigningError: If the signing key and certificate
                currently loaded don't match (see `signing.SigningError`).
            ReportSignerProcessingError: If signing fails for any other reason.
        """

        try:
            logger.debug("Signing report")
            signed_report = signing.sign_report(report)
            logger.debug("Report signed successfully")

            return signed_report
        except signing.SigningError as e:
            logger.error(
                "Signing material mismatch while signing report", exc_info=True
            )
            raise ReportSignerSigningError(f"Failed to sign report: {str(e)}") from e
        except Exception as e:
            logger.error("Error signing report", exc_info=True)
            raise ReportSignerProcessingError(f"Failed to sign report: {str(e)}") from e

    async def _save_report(
        self, signed_report: Dict, filename: str, signing_metadata: SigningMetadata
    ):
        """Persist the signed report to the configured storage backend.

        Args:
            signed_report: The signed report to store.
            filename: Name of the stored signed report.
            signing_metadata: Metadata describing where the signed report
                should be uploaded.

        Raises:
            ReportSignerStorageError: If storage operations fail.
        """

        try:
            await self.client.save_file(
                file=signed_report,
                filename=filename,
                upload_report_metadata=signing_metadata,
            )
            logger.debug("Signed report saved successfully")
        except StorageError as e:
            logger.error("Error saving signed report", exc_info=True)
            raise ReportSignerStorageError(
                f"Storage error while saving signed report: {e}"
            ) from e


async def get_signer(
    client: StorageClient = Depends(get_storage_client),
) -> ReportSigner:
    return ReportSigner(client)
