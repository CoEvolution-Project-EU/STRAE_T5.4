import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.generator import AIMBOMGenerator
from app.logging import setup_logging
from app.storage import OrchestratorStorage

# Configure logging
log_level = getattr(logging, settings.LOG_LEVEL, logging.INFO)
setup_logging(log_level)

logger = logging.getLogger(__name__)


async def main():
    storage = OrchestratorStorage()
    generator = AIMBOMGenerator(storage)

    consumer = AIOKafkaConsumer(
        "strae",
        bootstrap_servers=["147.102.19.168:30004"],
        group_id="strae",
        auto_offset_reset="latest",
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        enable_auto_commit=False,
    )

    await consumer.start()

    print("Worker started, waiting for messages...")

    try:
        async for message in consumer:
            event = message.value

            logger.info(
                "Received AIMBOM generation request for model %s version %s",
                event["model_uuid"],
                event["version"],
            )

            try:
                await generator.generate(
                    event["model_uuid"], event["version"], event["reports"]
                )

                await consumer.commit()

            except Exception:
                logger.exception("AIMBOM generation failed")

    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
