import os
import uuid
import json
import logging
import io
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from dotenv import load_dotenv

from api.auth import extract_user_id, create_token
from api.producer import send_to_kafka, close_producer
from api.rate_limiter import check_rate_limit, close_redis
from api.models import UploadResponse, FeedbackRequest, HealthResponse
from api.metrics import instrumentator
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "ragreader-files")
MINIO_USE_SSL = os.getenv("MINIO_USE_SSL", "false").lower() == "true"

KAFKA_INGESTION_TOPIC = os.getenv("KAFKA_INGESTION_TOPIC", "document-ingestion")

CHROMA_HOST = os.getenv("CHROMA_HOST", "chroma-server")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

HF_EMBEDDING_MODEL = os.getenv("HF_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
HF_GENERATION_MODEL = os.getenv("HF_GENERATION_MODEL", "google/flan-t5-large")
HF_RERANKER_MODEL = os.getenv("HF_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")


@asynccontextmanager
async def lifespan(app: FastAPI):
    instrumentator.expose(app)
    yield
    await close_producer()
    await close_redis()


app = FastAPI(
    title="ragreader",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

instrumentator.instrument(app)


def get_minio_client():
    from minio import Minio
    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_USE_SSL,
    )
    if not client.bucket_exists(MINIO_BUCKET):
        client.make_bucket(MINIO_BUCKET)
    return client


class AuthRequest(BaseModel):
    user_id: str


@app.post("/auth/token")
async def auth_token(req: AuthRequest):
    token = create_token(req.user_id)
    return {"access_token": token, "token_type": "bearer", "user_id": req.user_id}


@app.get("/health")
async def health():
    statuses = {}
    try:
        import chromadb
        c = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        c.heartbeat()
        statuses["chroma"] = "ok"
    except Exception:
        statuses["chroma"] = "unreachable"

    try:
        from aiokafka import AIOKafkaProducer
        p = AIOKafkaProducer(bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"))
        await p.start()
        await p.stop()
        statuses["kafka"] = "ok"
    except Exception:
        statuses["kafka"] = "unreachable"

    try:
        import redis.asyncio as aioredis
        r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT)
        await r.ping()
        await r.close()
        statuses["redis"] = "ok"
    except Exception:
        statuses["redis"] = "unreachable"

    try:
        mc = get_minio_client()
        mc.list_buckets()
        statuses["minio"] = "ok"
    except Exception:
        statuses["minio"] = "unreachable"

    all_ok = all(v == "ok" for v in statuses.values())
    return HealthResponse(
        status="healthy" if all_ok else "degraded",
        services=statuses,
    )


@app.post("/upload")
async def upload_doc(
    file: UploadFile = File(...),
    user_id: str = Depends(extract_user_id),
):
    content = await file.read()
    file_size = len(content)

    allowed, status_code = await check_rate_limit(user_id)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    file_ext = os.path.splitext(file.filename)[1].lower()
    allowed_exts = {".pdf", ".txt", ".docx", ".md", ".csv", ".html", ".json"}
    if file_ext not in allowed_exts:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_ext}")

    job_id = str(uuid.uuid4())
    object_path = f"{user_id}/{job_id}_{file.filename}"

    try:
        mc = get_minio_client()
        mc.put_object(
            MINIO_BUCKET,
            object_path,
            io.BytesIO(content),
            length=file_size,
            content_type=file.content_type or "application/octet-stream",
        )
    except Exception as e:
        logger.error("MinIO upload failed: %s", e)
        raise HTTPException(status_code=500, detail="File storage failed")

    try:
        file_url = f"{MINIO_ENDPOINT}/{MINIO_BUCKET}/{object_path}"
        await send_to_kafka({
            "job_id": job_id,
            "user_id": user_id,
            "file_url": file_url,
            "filename": file.filename,
            "content_type": file.content_type,
        })
    except Exception as e:
        logger.error("Kafka produce failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to queue ingestion job")

    return UploadResponse(
        job_id=job_id,
        status="processing",
        filename=file.filename,
    )


