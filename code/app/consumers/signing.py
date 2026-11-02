import logging

from pydantic import ValidationError

from app.models.requests import SigningMetadata
from app.services.report_signer import (
    ReportSigner,
    ReportSignerInvalidFileError,
    ReportSignerMissingReportError,
    ReportSignerProcessingError,
    ReportSignerSigningError,
    ReportSignerStorageError,
    ReportSignerUploadRejectedError,
)

logger = logging.getLogger(__name__)


async def handle_signing_event(event: dict, signer: ReportSigner):
    """Sign and upload the files of an event of the signing topic.

    Args:
        event: The JSON-decoded Kafka event.
        signer: A `ReportSigner` used to process signing requests.

    Errors are logged and not retried, like in the other CoEvolution
    components. For errors that aren't caused by the event itself, the event
    is logged so the request can be sent again.
    """

    logger.info(
        "Received report signing request model_uuid=%s version=%s",
        event.get("model_uuid"),
        event.get("version"),
    )

    try:
        signing_metadata = SigningMetadata.model_validate(event)
    except ValidationError as e:
        logger.error(
            "Invalid signing event payload model_uuid=%s: %s",
            event.get("model_uuid"),
            str(e),
        )

        return

    try:
        await signer.sign_and_upload(signing_metadata)

    except (
        ReportSignerMissingReportError,
        ReportSignerInvalidFileError,
        ReportSignerUploadRejectedError,
        ReportSignerProcessingError,
    ):
        logger.exception(
            "Failed to sign reports for model_uuid=%s",
            event.get("model_uuid"),
        )

        # The other files of the event have already been signed.
        return

    except ReportSignerStorageError:
        # Sending the event again is safe: files that were already uploaded
        # are reported as already signed and skipped.
        logger.exception(
            "Storage error while signing reports model_uuid=%s, "
            "request dropped event=%s",
            event.get("model_uuid"),
            event,
        )
        return

    except ReportSignerSigningError:
        logger.exception(
            "Signing material error while signing reports model_uuid=%s, "
            "request dropped event=%s",
            event.get("model_uuid"),
            event,
        )
        return

    logger.info(
        "Reports signed successfully: model_uuid=%s, model_version=%s, files=%d",
        signing_metadata.model_uuid,
        signing_metadata.version,
        len(signing_metadata.files),
    )
