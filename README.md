<div align="center">
  <br>
  <h1>Ragbot</h1>
  <p><em>Drag-and-drop RAG chatbot</em></p>
  <br>
  <a href="https://nnine0.github.io/Ragbot/" style="display:inline-block;padding:14px 40px;background:#6366f1;color:#fff;border-radius:8px;text-decoration:none;font-weight:600;font-size:1.2rem;">Launch Ragbot →</a>
  <br><br>
  <a href="https://nnine0.github.io/Ragbot/" style="color:#818cf8;">nnine0.github.io/Ragbot</a>
  <br><br>
  <sub>ChromaDB · MinIO · Redis · FastAPI · GitHub Pages</sub>
  <br><br>
</div>

---

## Architecture

```
Client (HTML/JS)
    │
    ├── /api/* ──→ Vercel Proxy ──→ FastAPI
    │                                    │
    │                              ┌─────┼─────────┐
    │                              │     │         │
    │                           ChromaDB  MinIO   Redis
    │                           (vectors) (files) (cache)
    │
    └── static ──→ GitHub Pages / Vercel
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