@app.post("/ask")
async def ask_question(
    question: str,
    user_id: str = Depends(extract_user_id),
):
    allowed, status_code = await check_rate_limit(user_id)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    async def event_generator():
        import asyncio
        import numpy as np
        import torch
        from chromadb import HttpClient as ChromaClient
        from sentence_transformers import SentenceTransformer

        chroma_client = ChromaClient(host=CHROMA_HOST, port=CHROMA_PORT)

        try:
            collection = chroma_client.get_collection("user_docs")
        except Exception:
            yield {"event": "error", "data": "No documents indexed yet"}
            return

        yield {"event": "status", "data": "searching"}

        embedder = SentenceTransformer(HF_EMBEDDING_MODEL)
        question_embedding = embedder.encode(question).tolist()

        results = collection.query(
            query_embeddings=[question_embedding],
            n_results=20,
            where={"user_id": user_id},
        )

        if not results["documents"] or not results["documents"][0]:
            yield {"event": "error", "data": "No relevant documents found"}
            return

        documents = results["documents"][0]
        ids = results["ids"][0] if results.get("ids") else []

        yield {"event": "status", "data": f"reranking {len(documents)} chunks"}

        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        reranker_tokenizer = AutoTokenizer.from_pretrained(HF_RERANKER_MODEL)
        reranker_model = AutoModelForSequenceClassification.from_pretrained(HF_RERANKER_MODEL)

        pairs = [[question, doc] for doc in documents]
        inputs = reranker_tokenizer(
            pairs,
            padding=True,
            truncation=True,
            return_tensors="pt",
            max_length=512,
        )
        with torch.no_grad():
            scores = reranker_model(**inputs).logits.squeeze(-1).tolist()

        if isinstance(scores, (int, float)):
            scores = [scores]
        top_indices = np.argsort(scores)[-5:][::-1]

        top_docs = [documents[i] for i in top_indices]
        top_ids = [ids[i] for i in top_indices] if ids else []

        yield {"event": "status", "data": "generating answer"}

        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        gen_tokenizer = AutoTokenizer.from_pretrained(HF_GENERATION_MODEL)
        gen_model = AutoModelForSeq2SeqLM.from_pretrained(HF_GENERATION_MODEL)

        context = "\n\n".join(top_docs)
        prompt = (
            "Answer the question based on the provided context.\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {question}\n\n"
            "Answer:"
        )

        inputs = gen_tokenizer(prompt, return_tensors="pt", max_length=512, truncation=True)
        outputs = gen_model.generate(
            **inputs,
            max_new_tokens=256,
            do_sample=True,
            temperature=0.3,
        )
        full_answer = gen_tokenizer.decode(outputs[0], skip_special_tokens=True)

        words = full_answer.split(" ")
        for i, word in enumerate(words):
            prefix = " " if i > 0 else ""
            yield {"event": "token", "data": f"{prefix}{word}"}
            await asyncio.sleep(0)

        try:
            import redis.asyncio as aioredis
            r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            cache_entry = json.dumps({
                "question": question,
                "answer": full_answer,
                "sources": top_ids,
            })
            await r.setex(f"qa:{user_id}:{hash(question)}", 3600, cache_entry)
            await r.close()
        except Exception:
            pass

        yield {"event": "done", "data": json.dumps({"answer": full_answer, "sources": top_ids})}

    return EventSourceResponse(event_generator())


@app.post("/feedback")
async def submit_feedback(
    feedback: FeedbackRequest,
    user_id: str = Depends(extract_user_id),
):
    import redis.asyncio as aioredis

    r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    entry = json.dumps({
        "user_id": user_id,
        "query_id": feedback.query_id,
        "thumbs_up": feedback.thumbs_up,
        "comment": feedback.comment,
    })
    await r.lpush("feedback", entry)
    await r.close()
    return {"status": "recorded"}
