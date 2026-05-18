import os
import json
import tempfile
import logging
from kafka import KafkaConsumer, KafkaProducer
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings

from worker.document_processor import process_document

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_INGESTION_TOPIC = os.getenv("KAFKA_INGESTION_TOPIC", "document-ingestion")
KAFKA_DLQ_TOPIC = os.getenv("KAFKA_DLQ_TOPIC", "document-ingestion-dlq")
KAFKA_CONSUMER_GROUP = os.getenv("KAFKA_CONSUMER_GROUP", "rag-worker-group")

CHROMA_HOST = os.getenv("CHROMA_HOST", "chroma-server")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "user_docs")

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "ragreader-files")
MINIO_USE_SSL = os.getenv("MINIO_USE_SSL", "false").lower() == "true"

HF_EMBEDDING_MODEL = os.getenv("HF_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")


def download_from_minio(file_url: str) -> str:
    from minio import Minio
    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_USE_SSL,
    )
    path_parts = file_url.replace(f"{MINIO_ENDPOINT}/{MINIO_BUCKET}/", "").split("/", 1)
    if len(path_parts) == 2:
        object_path = "/".join(path_parts)
    else:
        object_path = path_parts[0]

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.basename(object_path))
    client.fget_object(MINIO_BUCKET, object_path, tmp.name)
    return tmp.name


def process_message(message_value: bytes) -> None:
    data = json.loads(message_value)
    user_id = data["user_id"]
    file_url = data["file_url"]
    filename = data["filename"]

    logger.info("Processing file: %s for user: %s", filename, user_id)

    local_path = download_from_minio(file_url)

    try:
        chunks = list(process_document(local_path, filename))
    finally:
        os.unlink(local_path)

    if not chunks:
        logger.warning("No chunks extracted from %s", filename)
        return

    chroma_client = chromadb.HttpClient(
        host=CHROMA_HOST,
        port=CHROMA_PORT,
        settings=Settings(anonymized_telemetry=False),
    )
    collection = chroma_client.get_or_create_collection(
        CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    embedder = SentenceTransformer(HF_EMBEDDING_MODEL)
    embeddings = embedder.encode(chunks).tolist()

    ids = [f"{user_id}_{filename}_{i}" for i in range(len(chunks))]
    metadatas = [
        {
            "user_id": user_id,
            "filename": filename,
            "chunk_index": i,
            "source": file_url,
        }
        for i in range(len(chunks))
    ]

    collection.add(
        documents=chunks,
        embeddings=embeddings,
        ids=ids,
        metadatas=metadatas,
    )

    logger.info("Indexed %d chunks from %s for user %s", len(chunks), filename, user_id)


def main():
    consumer = KafkaConsumer(
        KAFKA_INGESTION_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=KAFKA_CONSUMER_GROUP,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        max_poll_interval_ms=300000,
        max_poll_records=10,
    )

    dlq_producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        acks="all",
        retries=3,
    )

    logger.info("Worker started, consuming from %s", KAFKA_INGESTION_TOPIC)

    for message in consumer:
        try:
            process_message(message.value)
        except Exception as e:
            logger.error("Failed to process message: %s", e, exc_info=True)
            dlq_producer.send(KAFKA_DLQ_TOPIC, message.value)
            dlq_producer.flush()
            logger.info("Message sent to DLQ topic: %s", KAFKA_DLQ_TOPIC)


if __name__ == "__main__":
    main()
