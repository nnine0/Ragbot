import os
import uuid
import json
import io
import time
import logging
import tempfile
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from dotenv import load_dotenv
from pydantic import BaseModel

from api.auth import extract_user_id, create_token
from api.rate_limiter import check_rate_limit

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "ragbot-files")
MINIO_USE_SSL = os.getenv("MINIO_USE_SSL", "false").lower() == "true"
CHROMA_HOST = os.getenv("CHROMA_HOST", "chroma-server")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
HF_EMBEDDING_MODEL = os.getenv("HF_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
HF_GENERATION_MODEL = os.getenv("HF_GENERATION_MODEL", "google/flan-t5-large")
HF_RERANKER_MODEL = os.getenv("HF_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "")
ALLOWED_EXTS = {".pdf", ".txt", ".docx", ".md", ".csv", ".html", ".json", ".doc"}

_embedder = None
_reranker = None
_gen_model = None
_gen_tokenizer = None


def get_minio():
    from minio import Minio
    c = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=MINIO_USE_SSL)
    if not c.bucket_exists(MINIO_BUCKET):
        c.make_bucket(MINIO_BUCKET)
    return c


def get_chroma():
    import chromadb
    return chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)


def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedder: %s", HF_EMBEDDING_MODEL)
        _embedder = SentenceTransformer(HF_EMBEDDING_MODEL)
    return _embedder


def get_reranker():
    global _reranker
    if _reranker is None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        logger.info("Loading reranker: %s", HF_RERANKER_MODEL)
        _reranker = AutoModelForSequenceClassification.from_pretrained(HF_RERANKER_MODEL)
        _reranker.eval()
    return _reranker


def get_reranker_tokenizer():
    global _reranker
    get_reranker()
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(HF_RERANKER_MODEL)


def get_generation_model():
    global _gen_model, _gen_tokenizer
    if _gen_model is None:
        if OLLAMA_BASE_URL:
            logger.info("Using Ollama for generation: %s", OLLAMA_BASE_URL)
            return None, None
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        logger.info("Loading generation model: %s", HF_GENERATION_MODEL)
        _gen_tokenizer = AutoTokenizer.from_pretrained(HF_GENERATION_MODEL)
        _gen_model = AutoModelForSeq2SeqLM.from_pretrained(HF_GENERATION_MODEL)
        _gen_model.eval()
    return _gen_model, _gen_tokenizer


def process_document_bytes(content: bytes, filename: str) -> list[str]:
    ext = os.path.splitext(filename)[1].lower()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    try:
        tmp.write(content)
        tmp.flush()
        tmp.close()
        from unstructured.partition.auto import partition
        elements = partition(filename=tmp.name, strategy="auto", ocr_mode="auto", languages=["eng"])
        full_text = "\n\n".join([str(el) for el in elements])
    finally:
        os.unlink(tmp.name)

    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100, separators=["\n\n", "\n", ".", " ", ""])
    return splitter.split_text(full_text)


def index_document(user_id: str, filename: str, chunks: list[str], file_url: str):
    chroma = get_chroma()
    collection = chroma.get_or_create_collection("ragbot_docs", metadata={"hnsw:space": "cosine"})
    embedder = get_embedder()
    embeddings = embedder.encode(chunks).tolist()
    ids = [f"{user_id}_{filename}_{i}_{uuid.uuid4().hex[:8]}" for i in range(len(chunks))]
    metadatas = [{"user_id": user_id, "filename": filename, "chunk_index": i, "source": file_url} for i in range(len(chunks))]
    collection.add(documents=chunks, embeddings=embeddings, ids=ids, metadatas=metadatas)
    return len(chunks)


def delete_user_documents(user_id: str):
    chroma = get_chroma()
    try:
        collection = chroma.get_collection("ragbot_docs")
        results = collection.get(where={"user_id": user_id})
        if results["ids"]:
            collection.delete(ids=results["ids"])
    except Exception:
        pass


class AuthRequest(BaseModel):
    user_id: str


class FeedbackRequest(BaseModel):
    query_id: str
    thumbs_up: bool
    comment: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Ragbot starting up...")
    yield
    logger.info("Ragbot shutting down...")

app = FastAPI(title="Ragbot", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
_static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(_static_dir, "index.html"))


@app.post("/auth/token")
async def auth_token(req: AuthRequest):
    token = create_token(req.user_id)
    return {"access_token": token, "token_type": "bearer", "user_id": req.user_id}


@app.get("/health")
async def health():
    statuses = {}
    for name, check in [
        ("chroma", lambda: (get_chroma().heartbeat(), "ok")),
        ("minio", lambda: (get_minio().list_buckets(), "ok")),
        ("redis", None),
    ]:
        try:
            if name == "redis":
                import redis.asyncio as aioredis
                r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT)
                await r.ping()
                await r.close()
                statuses["redis"] = "ok"
            else:
                _, s = check()
                statuses[name] = s
        except Exception as e:
            statuses[name] = f"error: {e}"
    all_ok = all(v == "ok" for v in statuses.values())
    return {"status": "healthy" if all_ok else "degraded", "services": statuses}


