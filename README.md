# ragreader

Production-grade Retrieval-Augmented Generation (RAG) tool built for scale — decoupled ingestion, semantic caching, two-stage retrieval, and Kubernetes-native autoscaling.

## Architecture

```
                    ┌──────────┐
                    │  Client   │
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │  FastAPI  │  JWT Auth + Rate Limiting
                    │  (API)   │  Prometheus /metrics
                    └──┬───┬───┘
                       │   │
              ┌────────┘   └────────┐
              ▼                      ▼
       ┌──────────┐          ┌──────────┐
       │  Kafka   │          │  Redis    │  Semantic Cache + Rate Limit
       │ (32 part)│          │ (Stack)   │
       └────┬─────┘          └──────────┘
            │
       ┌────▼─────┐
       │  Worker   │  Unstructured.io + OCR → LangChain chunks → Embed
       │  (HPA)   │  BGE-Reranker (two-stage)
       └────┬─────┘
            │
       ┌────▼─────┐
       │ ChromaDB │  Multi-tenant (user_id filter)
       └──────────┘

       ┌──────────┐
       │  MinIO   │  Claim Check pattern (files via object store)
       └──────────┘
```

## Features

| Feature | Implementation |
|---------|---------------|
| **Multi-Tenancy** | Every chunk tagged with `user_id`; queries filtered by `where={"user_id": "..."}` |
| **Claim Check Pattern** | Large files stored in MinIO; only metadata sent through Kafka |
| **Semantic Caching** | Redis VL caches Q&A pairs; 95% similarity threshold avoids redundant LLM calls |
| **Two-Stage Retrieval** | ChromaDB top-20 → BGE-Reranker top-5 → LLM generation |
| **Doc Preprocessing** | Unstructured.io partitioning + Tesseract OCR (tables, headers, scanned docs) |
| **Dead Letter Queue** | Failed messages routed to `document-ingestion-dlq` topic |
| **SSE Streaming** | Server-Sent Events for real-time token streaming to frontend |
| **Rate Limiting** | Redis sliding window per user (configurable) |
| **RAG Evaluation** | RAGAS faithfulness/relevancy CronJob (weekly) |
| **Self-Hosted LLM** | HuggingFace pipelines — no API key required |
| **K8s HPA** | API scales on CPU/memory; Worker scales on Kafka consumer lag |

## Project Structure

```
ragreader/
├── api/                     # FastAPI application
│   ├── main.py             # Endpoints: /upload, /ask (SSE), /feedback, /health
│   ├── auth.py             # JWT authentication
│   ├── producer.py         # Async Kafka producer (aiokafka)
│   ├── rate_limiter.py     # Redis-based rate limiting
│   ├── models.py           # Pydantic schemas
│   └── metrics.py          # Prometheus instrumentation
├── worker/                  # Kafka consumer & RAG logic
│   ├── processor.py        # Consumer with DLQ support
│   ├── document_processor.py # Unstructured.io partitioning + OCR
│   ├── rag_engine.py       # Generation pipeline (HuggingFace)
│   └── reranker.py         # BGE-Reranker for two-stage retrieval
├── chromadb/               # ChromaDB config
├── redis/                  # Redis config
├── minio/                  # MinIO setup script
├── static/                 # HTML/JS frontend
├── k8s/                    # Kubernetes manifests
│   ├── api-deployment.yaml
│   ├── worker-deployment.yaml
│   ├── chroma-statefulset.yaml
│   ├── kafka-statefulset.yaml
│   ├── minio-deployment.yaml
│   ├── redis-deployment.yaml
│   ├── prometheus-adapter.yaml
│   └── ragas-cronjob.yaml
├── docker-compose.yml      # Local development (7 services)
├── Dockerfile.api
├── Dockerfile.worker
└── requirements.txt
```

## Quick Start (Local)

```bash
# 1. Start all services
docker-compose up -d

# 2. Get a JWT token (run once)
curl -X POST http://localhost:8080/auth/login \
  -H "Content-Type: application/json" \
  -d '{"user_id": "demo"}'

# 3. Upload a document
curl -X POST http://localhost:8080/upload \
  -H "Authorization: Bearer <token>" \
  -F "file=@document.pdf"

# 4. Ask a question
curl -X POST http://localhost:8080/ask \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is this document about?"}'
```

## Production Deployment (K8s)

```bash
# 1. Create namespace
kubectl apply -f k8s/namespace.yaml

# 2. Create secrets
kubectl create secret generic ragreader-secrets \
  --namespace=ragreader \
  --from-literal=jwt-secret='<strong-random-secret>' \
  --from-literal=minio-access-key='minioadmin' \
  --from-literal=minio-secret-key='minioadmin'

# 3. Deploy infrastructure
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/kafka-statefulset.yaml
kubectl apply -f k8s/chroma-statefulset.yaml
kubectl apply -f k8s/minio-deployment.yaml
kubectl apply -f k8s/redis-deployment.yaml

# 4. Deploy application
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/worker-deployment.yaml

# 5. Deploy monitoring
kubectl apply -f k8s/prometheus-adapter.yaml
kubectl apply -f k8s/ragas-cronjob.yaml
```

## Scaling Strategy

| Component | Strategy |
|-----------|----------|
| **API** | Horizontal scaling via HPA (CPU > 70%) |
| **Worker** | Scale on Kafka consumer lag (> 100 messages behind) |
| **Kafka** | 32 partitions = 32 concurrent consumers |
| **ChromaDB** | StatefulSet with SSD persistent volume |
| **LLM** | HuggingFace pipelines; upgrade to vLLM on GPU for scale |
| **Vector DB** | ChromaDB for MVP; migrate to Milvus/Qdrant at billion-vector scale |

## Environment Variables

See `.env.example` for all configurable variables.

## License

MIT
