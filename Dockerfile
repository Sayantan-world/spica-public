# ── Stage 1: build the React frontend ────────────────────────────────────────
FROM node:22-slim AS frontend

WORKDIR /app/frontend

RUN corepack enable

COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm build

# ── Stage 2: Python runtime ──────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/tmp/hf_cache \
    XDG_CACHE_HOME=/tmp/.cache

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-docker.txt ./
RUN pip install --upgrade pip \
    && pip install --retries 5 --timeout 120 -r requirements-docker.txt

COPY backend/ ./backend/

COPY --from=frontend /app/frontend/dist ./frontend/dist

RUN mkdir -p /tmp/logs /tmp/hf_cache /tmp/.cache /tmp/user_data \
    && chmod -R 777 /tmp/logs /tmp/hf_cache /tmp/.cache /tmp/user_data
ENV LOGS_DIR=/tmp/logs
ENV USER_DATA_DIR=/tmp/user_data

ENV PORT=7860
EXPOSE 7860

CMD sh -c "uvicorn backend.api.main:app --host 0.0.0.0 --port ${PORT:-7860}"
