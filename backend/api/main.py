import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.process_user_data.db import init_db
from backend.process_user_data.phrase_audio import start_phrase_audio_warmup
from backend.process_user_data.routes import router as account_router

app = FastAPI(
    title="SPICA API",
    description="Account-based AAC chat with multimodal sensing",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(account_router)

_log = logging.getLogger(__name__)
_ready = False


@app.on_event("startup")
def _startup():
    global _ready
    init_db()
    start_phrase_audio_warmup()
    _ready = True
    _log.info("SPICA API ready")


@app.get("/health")
def health():
    return {"status": "ok", "models_ready": _ready}


_frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="static")
