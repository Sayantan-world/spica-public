"""Shared on-disk Magpie clips for picture-board phrases (all users)."""

import logging
import threading
import time
from pathlib import Path

from backend.config.settings import settings
from backend.process_user_data import nim_speech

_log = logging.getLogger(__name__)

PHRASE_ITEMS = [
    {"id": "yes", "speak": "Yes"},
    {"id": "no", "speak": "No"},
    {"id": "help", "speak": "Help"},
    {"id": "bathroom", "speak": "I need the bathroom"},
    {"id": "food", "speak": "I'm hungry"},
    {"id": "drink", "speak": "I'm thirsty"},
    {"id": "excuse", "speak": "Excuse me"},
    {"id": "like", "speak": "I like it"},
    {"id": "dislike", "speak": "I don't like it"},
    {"id": "more", "speak": "Tell me more"},
    {"id": "wait", "speak": "Wait"},
    {"id": "come", "speak": "Come here"},
]

PHRASE_IDS = {p["id"] for p in PHRASE_ITEMS}

DOWNLOAD_GAP_S = 3.0
ERROR_BACKOFF_STEP_S = 5.0

_lock = threading.Lock()
_thread: threading.Thread | None = None
_status: dict = {
    "status": "idle",
    "done": 0,
    "total": 0,
    "current": None,
    "message": "",
}


def cache_dir() -> Path:
    path = Path(settings.phrase_audio_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def sample_path(voice: str) -> Path:
    voice_n = nim_speech.normalize_voice(voice, strict=False)
    return cache_dir() / voice_n.lower() / "sample.wav"


def clip_path(voice: str, phrase_id: str) -> Path:
    voice_n = nim_speech.normalize_voice(voice, strict=False)
    return cache_dir() / voice_n.lower() / f"{phrase_id}.wav"


def total_clips() -> int:
    # 6 voice samples + 6×12 picture-board phrases
    return len(nim_speech.VOICE_OPTIONS) * (1 + len(PHRASE_ITEMS))


def count_ready() -> int:
    n = 0
    for v in nim_speech.VOICE_OPTIONS:
        sample = sample_path(v["id"])
        if sample.is_file() and sample.stat().st_size > 44:
            n += 1
        for p in PHRASE_ITEMS:
            path = clip_path(v["id"], p["id"])
            if path.is_file() and path.stat().st_size > 44:
                n += 1
    return n


def get_status() -> dict:
    with _lock:
        out = dict(_status)
    out["total"] = total_clips()
    if out["status"] != "running":
        out["done"] = count_ready()
        if out["done"] >= out["total"] and out["total"] > 0:
            out["status"] = "ready"
            out["message"] = "Offline phrases ready"
    return out


def _set_status(**kwargs) -> None:
    with _lock:
        _status.update(kwargs)


def read_clip(voice: str, phrase_id: str) -> tuple[bytes, str] | None:
    phrase_id = (phrase_id or "").strip().lower()
    if phrase_id not in PHRASE_IDS:
        return None
    path = clip_path(voice, phrase_id)
    if not path.is_file() or path.stat().st_size <= 44:
        return None
    return path.read_bytes(), "audio/wav"


def read_sample(voice: str) -> tuple[bytes, str] | None:
    path = sample_path(voice)
    if not path.is_file() or path.stat().st_size <= 44:
        return None
    return path.read_bytes(), "audio/wav"


def _synthesize_to(path: Path, text: str, voice: str) -> None:
    result = nim_speech.synthesize_speech(
        text,
        voice=voice,
        emotion="NEUTRAL",
    )
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(result["audio"])
    tmp.replace(path)


def _warm_once() -> None:
    total = total_clips()
    done = count_ready()
    _set_status(
        status="ready" if done >= total else "running",
        done=done,
        total=total,
        current=None,
        message="Offline phrases ready" if done >= total else "Downloading phrase audio…",
    )
    if done >= total:
        _log.info("phrase audio cache complete (%s/%s)", done, total)
        return

    error_streak = 0
    sample_text = nim_speech.SAMPLE_VOICE_TEXT

    def _save(label: str, path: Path, text: str, voice: str) -> None:
        nonlocal done, error_streak
        while True:
            _set_status(
                status="running",
                done=done,
                total=total,
                current=label,
                message=f"Downloading {done + 1}/{total}…",
            )
            try:
                _synthesize_to(path, text, voice)
                done += 1
                error_streak = 0
                _set_status(
                    status="ready" if done >= total else "running",
                    done=done,
                    total=total,
                    current=None,
                    message=(
                        "Offline phrases ready"
                        if done >= total
                        else f"Cached {done}/{total}"
                    ),
                )
                _log.info("cached %s (%s/%s)", label, done, total)
                time.sleep(DOWNLOAD_GAP_S)
                return
            except Exception as exc:
                error_streak += 1
                wait_s = DOWNLOAD_GAP_S + error_streak * ERROR_BACKOFF_STEP_S
                _set_status(
                    status="running",
                    done=done,
                    total=total,
                    current=label,
                    message=(
                        f"{exc} — retry in {wait_s:.0f}s "
                        f"(backoff +{error_streak * ERROR_BACKOFF_STEP_S:.0f}s)"
                    ),
                )
                _log.warning(
                    "phrase cache failed %s (streak=%s): %s",
                    label,
                    error_streak,
                    exc,
                )
                time.sleep(wait_s)

    for v in nim_speech.VOICE_OPTIONS:
        voice = v["id"]
        (cache_dir() / voice.lower()).mkdir(parents=True, exist_ok=True)

        sample = sample_path(voice)
        if not (sample.is_file() and sample.stat().st_size > 44):
            _save(f"{voice} · sample", sample, sample_text, voice)

        for p in PHRASE_ITEMS:
            path = clip_path(voice, p["id"])
            if path.is_file() and path.stat().st_size > 44:
                continue
            _save(f"{voice} · {p['speak']}", path, p["speak"], voice)

    _set_status(
        status="ready",
        done=total,
        total=total,
        current=None,
        message="Offline phrases ready",
    )


def start_phrase_audio_warmup() -> None:
    """Idempotent background fill of shared phrase WAV cache."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(
            target=_warm_once,
            name="phrase-audio-warmup",
            daemon=True,
        )
        _thread.start()
        _log.info("phrase audio warmup started → %s", cache_dir())
