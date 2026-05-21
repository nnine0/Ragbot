<div align="center">
  <iframe src="https://nnine0.github.io/Ragbot/" width="100%" height="600px" style="border: 1px solid #30363d; border-radius: 8px;" title="Ragbot"></iframe>
  <br><br>
  <a href="https://nnine0.github.io/Ragbot/" target="_blank"><strong>Open Ragbot ↗</strong></a>
</div>

---

# Ragbot

Drag-and-drop RAG chatbot with ChromaDB, MinIO, and Redis.

## Architecture

```
Client (static HTML/JS)
    │
    ├── /api/* ──→ Vercel Proxy ──→ FastAPI Backend
    │                                    │
    │                              ┌─────┼─────────┐
    │                              │     │         │
    │                           ChromaDB  MinIO   Redis
    │                           (vectors) (files) (cache)
    │
    └── static files ──→ GitHub Pages / Vercel
```

## Quick Start

```bash
docker compose up -d
# Open http://localhost:8080
```

## Deployments

| Access Point | URL |
|---|---|
| **GitHub Pages** | [nnine0.github.io/Ragbot/](https://nnine0.github.io/Ragbot/) |
| **Vercel** | [ragreader-base.vercel.app](https://ragreader-base.vercel.app/) |

## Tech Stack

- **Backend**: FastAPI (Python 3.12)
- **Vector DB**: ChromaDB
- **Object Store**: MinIO
- **Cache**: Redis
- **Frontend**: Vanilla HTML/JS (drag-and-drop)
- **Deploy**: GitHub Pages + Vercel
