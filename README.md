# SPICA

AAC chat agent. Partners send messages; the signed-in AAC user picks among four
replies (or taps the picture board). A central orchestrator runs a fixed tool
plan: load profile, retrieve memory, retrieve facts, generate options, persist.

## New VM

1. Install Python 3.12, [uv](https://docs.astral.sh/uv/), Node 22+, pnpm, and PostgreSQL 16 with `pgvector`.
2. Create DB user/db (`spica` / `spica` is the default in `.env.example`).
3. Clone this repo. Copy env and keys:

```bash
cp .env.example .env
cp packages.env.sh.example .packages.env.sh   # optional; setup.sh does this
mkdir -p backend/.llm_enpoints
printf '%s' 'YOUR_OPENAI_KEY' > backend/.llm_enpoints/.openai_key
printf '%s' 'YOUR_NIM_KEY'    > backend/.llm_enpoints/.nim_key
```

4. Put keys only in those two files (or set `OPENAI_API_KEY` / `NIM_API_KEY` in `.env`). Never commit `.env`, `.packages.env.sh`, or `backend/.llm_enpoints/`.
5. Install and run:

```bash
./setup.sh
./run.sh
```

Frontend `:5001`, API `:5002`. Edit `.packages.env.sh` if caches should not live under `$HOME/.spica-packages`.

## How the agent uses memory

Uploads are chunked, embedded with nomic (`nomic-ai/nomic-embed-text-v1.5`), and stored in Postgres `account_memory_chunks` (pgvector). Account-level facts/relations live on `accounts`.

On each partner turn the orchestrator calls tools in order:

1. `get_session` / `load_profile`
2. `retrieve_memory` (top-2 non-fact chunks by cosine)
3. `retrieve_facts` (top-2 fact chunks, else ranked `accounts.facts`)
4. `format_history`
5. `generate_reply_options` (Luna; four candidates)
6. `store_pending` until the user picks, then `commit_turn` + `write_memory`

Picture-board taps inside the 5s window skip generation and `commit_turn` directly. Later turns retrieve that reply through history + vector search.