@app.post("/upload")
async def upload_file(file: UploadFile = File(...), user_id: str = Depends(extract_user_id)):
    content = await file.read()
    file_size = len(content)
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"Unsupported file type: {ext}")

    allowed, code = await check_rate_limit(user_id)
    if not allowed:
        raise HTTPException(429, "Rate limit exceeded")

    object_path = f"{user_id}/{uuid.uuid4().hex}_{file.filename}"
    mc = get_minio()
    mc.put_object(MINIO_BUCKET, object_path, io.BytesIO(content), length=file_size, content_type=file.content_type or "application/octet-stream")
    file_url = f"{MINIO_ENDPOINT}/{MINIO_BUCKET}/{object_path}"

    try:
        chunks = process_document_bytes(content, file.filename)
        if not chunks:
            raise HTTPException(400, "No text could be extracted from the file")
        count = index_document(user_id, file.filename, chunks, file_url)
        logger.info("Indexed %d chunks from %s for %s", count, file.filename, user_id)
        return {"status": "indexed", "filename": file.filename, "chunks": count}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Processing failed for %s: %s", file.filename, e)
        raise HTTPException(500, f"Processing failed: {e}")


@app.get("/documents")
async def list_documents(user_id: str = Depends(extract_user_id)):
    chroma = get_chroma()
    try:
        collection = chroma.get_collection("ragbot_docs")
        results = collection.get(where={"user_id": user_id})
        filenames = set()
        for m in (results.get("metadatas") or []):
            if m:
                filenames.add(m.get("filename", "unknown"))
        return {"documents": sorted(filenames)}
    except Exception:
        return {"documents": []}


@app.delete("/documents")
async def clear_documents(user_id: str = Depends(extract_user_id)):
    delete_user_documents(user_id)
    return {"status": "cleared"}


@app.post("/ask")
async def ask_question(question: str, user_id: str = Depends(extract_user_id)):
    allowed, code = await check_rate_limit(user_id)
    if not allowed:
        raise HTTPException(429, "Rate limit exceeded")

    async def event_generator():
        import asyncio
        import numpy as np
        import torch
        import redis.asyncio as aioredis

        yield {"event": "status", "data": "searching"}

        chroma = get_chroma()
        try:
            collection = chroma.get_collection("ragbot_docs")
        except Exception:
            yield {"event": "error", "data": "No documents found. Upload a document first."}
            return

        embedder = get_embedder()
        question_embedding = embedder.encode(question).tolist()

        results = collection.query(query_embeddings=[question_embedding], n_results=20, where={"user_id": user_id})

        if not results.get("documents") or not results["documents"][0]:
            yield {"event": "error", "data": "No relevant content found in your documents"}
            return

        documents = results["documents"][0]
        ids = results["ids"][0] if results.get("ids") else []
        filenames = list(set(m.get("filename", "?") for m in (results.get("metadatas", [[]])[0] or []) if m))

        yield {"event": "status", "data": f"reranking {len(documents)} chunks"}

        reranker = get_reranker()
        reranker_tokenizer = get_reranker_tokenizer()
        pairs = [[question, doc] for doc in documents]
        inputs = reranker_tokenizer(pairs, padding=True, truncation=True, return_tensors="pt", max_length=512)
        with torch.no_grad():
            scores = reranker(**inputs).logits.squeeze(-1).tolist()
        if isinstance(scores, (int, float)):
            scores = [scores]
        top_indices = np.argsort(scores)[-5:][::-1]
        top_docs = [documents[i] for i in top_indices]
        top_ids = [ids[i] for i in top_indices] if ids else []

        yield {"event": "status", "data": "generating answer"}

        context = "\n\n".join(top_docs)
        prompt = f"Answer the question based on the provided context.\n\nContext:\n{context}\n\nQuestion: {question}\n\nAnswer:"

        answer = ""
        if OLLAMA_BASE_URL:
            import httpx
            async with httpx.AsyncClient(timeout=60) as client:
                payload = {
                    "model": os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
                    "prompt": prompt,
                    "stream": True,
                    "options": {"temperature": 0.3, "max_tokens": 512},
                }
                async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/generate", json=payload) as resp:
                    async for line in resp.aiter_lines():
                        if line.strip():
                            try:
                                chunk = json.loads(line)
                                token = chunk.get("response", "")
                                if token:
                                    answer += token
                                    yield {"event": "token", "data": token}
                            except json.JSONDecodeError:
                                pass
        else:
            gen_model, gen_tokenizer = get_generation_model()
            inputs = gen_tokenizer(prompt, return_tensors="pt", max_length=512, truncation=True)
            outputs = gen_model.generate(**inputs, max_new_tokens=256, do_sample=True, temperature=0.3)
            full = gen_tokenizer.decode(outputs[0], skip_special_tokens=True)
            for word in full.split(" "):
                prefix = " " if len(answer) > 0 else ""
                answer += f"{prefix}{word}"
                yield {"event": "token", "data": f"{prefix}{word}"}
                await asyncio.sleep(0)

        try:
            r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            cache_entry = json.dumps({"question": question, "answer": answer, "sources": top_ids})
            await r.setex(f"qa:{user_id}:{hash(question)}", 3600, cache_entry)
            await r.close()
        except Exception:
            pass

        yield {"event": "done", "data": json.dumps({"answer": answer, "sources": top_ids, "filenames": filenames})}

    return EventSourceResponse(event_generator())


@app.post("/feedback")
async def submit_feedback(feedback: FeedbackRequest, user_id: str = Depends(extract_user_id)):
    import redis.asyncio as aioredis
    r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    await r.lpush("feedback", json.dumps({"user_id": user_id, "query_id": feedback.query_id, "thumbs_up": feedback.thumbs_up, "comment": feedback.comment}))
    await r.close()
    return {"status": "recorded"}
