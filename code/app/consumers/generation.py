import logging

from pydantic import ValidationError

from app.core.config import settings
from app.models.requests import GenerationMetadata
from app.services.generator import (
    AIMBOMGenerator,
    GeneratorGenerationError,
    GeneratorInvalidReportError,
    GeneratorMissingReportError,
    GeneratorSigningError,
    GeneratorStorageError,
    GeneratorUploadRejectedError,
)

logger = logging.getLogger(__name__)


class WorkerInvalidPayloadError(Exception):
    """Raised when a Kafka event is missing fields required for its event type."""


def _extract_previous_aimbom_and_reports(
    event: dict,
) -> tuple[dict | None, dict]:
    """Derive the `previous_aimbom` and `reports` payloads from a raw Kafka event.

    For an `updated-aimbom-requested` event, the previous AIMBOM reference is
    read from `changedReports.aimbom_report` and the remaining entries of
    `changedReports` are used as the changed reports. For any other event
    type, `reports` is used directly and there is no previous AIMBOM.

    This only checks the structural shape needed to build a
    `GenerationMetadata` instance (e.g. that `aimbom_report` is present, so
    it can be popped out as `previous_aimbom`). Whether the *right* reports
    are present for an update (the assessment and risk reports, the gadgets
    report alone, or all three) is enforced by
    `GenerationMetadata` itself.

    Args:
        event: The raw, JSON-decoded Kafka event.

    Returns:
        A `(previous_aimbom, reports)` tuple of raw dicts, suitable for
        constructing a `GenerationMetadata` instance.

    Raises:
        WorkerInvalidPayloadError: If the event is missing the fields
            required for its declared event type.
    """

    if event.get("event") == settings.UPDATED_AIMBOM_EVENT:
        changed_reports = event.get("changedReports")

        if (
            not isinstance(changed_reports, dict)
            or "aimbom_report" not in changed_reports
        ):
            raise WorkerInvalidPayloadError(
                f"'{settings.UPDATED_AIMBOM_EVENT}' event requires a "
                "'changedReports.aimbom_report' field"
            )

        # Copy to avoid mutating the original Kafka message value.
        changed_reports = dict(changed_reports)
        previous_aimbom = changed_reports.pop("aimbom_report")
        reports = changed_reports
    else:
        previous_aimbom = None
        reports = event.get("reports")

        if not isinstance(reports, dict):
            raise WorkerInvalidPayloadError("Event requires a 'reports' field")

        # The orchestrator includes an `aimbom_report: null` placeholder in
        # new-generation requests, since no AIMBOM exists yet. Drop it so it
        # isn't rejected as an unknown report. A non-null value has no
        # meaning for a new generation, so reject it explicitly.
        if "aimbom_report" in reports:
            if reports["aimbom_report"] is not None:
                raise WorkerInvalidPayloadError(
                    "'reports.aimbom_report' must be null for a new "
                    f"generation; use a '{settings.UPDATED_AIMBOM_EVENT}' "
                    "event to update an existing AIMBOM"
                )

            # Copy to avoid mutating the original Kafka message value.
            reports = {k: v for k, v in reports.items() if k != "aimbom_report"}

    return previous_aimbom, reports


async def handle_generation_event(event: dict, generator: AIMBOMGenerator):
    """Run AIMBOM generation for an event of the AIMBOM topic.

    Args:
        event: The JSON-decoded Kafka event.
        generator: An `AIMBOMGenerator` used to process generation requests.

    Errors are logged and not retried, like in the other CoEvolution
    components. For errors that aren't caused by the event itself, the event
    is logged so the request can be sent again.
    """

    logger.info(
        "Received AIMBOM generation request model_uuid=%s version=%s",
        event.get("model_uuid"),
        event.get("version"),
    )

    # Basic payload validation
    required_fields = [
        "model_uuid",
        "version",
    ]

    missing_fields = [field for field in required_fields if field not in event]

    if missing_fields:
        logger.error(
            "Invalid Kafka event missing fields=%s payload=%s",
            missing_fields,
            event,
        )

        return

    # Determine previous AIMBOM and reports based on event type, and
    # validate the resulting shape against GenerationMetadata.
    try:
        previous_aimbom, reports = _extract_previous_aimbom_and_reports(event)

        generation_metadata = GenerationMetadata(
            model_uuid=event["model_uuid"],
            version=event["version"],
            previous_aimbom=previous_aimbom,
            reports=reports,
        )
    except (WorkerInvalidPayloadError, ValidationError) as e:
        logger.error(
            "Invalid Kafka event payload model_uuid=%s: %s",
            event.get("model_uuid"),
            str(e),
        )

        return

    try:
        aimbom = await generator.generate(
            generation_metadata,
        )

    except GeneratorMissingReportError as e:
        logger.warning(
            "Missing reports for model_uuid=%s: %s",
            event.get("model_uuid"),
            str(e),
        )

        return

    except GeneratorInvalidReportError as e:
        logger.warning(
            "Invalid report for model_uuid=%s: %s",
            event.get("model_uuid"),
            str(e),
        )

        return

    except GeneratorUploadRejectedError as e:
        logger.warning(
            "AIMBOM rejected by storage for model_uuid=%s: %s",
            event.get("model_uuid"),
            str(e),
        )

        return

    except GeneratorStorageError:
        logger.exception(
            "Storage error while generating AIMBOM model_uuid=%s, "
            "request dropped event=%s",
            event.get("model_uuid"),
            event,
        )
        return

    except GeneratorSigningError:
        logger.exception(
            "Signing material error while generating AIMBOM model_uuid=%s, "
            "request dropped event=%s",
            event.get("model_uuid"),
            event,
        )
        return

    except GeneratorGenerationError:
        logger.exception(
            "Generation error for model_uuid=%s",
            event.get("model_uuid"),
        )
        return

    logger.info(
        "AIMBOM generated successfully: model_uuid=%s, model_version=%s, serial_number=%s",
        event["model_uuid"],
        event["version"],
        aimbom.serial_number,
    )
