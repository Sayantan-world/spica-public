import io
import logging
import subprocess
import tempfile
import wave
from pathlib import Path

from backend.config.settings import settings

_log = logging.getLogger(__name__)
_DEFAULT_NIM_KEY = Path(__file__).resolve().parents[1] / ".llm_enpoints" / ".nim_key"

_DOWN_MSG = "API is down, unable to use the service at this moment"


class NimSpeechUnavailable(RuntimeError):
    """Raised when NVIDIA NIM speech cannot complete the request."""


def _load_nim_key() -> str:
    if settings.nim_api_key.strip():
        return settings.nim_api_key.strip()
    path = Path(settings.nim_key_path)
    if not path.is_file():
        path = _DEFAULT_NIM_KEY
    if not path.is_file():
        raise NimSpeechUnavailable(_DOWN_MSG)
    key = path.read_text(encoding="utf-8").strip()
    if not key:
        raise NimSpeechUnavailable(_DOWN_MSG)
    return key


def _riva_auth(function_id: str):
    import riva.client

    return riva.client.Auth(
        uri=settings.nim_grpc_server,
        use_ssl=True,
        metadata_args=[
            ["function-id", function_id],
            ["authorization", f"Bearer {_load_nim_key()}"],
        ],
        options=[
            ("grpc.max_receive_message_length", 64 * 1024 * 1024),
            ("grpc.max_send_message_length", 64 * 1024 * 1024),
        ],
    )


def _is_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def _ensure_wav_mono16(data: bytes, content_type: str = "") -> bytes:
    """Riva Whisper wants mono 16-bit WAV/OPUS/FLAC. Convert via ffmpeg if needed."""
    if _is_wav(data):
        try:
            with wave.open(io.BytesIO(data), "rb") as wf:
                if wf.getnchannels() == 1 and wf.getsampwidth() == 2:
                    return data
        except wave.Error:
            pass

    # Prefer ffmpeg when present (handles webm/opus/mp4 from MediaRecorder).
    ffmpeg = "ffmpeg"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.bin"
            dst = Path(tmp) / "out.wav"
            src.write_bytes(data)
            cmd = [
                ffmpeg,
                "-y",
                "-i",
                str(src),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-sample_fmt",
                "s16",
                str(dst),
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=60,
                check=False,
            )
            if proc.returncode == 0 and dst.is_file() and dst.stat().st_size > 44:
                return dst.read_bytes()
            _log.warning(
                "ffmpeg convert failed (%s): %s",
                proc.returncode,
                (proc.stderr or b"")[:300],
            )
    except FileNotFoundError:
        _log.warning("ffmpeg not installed; cannot convert %s to wav", content_type or "audio")
    except Exception:
        _log.exception("audio conversion failed")

    if _is_wav(data):
        return data
    raise NimSpeechUnavailable(
        "Could not convert audio to WAV for Whisper. Record again or install ffmpeg."
    )


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframesraw(pcm)
    return buf.getvalue()


def transcribe_audio(
    data: bytes,
    *,
    filename: str = "audio.wav",
    content_type: str = "audio/wav",
) -> dict:
    del filename
    if not data:
        raise ValueError("empty audio")
    if len(data) > settings.max_speech_bytes:
        raise ValueError("audio too large")

    try:
        import riva.client

        wav = _ensure_wav_mono16(data, content_type)
        auth = _riva_auth(settings.nim_whisper_function_id)
        asr = riva.client.ASRService(auth)
        config = riva.client.RecognitionConfig(
            language_code=settings.nim_whisper_language,
            max_alternatives=1,
            enable_automatic_punctuation=True,
            verbatim_transcripts=False,
        )
        resp = asr.offline_recognize(wav, config)
        parts: list[str] = []
        for result in resp.results:
            for alt in result.alternatives:
                t = (alt.transcript or "").strip()
                if t:
                    parts.append(t)
        text = " ".join(parts).strip()
        if not text:
            raise NimSpeechUnavailable("No speech detected in the recording.")
        return {
            "text": text,
            "provider": "nim",
            "model": settings.nim_whisper_model,
        }
    except NimSpeechUnavailable:
        raise
    except Exception as exc:
        _log.exception("NIM Whisper gRPC failed")
        raise NimSpeechUnavailable(_DOWN_MSG) from exc


def synthesize_speech(
    text: str,
    *,
    voice: str | None = None,
    emotion: str | None = None,
) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty text")
    text = text[:4000]
    magpie_voice = resolve_magpie_voice(voice, emotion)

    try:
        import riva.client
        from riva.client.proto.riva_audio_pb2 import AudioEncoding

        auth = _riva_auth(settings.nim_magpie_function_id)
        tts = riva.client.SpeechSynthesisService(auth)
        sample_rate = int(settings.nim_magpie_sample_rate_hz)
        resp = tts.synthesize(
            text,
            magpie_voice,
            settings.nim_magpie_language,
            sample_rate_hz=sample_rate,
            encoding=AudioEncoding.LINEAR_PCM,
        )
        pcm = resp.audio or b""
        if not pcm:
            raise NimSpeechUnavailable(_DOWN_MSG)
        wav = _pcm_to_wav(pcm, sample_rate)
        return {
            "audio": wav,
            "media_type": "audio/wav",
            "provider": "nim",
            "model": settings.nim_magpie_model,
            "voice": magpie_voice,
        }
    except NimSpeechUnavailable:
        raise
    except Exception as exc:
        _log.exception("NIM Magpie gRPC failed")
        raise NimSpeechUnavailable(_DOWN_MSG) from exc


SAMPLE_VOICE_TEXT = "Your sample voice"

VOICE_OPTIONS = [
    {"id": "Jason", "label": "Jason", "gender": "male"},
    {"id": "Leo", "label": "Leo", "gender": "male"},
    {"id": "Ray", "label": "Ray", "gender": "male"},
    {"id": "Mia", "label": "Mia", "gender": "female"},
    {"id": "Aria", "label": "Aria", "gender": "female"},
    {"id": "Sofia", "label": "Sofia", "gender": "female"},
]

_VOICE_IDS = {v["id"].lower(): v["id"] for v in VOICE_OPTIONS}

# Voices that expose Fearful tone (used for SURPRISED).
_FEARFUL_VOICES = {"Sofia", "Ray"}


def normalize_voice(voice: str | None, *, strict: bool = True) -> str:
    key = (voice or "").strip()
    if not key:
        return "Jason"
    found = _VOICE_IDS.get(key.lower())
    if not found:
        if strict:
            raise ValueError("invalid voice preference")
        return "Jason"
    return found


def resolve_magpie_voice(voice: str | None, emotion: str | None = None) -> str:
    """Map preferred speaker + webcam emotion → Magpie multilingual voice id."""
    base = normalize_voice(voice, strict=False)
    emo = (emotion or "").strip().upper()
    tone: str | None = None
    if emo == "HAPPY":
        tone = "Happy"
    elif emo == "FRUSTRATED":
        tone = "Angry"
    elif emo == "SURPRISED":
        tone = "Fearful" if base in _FEARFUL_VOICES else "Neutral"
    elif emo == "NEUTRAL":
        tone = "Neutral"
    # No emotion / webcam off → default base tone (no suffix).
    if tone:
        return f"Magpie-Multilingual.EN-US.{base}.{tone}"
    return f"Magpie-Multilingual.EN-US.{base}"
