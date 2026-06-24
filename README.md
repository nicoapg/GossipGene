# GossipGene

A minimal chat prototype: a React frontend (Vercel AI SDK `useChat`) talking to a Python 
FastAPI + Pydantic AI agent that runs a local 3B model via Ollama, streamed over the Vercel AI Data Stream Protocol.

## Prerequisites

- [Ollama](https://ollama.com) running locally, with the model pulled:

```bash
ollama serve
ollama pull qwen2.5:7b          # generation/agents (see MODEL_NAME in retrieval.py)
ollama pull nomic-embed-text    # dense embeddings for hybrid /retrieve
```

## Backend

```bash
cd backend
poetry install
poetry run python -m retrieval build   # one-time: builds the dense embedding cache (~57k rows)
poetry run uvicorn main:app --port 8000
```

The `retrieval build` step embeds every gene row once and caches the matrix next to the
dataset; `/retrieve` loads that cache and fails fast if it is missing.

## Run with Docker

Starts the backend (`:8000`) and frontend (`:5173`) in containers. Ollama stays on the host; the containers reach
it via `host.docker.internal`.

Prerequisites:

- Docker (with Compose).
- [Ollama](https://ollama.com) running on the host with both models pulled:

```bash
ollama serve
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
```

Then bring everything up:

```bash
docker compose up --build
```

Open http://localhost:5173. The gitignored dataset and embedding cache in `data-science/` are mounted into the backend, 
so an existing `.npy` cache is reused. If the cache is missing, build it once inside the container:

```bash
docker compose run --rm backend python -m retrieval build
```

## Frontend - on its own.

```bash
cd frontend
npm install
npm run dev
```

Open the printed URL (default http://localhost:5173).
