import asyncio
import json
import logging
import signal
from contextlib import suppress
from functools import partial
from typing import Awaitable, Callable

from aiokafka import AIOKafkaConsumer, TopicPartition

from app.clients.orchestrator_client import get_orchestrator_client
from app.consumers.generation import handle_generation_event
from app.consumers.signing import handle_signing_event
from app.core.config import settings
from app.core.logging import setup_logging
from app.services import signing
from app.services.generator import AIMBOMGenerator
from app.services.report_signer import ReportSigner

# Configure logging
log_level = getattr(logging, settings.LOG_LEVEL, logging.INFO)
setup_logging(log_level)

logger = logging.getLogger(__name__)


shutdown_event = asyncio.Event()


def _handle_shutdown_signal():
    """Handle termination signals by initiating a clean shutdown.

    Sets the module-level `shutdown_event` so running loops can exit
    gracefully.
    """

    logger.info("Shutdown signal received")
    shutdown_event.set()


# Processes a JSON-decoded event
EventHandler = Callable[[dict], Awaitable[None]]


def _deserialize(value: bytes) -> object | None:
    """Decode a Kafka message value as JSON.

    Returns `None` for values that aren't valid JSON, instead of raising from
    inside the consumer's iterator, so they are skipped like any other
    non-object payload.
    """

    try:
        return json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.error("Failed to decode Kafka message value=%r", value[:200])
        return None


def _create_consumer(
    topic: str, group_id: str, auto_offset_reset: str
) -> AIOKafkaConsumer:
    """Create a consumer for a single topic with manual commits."""

    return AIOKafkaConsumer(
        topic,
        bootstrap_servers=[settings.KAFKA_BOOTSTRAP_SERVERS],
        group_id=group_id,
        auto_offset_reset=auto_offset_reset,
        value_deserializer=_deserialize,
        enable_auto_commit=False,
    )


async def consume_messages(consumer: AIOKafkaConsumer, handler: EventHandler):
    """Consume Kafka messages and process each one with `handler`.

    Every message is committed once it has been processed, whether it
    succeeded or not, so a failing message never blocks the queue. Failures
    are logged and not retried. Only the message's own partition is committed.

    Args:
        consumer: An `AIOKafkaConsumer` instance to read events from Kafka.
        handler: Processes an event.

    Returns:
        None
    """
    async for message in consumer:
        if shutdown_event.is_set():
            logger.info("Shutdown requested, stopping consumer loop")
            break

        try:
            event = message.value

            if isinstance(event, dict):
                await handler(event)
            else:
                logger.error(
                    "Discarding non-object Kafka event topic=%s payload=%r",
                    message.topic,
                    event,
                )

        except Exception:
            logger.exception(
                "Unexpected error while processing Kafka message topic=%s, "
                "request dropped event=%r",
                message.topic,
                message.value,
            )

        await consumer.commit(
            {TopicPartition(message.topic, message.partition): message.offset + 1}
        )


async def main():
    """Entrypoint for the Kafka worker process.

    Sets up the orchestrator storage client, AIMBOM generator and report
    signer, and runs one Kafka consumer per topic: AIMBOM generation requests
    and report signing requests. Each consumer has its own consumer group, so
    the two topics are committed independently. Runs until a shutdown is
    requested or a consumer stops, then shuts down cleanly.
    """

    logger.info("Starting STRAE Kafka worker")

    client = None
    consumers: list[AIOKafkaConsumer] = []
    tasks: list[asyncio.Task] = []

    try:
        # Validate signing material
        signing.validate_signing_material()

        client = get_orchestrator_client()
        generator = AIMBOMGenerator(client)
        signer = ReportSigner(client)

        consumer_configs = [
            (
                settings.KAFKA_TOPIC,
                settings.KAFKA_GROUP_ID,
                settings.KAFKA_AUTO_OFFSET_RESET,
                partial(handle_generation_event, generator=generator),
            ),
            (
                settings.KAFKA_SIGNING_TOPIC,
                settings.KAFKA_SIGNING_GROUP_ID,
                settings.KAFKA_SIGNING_AUTO_OFFSET_RESET,
                partial(handle_signing_event, signer=signer),
            ),
        ]

        for topic, group_id, auto_offset_reset, handler in consumer_configs:
            consumer = _create_consumer(topic, group_id, auto_offset_reset)
            consumers.append(consumer)

            await consumer.start()

            logger.info(
                "Kafka consumer started topic=%s group_id=%s auto_offset_reset=%s",
                topic,
                group_id,
                auto_offset_reset,
            )

            tasks.append(
                asyncio.create_task(consume_messages(consumer, handler), name=topic)
            )

        shutdown_task = asyncio.create_task(shutdown_event.wait())

        done, _ = await asyncio.wait(
            [shutdown_task, *tasks], return_when=asyncio.FIRST_COMPLETED
        )

        # A consumer stopping on its own is a failure: stop the worker so it
        # gets restarted, instead of running with only one of the topics.
        for task in tasks:
            if task in done:
                if task.exception() is not None:
                    logger.error(
                        "Kafka consumer for topic=%s failed",
                        task.get_name(),
                        exc_info=task.exception(),
                    )
                else:
                    logger.error("Kafka consumer for topic=%s stopped", task.get_name())

        shutdown_task.cancel()

    except asyncio.CancelledError:
        logger.info("Worker task cancelled")

    except Exception:
        logger.exception("Fatal worker error")

    finally:
        logger.info("Shutting down worker")

        for task in tasks:
            task.cancel()

        with suppress(Exception):
            await asyncio.gather(*tasks, return_exceptions=True)

        for consumer in consumers:
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
