import logging
from dataclasses import dataclass
from typing import Dict

from fastapi import Depends

from app.clients.storage_client import (
    StorageBadRequestError,
    StorageClient,
    StorageConflictError,
    StorageConnectionError,
    StorageError,
    StorageInvalidFileError,
    StorageOperationError,
    get_storage_client,
)
from app.models.requests import SigningFile, SigningMetadata, UploadReportMetadata
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


class ReportSignerUploadRejectedError(ReportSignerError):
    """Raised when the storage backend rejects the signed report, e.g. because
    the original doesn't belong to the given model version or bucket.
    """

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


@dataclass
class SigningResult:
    """How many files of a signing request were signed."""

    # Files signed and uploaded by this request.
    signed: int = 0
    # Files the storage backend reported as already signed.
    already_signed: int = 0


class ReportSigner:
    def __init__(self, client: StorageClient):
        self.client = client

    async def sign_and_upload(self, signing_metadata: SigningMetadata) -> SigningResult:
        """Download, sign and upload every file of a signing request.

        Each file is uploaded separately to `target_pool` / `target_bucket`,
        together with the ID of its original. A file the storage backend
        reports as already signed is treated as done, so a request can safely
        be retried.

        Errors specific to one file (missing, invalid, rejected) don't stop
        the remaining files from being signed; they are raised once all files
        have been processed. Storage and signing material errors affect every
        file, so they are raised immediately.

        Args:
            signing_metadata: Metadata describing the files to sign and the
                destination where the signed files should be uploaded.

        Returns:
            How many files were signed, and how many were already signed.

        Raises:
            ReportSignerMissingReportError: When a report cannot be found.
            ReportSignerInvalidFileError: When a report is not a JSON object.
            ReportSignerUploadRejectedError: When the storage backend rejects
                a signed report.
            ReportSignerProcessingError: When signing fails for any other reason.
            ReportSignerStorageError: When storage operations fail.
            ReportSignerSigningError: When the signing key and certificate
                currently loaded don't match.
        """

        logger.debug(
            "Starting signing pipeline model_uuid=%s, model_version=%s, files=%d",
            signing_metadata.model_uuid,
            signing_metadata.version,
            len(signing_metadata.files),
        )

        result = SigningResult()
        failures: list[ReportSignerError] = []

        for file in signing_metadata.files:
            try:
                report = await self._fetch_report(file.download_url)
                signed_report = self._sign_report(report)
                if await self._save_report(signed_report, file, signing_metadata):
                    result.signed += 1
                else:
                    result.already_signed += 1
            except (
                ReportSignerMissingReportError,
                ReportSignerInvalidFileError,
                ReportSignerUploadRejectedError,
                ReportSignerProcessingError,
            ) as e:
                logger.warning(
                    "Failed to sign file=%s original_file_id=%s: %s",
                    file.filename,
                    file.id,
                    e,
                )
                failures.append(e)

        if failures:
            # The first failure decides the error type; the message lists all of them.
            raise type(failures[0])(
                "; ".join(str(failure) for failure in failures)
            ) from failures[0]

        logger.debug(
            "Signing completed model_uuid=%s, model_version=%s",
            signing_metadata.model_uuid,
            signing_metadata.version,
        )

        return result

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
                "Storage connection error retrieving report to sign: %s",
                e,
            )
            raise ReportSignerStorageError(
                f"Failed to retrieve report from storage: {str(e)}"
            ) from e
        except StorageInvalidFileError as e:
            logger.warning(
                "Report to sign is not valid JSON download_url=%s: %s",
                download_url,
                e,
            )
            raise ReportSignerInvalidFileError(
                f"Report to sign is not valid JSON ({download_url}): {str(e)}"
            ) from e
        except StorageOperationError as e:
            logger.warning(
                "Report to sign not found download_url=%s: %s",
                download_url,
                e,
            )
            raise ReportSignerMissingReportError(
                f"Report to sign is missing ({download_url}): {str(e)}"
            ) from e

        if not isinstance(report, dict):
            logger.warning(
                "Report to sign is not a JSON object download_url=%s",
                download_url,
            )
            raise ReportSignerInvalidFileError(
                f"Report to sign must be a JSON object ({download_url}), "
                f"got {type(report).__name__}"
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
            logger.error("Signing material mismatch while signing report: %s", e)
            raise ReportSignerSigningError(f"Failed to sign report: {str(e)}") from e
        except Exception as e:
            logger.error("Error signing report: %s", e)
            raise ReportSignerProcessingError(f"Failed to sign report: {str(e)}") from e

    async def _save_report(
        self,
        signed_report: Dict,
        file: SigningFile,
        signing_metadata: SigningMetadata,
    ) -> bool:
        """Persist the signed report to the configured storage backend.

        Args:
            signed_report: The signed report to store.
            file: The original file the signed report is a copy of.
            signing_metadata: Metadata describing where the signed report
                should be uploaded.

        Returns:
            `True` if the signed report was uploaded, `False` if the original
            had already been signed.

        Raises:
            ReportSignerUploadRejectedError: If the storage backend rejects the
                signed report.
            ReportSignerStorageError: If storage operations fail.
        """

        upload_report_metadata = UploadReportMetadata(
            model_uuid=signing_metadata.model_uuid,
            version=signing_metadata.version,
            pool=signing_metadata.target_pool,
            bucket=signing_metadata.target_bucket,
            tags=",".join(signing_metadata.tags) if signing_metadata.tags else None,
            original_file_id=file.id,
        )

        try:
            await self.client.save_file(
                file=signed_report,
                filename=file.filename,
                upload_report_metadata=upload_report_metadata,
            )
            logger.debug("Signed report saved successfully file=%s", file.filename)
            return True
        except StorageConflictError:
            # Already signed, e.g. by an earlier attempt of this request.
            logger.info(
                "File already signed file=%s original_file_id=%s",
                file.filename,
                file.id,
            )
            return False
        except StorageBadRequestError as e:
            logger.warning(
                "Signed report rejected file=%s original_file_id=%s: %s",
                file.filename,
                file.id,
                e,
            )
            raise ReportSignerUploadRejectedError(
                f"Signed report '{file.filename}' was rejected: {e}"
            ) from e
        except StorageError as e:
            logger.error("Error saving signed report: %s", e)
            raise ReportSignerStorageError(
                f"Storage error while saving signed report: {e}"
            ) from e


async def get_signer(
    client: StorageClient = Depends(get_storage_client),
) -> ReportSigner:
    return ReportSigner(client)
