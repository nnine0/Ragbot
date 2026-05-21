# Ragbot

[Launch Ragbot →](https://nnine0.github.io/Ragbot/)

Drag-and-drop RAG chatbot with ChromaDB, MinIO, and Redis.

## Architecture

```
Client → Vercel Proxy → FastAPI → ChromaDB / MinIO / Redis
```

## Quick Start

```bash
docker compose up -d
```

Open http://localhost:8080

## Deployments

| Access Point | URL |
|---|---|
| GitHub Pages | https://nnine0.github.io/Ragbot/ |
| Vercel | https://ragreader-base.vercel.app/ |

## Tech Stack

Backend: FastAPI · Vector DB: ChromaDB · Object Store: MinIO · Cache: Redis · Frontend: Vanilla HTML/JS · Deploy: GitHub Pages + Vercel
