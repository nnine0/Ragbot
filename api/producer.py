import os
import json
import logging
from aiokafka import AIOKafkaProducer

logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_INGESTION_TOPIC = os.getenv("KAFKA_INGESTION_TOPIC", "document-ingestion")

_producer: AIOKafkaProducer | None = None


async def get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            client_id="rag-api",
            acks="all",
        )
        await _producer.start()
    return _producer


async def send_to_kafka(payload: dict) -> None:
    producer = await get_producer()
    message_bytes = json.dumps(payload).encode("utf-8")
    await producer.send_and_wait(KAFKA_INGESTION_TOPIC, message_bytes)
    logger.info("Produced message to topic %s: %s", KAFKA_INGESTION_TOPIC, payload.get("filename"))


async def close_producer() -> None:
    global _producer
    if _producer:
        await _producer.stop()
        _producer = None
