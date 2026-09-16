# SPICA — Project Guide

## What This Project Does

SPICA is an AAC chat **agent** that **speaks as the signed-in user**. Partners send
messages; the AAC user picks among 4 reply options. Optional webcam sensing
(emotion, hand gesture, head nod/shake) is captured for 5s after each partner
message and shapes the chit-chat and persona-alternate candidates.

A central orchestrator (`backend/agent/orchestrator.py`) runs a fixed tool plan.
Tools do retrieval, Luna generation, and persist. The LLM does not pick tools.

---

## Architecture

```
frontend/ React + Vite + TypeScript
  AccountNav          auth, uploads, process stored data
  AccountChatPanel    sessions + 4-option picker + multimodal capture
  useSensing          MediaPipe face + gesture + head nod/shake

backend/ Python (uv env: spica)
  api/main.py                   FastAPI — /health + /account/*
  agent/                        orchestrator + named tools
  process_user_data/            accounts, uploads, nomic embeddings, Luna tools
  config/settings.py            Pydantic settings
  .llm_enpoints/.openai_key     OpenAI API key (gitignored)
```

---

## How to Run

```bash
bash setup.sh
./run.sh
# FastAPI :5002 · React :5001
```

Or via systemd: `spica-backend` / `spica-frontend`.

---

## Configuration

Copy `.env.example` → `.env`. Important keys:

- `DATABASE_URL` — Postgres
- `OPENAI_MODEL` / `OPENAI_KEY_PATH` — Luna for processing + chat
- `USER_EMBED_MODEL` — nomic embeddings for account memory

API keys: `backend/.llm_enpoints/.openai_key` and `backend/.llm_enpoints/.nim_key`.

---

## Code Style

- Keep comments minimal.
- Skip `from __future__ import annotations` (Python 3.10+).
- Never use local Ollama models on this host — account chat uses OpenAI Luna.
