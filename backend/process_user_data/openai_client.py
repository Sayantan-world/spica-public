import logging
from pathlib import Path

from openai import OpenAI

from backend.config.settings import settings

_log = logging.getLogger(__name__)
_DEFAULT_KEY_PATH = Path(__file__).resolve().parents[1] / ".llm_enpoints" / ".openai_key"

# Rough chars-per-token for English; used to enforce max input context.
_CHARS_PER_TOKEN = 4


def _load_openai_key() -> str:
    if settings.openai_api_key:
        return settings.openai_api_key.strip()
    path = Path(settings.openai_key_path)
    if not path.is_file():
        path = _DEFAULT_KEY_PATH
    if not path.is_file():
        raise RuntimeError(f"OpenAI key not found at {path}")
    return path.read_text(encoding="utf-8").strip()


def _client(timeout: float) -> OpenAI:
    kwargs: dict = {
        "api_key": _load_openai_key(),
        "timeout": timeout,
    }
    base = (settings.openai_base_url or "").strip()
    if base:
        kwargs["base_url"] = base
    return OpenAI(**kwargs)


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    max_chars = max_tokens * _CHARS_PER_TOKEN
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _messages_token_budget(messages: list[dict], max_input_tokens: int) -> list[dict]:
    """Keep total prompt under max_input_tokens by trimming the last user message."""
    if not messages:
        return messages
    fixed = messages[:-1]
    last = dict(messages[-1])
    fixed_text = "\n".join(str(m.get("content") or "") for m in fixed)
    fixed_tokens = estimate_tokens(fixed_text)
    remaining = max(64, max_input_tokens - fixed_tokens)
    content = str(last.get("content") or "")
    last["content"] = truncate_to_tokens(content, remaining)
    return [*fixed, last]


def _output_text(response) -> str:
    text = getattr(response, "output_text", None)
    if text and str(text).strip():
        return str(text).strip()
    parts: list[str] = []
    for item in getattr(response, "output", None) or []:
        for block in getattr(item, "content", None) or []:
            btype = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
            if btype in ("output_text", "text"):
                value = getattr(block, "text", None)
                if value is None and isinstance(block, dict):
                    value = block.get("text")
                if value:
                    parts.append(str(value))
    joined = "\n".join(parts).strip()
    if joined:
        return joined
    raise RuntimeError(f"empty response from {settings.openai_model}")


def openai_chat(
    messages: list[dict],
    *,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    max_input_tokens: int | None = None,
    on_fallback=None,
) -> str:
    """Chat via OpenAI Responses API (gpt-5.6-luna, medium effort)."""
    del temperature  # reasoning models ignore temperature; keep for call-site compat
    model = settings.openai_model or "gpt-5.6-luna"
    timeout = float(settings.openai_timeout_s)
    max_input = int(
        max_input_tokens
        if max_input_tokens is not None
        else settings.openai_max_input_tokens
    )
    effort = settings.openai_reasoning_effort or "medium"
    trimmed = _messages_token_budget(messages, max_input)

    client = _client(timeout)
    try:
        response = client.responses.create(
            model=model,
            input=trimmed,
            reasoning={"effort": effort},
            max_output_tokens=max_tokens,
        )
        return _output_text(response)
    except Exception as exc:
        _log.exception("OpenAI Responses API failed for %s: %s", model, exc)
        if on_fallback:
            on_fallback(f"OpenAI error: {exc}")
        raise


# Back-compat alias used by older imports.
nim_chat = openai_chat
