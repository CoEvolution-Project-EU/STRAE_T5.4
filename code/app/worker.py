import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer

from app.generator import AIMBOMGenerator
from app.storage import OrchestratorStorage

logger = logging.getLogger(__name__)


async def main():
    storage = OrchestratorStorage()

    generator = AIMBOMGenerator(storage)

    consumer = AIOKafkaConsumer(
        "requirements-uploaded",
        bootstrap_servers=["147.102.19.168:30004"],
        group_id="my-partner-group",
        auto_offset_reset="latest",
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        enable_auto_commit=False,
    )

    await consumer.start()

    try:
        async for message in consumer:
            event = message.value

            logger.info(
                "New requirements file received: %s",
                event["requirements_url"],
            )

            try:
                await generator.generate(
                    "123e4567-e89b-12d3-a456-426614174000",
                    "v1.0",
                )

                await consumer.commit()

            except Exception:
                logger.exception("AIMBOM generation failed")

    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
