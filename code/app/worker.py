import asyncio
import json
import logging
import signal
from contextlib import suppress

from aiokafka import AIOKafkaConsumer
from pydantic import ValidationError

from app.clients.orchestrator_client import get_orchestrator_client
from app.core.config import settings
from app.core.logging import setup_logging
from app.models.requests import GenerationMetadata
from app.services import signing
from app.services.generator import (
    AIMBOMGenerator,
    GeneratorGenerationError,
    GeneratorMissingReportError,
    GeneratorStorageError,
)
from app.utils.utils import AIMBOMTier

# Configure logging
log_level = getattr(logging, settings.LOG_LEVEL, logging.INFO)
setup_logging(log_level)

logger = logging.getLogger(__name__)


class WorkerShutdown(Exception):
    """Raised when the worker is shutting down."""


class WorkerInvalidPayloadError(Exception):
    """Raised when a Kafka event is missing fields required for its event type."""


shutdown_event = asyncio.Event()

UPDATED_AIMBOM_EVENT = "updated-aimbom-requested"


def _extract_previous_aimbom_and_reports(
    event: dict,
) -> tuple[dict | None, dict]:
    """Derive the `previous_aimbom` and `reports` payloads from a raw Kafka event.

    For an `updated-aimbom-requested` event, the previous AIMBOM reference is
    read from `changedReports.aimbom_report` and the remaining entries of
    `changedReports` are used as the changed reports. For any other event
    type, `reports` is used directly and there is no previous AIMBOM.

    Args:
        event: The raw, JSON-decoded Kafka event.

    Returns:
        A `(previous_aimbom, reports)` tuple of raw dicts, suitable for
        constructing a `GenerationMetadata` instance.

    Raises:
        WorkerInvalidPayloadError: If the event is missing the fields
            required for its declared event type.
    """

    if event.get("event") == UPDATED_AIMBOM_EVENT:
        changed_reports = event.get("changedReports")

        if (
            not isinstance(changed_reports, dict)
            or "aimbom_report" not in changed_reports
        ):
            raise WorkerInvalidPayloadError(
                f"'{UPDATED_AIMBOM_EVENT}' event requires a "
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

    return previous_aimbom, reports


def _handle_shutdown_signal():
    """Handle termination signals by initiating a clean shutdown.

    Sets the module-level `shutdown_event` so running loops can exit
    gracefully.
    """

    logger.info("Shutdown signal received")
    shutdown_event.set()


async def consume_messages(
    consumer: AIOKafkaConsumer,
    generator: AIMBOMGenerator,
):
    """Consume Kafka messages and dispatch AIMBOM generation tasks.

    Args:
        consumer: An `AIOKafkaConsumer` instance to read events from Kafka.
        generator: An `AIMBOMGenerator` used to process generation requests.

    Returns:
        None
    """
    async for message in consumer:
        if shutdown_event.is_set():
            logger.info("Shutdown requested, stopping consumer loop")
            break

        try:
            event = message.value

            if not isinstance(event, dict):
                logger.error(
                    "Discarding non-object Kafka event payload=%r",
                    event,
                )

                # Commit invalid messages so they do not poison the queue
                await consumer.commit()

                continue

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

                # Commit invalid messages so they do not poison the queue
                await consumer.commit()

                continue

            # Determine previous AIMBOM and reports based on event type, and
            # validate the resulting shape against GenerationMetadata.
            try:
                previous_aimbom, reports = _extract_previous_aimbom_and_reports(event)

                generation_metadata = GenerationMetadata(
                    previous_aimbom=previous_aimbom,
                    reports=reports,
                )
            except (WorkerInvalidPayloadError, ValidationError) as e:
                logger.error(
                    "Invalid Kafka event payload model_uuid=%s: %s",
                    event.get("model_uuid"),
                    str(e),
                )

                # Commit invalid messages so they do not poison the queue
                await consumer.commit()

                continue

            tiered_aimbom = await generator.generate(
                event["model_uuid"],
                event["version"],
                generation_metadata,
            )

            logger.info(
                "AIMBOM generated successfully: model_uuid=%s, model_version=%s, serial_number=%s",
                event["model_uuid"],
                event["version"],
                tiered_aimbom[AIMBOMTier.TIER_1].serial_number,
            )

            # Commit ONLY after successful processing
            await consumer.commit()

        except GeneratorMissingReportError as e:
            logger.warning(
                "Missing reports for model_uuid=%s: %s",
                event.get("model_uuid"),
                str(e),
            )

            # Optional:
            # do not commit if you want retries later
            await consumer.commit()

        except GeneratorStorageError:
            logger.exception(
                "Storage error while generating AIMBOM model_uuid=%s",
                event.get("model_uuid"),
            )

            # No commit -> message will be retried

        except GeneratorGenerationError:
            logger.exception(
                "Generation error for model_uuid=%s",
                event.get("model_uuid"),
            )

            # Commit because this is likely a bad payload
            await consumer.commit()

        except json.JSONDecodeError:
            logger.exception("Failed to decode Kafka message")

            # Commit malformed messages
            await consumer.commit()

        except Exception:
            logger.exception("Unexpected error while processing Kafka message")

            # No commit -> retry later


async def main():
    """Entrypoint for the Kafka worker process.

    Sets up the orchestrator storage client, AIMBOM generator and Kafka
    consumer, runs the consume loop and performs clean shutdown on exit.
    """

    logger.info("Starting STRAE Kafka worker")

    client = None
    consumer = None

    try:
        # Validate signing material
        signing.validate_signing_material()

        client = get_orchestrator_client()
        generator = AIMBOMGenerator(client)

        consumer = AIOKafkaConsumer(
            settings.KAFKA_TOPIC,
            bootstrap_servers=[settings.KAFKA_BOOTSTRAP_SERVERS],
            group_id=settings.KAFKA_GROUP_ID,
            auto_offset_reset="latest",
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            enable_auto_commit=False,
        )

        await consumer.start()

        logger.info(
            "Kafka consumer started topic=%s group_id=%s",
            settings.KAFKA_TOPIC,
            settings.KAFKA_GROUP_ID,
        )

        await consume_messages(
            consumer,
            generator,
        )

    except asyncio.CancelledError:
        logger.info("Worker task cancelled")

    except Exception:
        logger.exception("Fatal worker error")

    finally:
        logger.info("Shutting down worker")

        if consumer is not None:
            logger.info("Stopping Kafka consumer")

            with suppress(Exception):
                await consumer.stop()

        if client is not None:
            logger.info("Closing client connection")

            with suppress(Exception):
                await client.close()

        logger.info("Worker shutdown completed")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (
        signal.SIGINT,
        signal.SIGTERM,
    ):
        loop.add_signal_handler(
            sig,
            _handle_shutdown_signal,
        )

    try:
        loop.run_until_complete(main())

    finally:
        pending = asyncio.all_tasks(loop)

        for task in pending:
            task.cancel()

        with suppress(Exception):
            loop.run_until_complete(
                asyncio.gather(
                    *pending,
                    return_exceptions=True,
                )
            )

        loop.close()
