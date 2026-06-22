# GossipGene

A minimal chat prototype: a React frontend (Vercel AI SDK `useChat`) talking to a Python 
FastAPI + Pydantic AI agent that runs a local 3B model via Ollama, streamed over the Vercel AI Data Stream Protocol.

## Prerequisites

- [Ollama](https://ollama.com) running locally, with the model pulled:

```bash
ollama serve
ollama pull llama3.2:3b
```

## Backend

```bash
cd backend
poetry install
poetry run uvicorn main:app --port 8000
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Open the printed URL (default http://localhost:5173).
