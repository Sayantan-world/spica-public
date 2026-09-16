import json
import re
from typing import Any

from backend.process_user_data.openai_client import openai_chat

_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

FACT_CHUNK_MIN = 400
FACT_CHUNK_MAX = 500
FACT_CHUNK_TARGET = 450


def try_parse_json_document(text: str) -> Any | None:
    """Return parsed JSON if the whole document is JSON; else None."""
    stripped = text.strip()
    if not stripped:
        return None
    if not (
        (stripped.startswith("{") and stripped.endswith("}"))
        or (stripped.startswith("[") and stripped.endswith("]"))
    ):
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def extract_json_payload(raw: str) -> Any:
    raw = raw.strip()
    m = _JSON_BLOCK.search(raw)
    if m:
        raw = m.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start_obj = raw.find("{")
        start_arr = raw.find("[")
        starts = [i for i in (start_obj, start_arr) if i >= 0]
        if not starts:
            raise
        start = min(starts)
        end_obj = raw.rfind("}")
        end_arr = raw.rfind("]")
        end = max(end_obj, end_arr)
        if end <= start:
            raise
        return json.loads(raw[start : end + 1])


def sliding_windows(text: str, window: int = 1400, overlap: int = 350) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= window:
        return [text]
    step = max(1, window - overlap)
    out: list[str] = []
    i = 0
    while i < len(text):
        chunk = text[i : i + window]
        if chunk.strip():
            out.append(chunk.strip())
        if i + window >= len(text):
            break
        i += step
    return out


def _tail_context(text: str, max_chars: int = 350) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    cut = text[-max_chars:]
    # Prefer starting at a sentence boundary inside the tail.
    parts = _SENT_SPLIT.split(cut)
    if len(parts) > 1:
        return " ".join(parts[1:]).strip() or cut
    return cut


def _fallback_size_chunks(text: str) -> list[dict]:
    """Sentence-aware hard split into ~450-char fact chunks."""
    sentences = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    if not sentences:
        raw = text.strip()
        return (
            [{"text": raw[:FACT_CHUNK_MAX], "bucket": "facts"}]
            if raw
            else []
        )
    out: list[dict] = []
    buf = ""
    for sent in sentences:
        candidate = f"{buf} {sent}".strip() if buf else sent
        if len(candidate) <= FACT_CHUNK_MAX:
            buf = candidate
            continue
        if buf:
            out.append({"text": buf[:FACT_CHUNK_MAX], "bucket": "facts"})
        if len(sent) <= FACT_CHUNK_MAX:
            buf = sent
        else:
            for i in range(0, len(sent), FACT_CHUNK_TARGET):
                piece = sent[i : i + FACT_CHUNK_TARGET].strip()
                if piece:
                    out.append({"text": piece[:FACT_CHUNK_MAX], "bucket": "facts"})
            buf = ""
    if buf:
        out.append({"text": buf[:FACT_CHUNK_MAX], "bucket": "facts"})
    return out


_SYSTEM = (
    "You extract durable personal memory for an AAC user profile. "
    "Reply with ONLY valid JSON. No markdown, no commentary."
)


def _relations_and_chunks_prompt(source_label: str, body: str) -> list[dict]:
    return [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                f"Source type: {source_label}\n\n"
                "From the text below, produce JSON with this shape:\n"
                "{\n"
                '  "relations": [\n'
                '    {"subject": "...", "relation": "...", "object": "...", "note": "..."}\n'
                "  ],\n"
                '  "chunks": [\n'
                '    {"text": "self-contained memory sentence(s)", "bucket": "family|medical|hobbies|daily_routine|social|work|other"}\n'
                "  ],\n"
                '  "profile_facts": {"key": "value"}\n'
                "}\n\n"
                "Rules:\n"
                "- relations: important people, conditions, preferences, places, routines.\n"
                "- chunks: 3-12 concise, self-contained memories useful for later retrieval.\n"
                "- Do not invent facts not supported by the text.\n"
                "- Keep each chunk under 400 characters.\n\n"
                f"TEXT:\n{body}"
            ),
        },
    ]


def _raw_fact_chunk_prompt(
    *,
    window_text: str,
    prior_context: str,
    window_idx: int,
    window_total: int,
) -> list[dict]:
    return [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                "You are chunking a raw personal text dump into durable FACT chunks "
                "for a future chatbot that speaks as this person.\n\n"
                f"Window {window_idx}/{window_total}.\n"
                "Use PRIOR CONTEXT only to resolve pronouns / continuity; do not repeat it "
                "unless needed to make a chunk self-contained.\n\n"
                "Return ONLY JSON:\n"
                "{\n"
                '  "facts": [\n'
                '    {"text": "400-500 character self-contained fact paragraph"}\n'
                "  ],\n"
                '  "relations": [\n'
                '    {"subject":"...","relation":"...","object":"...","note":"..."}\n'
                "  ],\n"
                '  "profile_facts": {"key": "value"}\n'
                "}\n\n"
                "Rules for facts:\n"
                f"- Each fact text MUST be about {FACT_CHUNK_MIN}-{FACT_CHUNK_MAX} characters "
                f"(target ~{FACT_CHUNK_TARGET}).\n"
                "- Each fact must stand alone without needing surrounding windows.\n"
                "- Prefer coherent topical paragraphs over tiny snippets.\n"
                "- Do not invent facts. Keep the person's voice when possible.\n"
                "- Cover the important content of CURRENT WINDOW; avoid near-duplicates.\n\n"
                f"PRIOR CONTEXT:\n{prior_context or '(none)'}\n\n"
                f"CURRENT WINDOW:\n{window_text}"
            ),
        },
    ]


def _normalize_extract(data: dict) -> dict:
    relations = data.get("relations") or []
    chunks = data.get("chunks") or data.get("facts") or []
    facts = data.get("profile_facts") or {}
    if not isinstance(relations, list):
        relations = []
    if not isinstance(chunks, list):
        chunks = []
    if not isinstance(facts, dict):
        facts = {}

    clean_chunks: list[dict] = []
    for c in chunks:
        if isinstance(c, str) and c.strip():
            text = c.strip()[:FACT_CHUNK_MAX]
            clean_chunks.append({"text": text, "bucket": "facts"})
        elif isinstance(c, dict) and str(c.get("text", "")).strip():
            text = str(c["text"]).strip()[:FACT_CHUNK_MAX]
            bucket = str(c.get("bucket") or "facts")[:40]
            clean_chunks.append({"text": text, "bucket": bucket})

    clean_relations: list[dict] = []
    for r in relations:
        if not isinstance(r, dict):
            continue
        subj = str(r.get("subject") or "").strip()
        rel = str(r.get("relation") or "").strip()
        obj = str(r.get("object") or "").strip()
        if not (subj or rel or obj):
            continue
        clean_relations.append(
            {
                "subject": subj[:120],
                "relation": rel[:120],
                "object": obj[:200],
                "note": str(r.get("note") or "")[:300],
            }
        )
    return {
        "relations": clean_relations,
        "chunks": clean_chunks,
        "profile_facts": {str(k)[:80]: str(v)[:400] for k, v in facts.items()},
        "facts": [
            {"text": c["text"], "char_count": len(c["text"])}
            for c in clean_chunks
            if c.get("text")
        ],
    }


def llm_extract_from_text(text: str, *, source_label: str, on_progress=None) -> dict:
    def on_fallback(msg: str) -> None:
        if on_progress:
            on_progress(None, msg)

    raw = openai_chat(
        _relations_and_chunks_prompt(source_label, text),
        max_tokens=2048,
        on_fallback=on_fallback,
    )
    try:
        data = extract_json_payload(raw)
    except Exception:
        return {"relations": [], "chunks": [], "profile_facts": {}, "facts": []}
    if not isinstance(data, dict):
        return {"relations": [], "chunks": [], "profile_facts": {}, "facts": []}
    return _normalize_extract(data)


def llm_raw_window_to_facts(
    window_text: str,
    *,
    prior_context: str,
    window_idx: int,
    window_total: int,
    on_progress=None,
) -> dict:
    def on_fallback(msg: str) -> None:
        if on_progress:
            on_progress(None, msg)

    raw = openai_chat(
        _raw_fact_chunk_prompt(
            window_text=window_text,
            prior_context=prior_context,
            window_idx=window_idx,
            window_total=window_total,
        ),
        max_tokens=2048,
        on_fallback=on_fallback,
    )
    try:
        data = extract_json_payload(raw)
    except Exception:
        fallback = _fallback_size_chunks(window_text)
        return {
            "relations": [],
            "chunks": fallback,
            "profile_facts": {},
            "facts": [{"text": c["text"], "char_count": len(c["text"])} for c in fallback],
        }
    if not isinstance(data, dict):
        fallback = _fallback_size_chunks(window_text)
        return {
            "relations": [],
            "chunks": fallback,
            "profile_facts": {},
            "facts": [{"text": c["text"], "char_count": len(c["text"])} for c in fallback],
        }
    # Prefer explicit "facts" list for raw dumps.
    if isinstance(data.get("facts"), list) and data["facts"]:
        data = {**data, "chunks": data["facts"]}
    normalized = _normalize_extract(data)
    # Enforce bucket=facts for raw dumps.
    for c in normalized["chunks"]:
        c["bucket"] = "facts"
    if not normalized["chunks"]:
        fallback = _fallback_size_chunks(window_text)
        normalized["chunks"] = fallback
        normalized["facts"] = [
            {"text": c["text"], "char_count": len(c["text"])} for c in fallback
        ]
    return normalized


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _join_list(value: Any) -> str:
    parts = [str(x).strip() for x in _as_list(value) if str(x).strip()]
    return ", ".join(parts)


def _flatten_json_leaves(obj: Any, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.update(_flatten_json_leaves(v, key))
    elif isinstance(obj, list):
        joined = _join_list(obj)
        if joined:
            out[prefix or "items"] = joined[:400]
    else:
        text = str(obj).strip()
        if text and prefix:
            out[prefix] = text[:400]
    return out


def structured_json_extract(parsed: Any) -> dict:
    """Deterministic memory from AAC-style profile JSON (no LLM required)."""
    if not isinstance(parsed, dict):
        body = json.dumps(parsed, ensure_ascii=False)
        chunks = _fallback_size_chunks(body)
        return {
            "relations": [],
            "chunks": chunks,
            "profile_facts": {},
            "facts": [{"text": c["text"], "char_count": len(c["text"])} for c in chunks],
        }

    name = str(parsed.get("name") or "").strip() or "This person"
    profile_facts: dict[str, str] = {}
    relations: list[dict] = []
    paragraphs: list[str] = []

    def put_fact(key: str, value: Any) -> None:
        if value is None or value == "":
            return
        if isinstance(value, (list, dict)):
            return
        profile_facts[key[:80]] = str(value)[:400]

    put_fact("name", parsed.get("name"))
    put_fact("age", parsed.get("age"))
    put_fact("gender", parsed.get("gender"))
    put_fact("pronouns", parsed.get("pronouns"))
    put_fact("severity", parsed.get("severity"))
    put_fact("disability_type", parsed.get("disability_type"))
    put_fact("communication_mode", parsed.get("communication_mode"))

    prefs = parsed.get("preferences") if isinstance(parsed.get("preferences"), dict) else {}
    bg = (
        parsed.get("personal_background")
        if isinstance(parsed.get("personal_background"), dict)
        else {}
    )
    access = parsed.get("access_needs") if isinstance(parsed.get("access_needs"), dict) else {}
    barriers = (
        parsed.get("communication_barriers")
        if isinstance(parsed.get("communication_barriers"), dict)
        else {}
    )
    dynamic = parsed.get("dynamic_traits") if isinstance(parsed.get("dynamic_traits"), dict) else {}

    for key, value in {
        **{f"preference_{k}": v for k, v in prefs.items() if not isinstance(v, (list, dict))},
        **{f"background_{k}": v for k, v in bg.items() if not isinstance(v, (list, dict))},
        **{f"access_{k}": v for k, v in access.items() if not isinstance(v, (list, dict))},
        **{f"barrier_{k}": v for k, v in barriers.items() if not isinstance(v, (list, dict))},
        **{f"dynamic_{k}": v for k, v in dynamic.items() if not isinstance(v, (list, dict))},
    }.items():
        put_fact(key, value)

    for key, value in {
        "topics_to_avoid": prefs.get("topics_to_avoid"),
        "hobbies": bg.get("hobbies"),
        "sensitive_topics": barriers.get("sensitive_topics"),
    }.items():
        joined = _join_list(value)
        if joined:
            profile_facts[key] = joined[:400]

    # Identity / medical
    identity_bits = [
        f"{name} is a {parsed.get('age')}-year-old {parsed.get('gender') or 'person'}."
        if parsed.get("age")
        else f"{name} uses AAC.",
    ]
    if parsed.get("disability_type"):
        identity_bits.append(
            f"Primary condition: {parsed.get('disability_type')}"
            + (f" ({parsed.get('severity')} severity)." if parsed.get("severity") else ".")
        )
    if parsed.get("communication_mode"):
        identity_bits.append(f"Communication mode: {parsed.get('communication_mode')}.")
    if parsed.get("pronouns"):
        identity_bits.append(f"Pronouns: {parsed.get('pronouns')}.")
    paragraphs.append(" ".join(identity_bits))

    if bg:
        bg_bits = []
        if bg.get("education"):
            bg_bits.append(f"Education: {bg['education']}.")
        if bg.get("work"):
            bg_bits.append(f"Work: {bg['work']}.")
        if bg.get("location"):
            bg_bits.append(f"Lives in {bg['location']}.")
        if bg.get("family"):
            bg_bits.append(f"Family: {bg['family']}.")
            relations.append(
                {
                    "subject": name,
                    "relation": "family",
                    "object": str(bg["family"])[:200],
                    "note": "",
                }
            )
        hobbies = _join_list(bg.get("hobbies"))
        if hobbies:
            bg_bits.append(f"Hobbies include {hobbies}.")
        if bg_bits:
            paragraphs.append(f"Background for {name}. " + " ".join(bg_bits))

    if prefs:
        pref_bits = []
        for label, key in [
            ("style", "style"),
            ("tone", "tone"),
            ("perspective", "perspective"),
            ("humor", "humor"),
            ("response length", "response_length"),
        ]:
            if prefs.get(key):
                pref_bits.append(f"{label}: {prefs[key]}")
        avoid = _join_list(prefs.get("topics_to_avoid"))
        if avoid:
            pref_bits.append(f"topics to avoid: {avoid}")
        if pref_bits:
            paragraphs.append(
                f"Communication preferences for {name}: " + "; ".join(pref_bits) + "."
            )

    if access:
        access_bits = [
            f"{k.replace('_', ' ')}: {v}"
            for k, v in access.items()
            if v is not None and not isinstance(v, (list, dict))
        ]
        if access_bits:
            paragraphs.append(f"Access needs for {name}: " + "; ".join(access_bits) + ".")

    if barriers:
        barrier_bits = []
        for k, v in barriers.items():
            if isinstance(v, list):
                joined = _join_list(v)
                if joined:
                    barrier_bits.append(f"{k.replace('_', ' ')}: {joined}")
            elif v is not None and not isinstance(v, dict):
                barrier_bits.append(f"{k.replace('_', ' ')}: {v}")
        if barrier_bits:
            paragraphs.append(
                f"Communication barriers for {name}: " + "; ".join(barrier_bits) + "."
            )

    if dynamic:
        dyn_bits = [
            f"{k.replace('_', ' ')}: {v}"
            for k, v in dynamic.items()
            if v is not None and not isinstance(v, (list, dict))
        ]
        if dyn_bits:
            paragraphs.append(f"Dynamic traits for {name}: " + "; ".join(dyn_bits) + ".")

    if parsed.get("disability_type"):
        relations.append(
            {
                "subject": name,
                "relation": "has_condition",
                "object": str(parsed["disability_type"])[:200],
                "note": str(parsed.get("severity") or "")[:300],
            }
        )
    if parsed.get("communication_mode"):
        relations.append(
            {
                "subject": name,
                "relation": "communicates_via",
                "object": str(parsed["communication_mode"])[:200],
                "note": "",
            }
        )

    # Catch remaining nested scalars not already covered.
    for key, value in _flatten_json_leaves(parsed).items():
        if key not in profile_facts and key.split(".")[0] not in {
            "id",
            "preferences",
            "personal_background",
            "access_needs",
            "communication_barriers",
            "dynamic_traits",
        }:
            profile_facts.setdefault(key[:80], value)

    # Pack paragraphs into ~400–500 char fact chunks.
    chunks: list[dict] = []
    buf = ""
    for para in paragraphs:
        para = " ".join(para.split()).strip()
        if not para:
            continue
        candidate = f"{buf} {para}".strip() if buf else para
        if len(candidate) <= FACT_CHUNK_MAX:
            buf = candidate
            continue
        if buf:
            chunks.append({"text": buf[:FACT_CHUNK_MAX], "bucket": "facts"})
        if len(para) <= FACT_CHUNK_MAX:
            buf = para
        else:
            chunks.extend(_fallback_size_chunks(para))
            buf = ""
    if buf:
        chunks.append({"text": buf[:FACT_CHUNK_MAX], "bucket": "facts"})
    if not chunks:
        narrative = " ".join(paragraphs).strip() or json.dumps(parsed, ensure_ascii=False)
        chunks = _fallback_size_chunks(narrative)

    for c in chunks:
        c["bucket"] = "facts"

    return {
        "relations": relations,
        "chunks": chunks,
        "profile_facts": profile_facts,
        "facts": [{"text": c["text"], "char_count": len(c["text"])} for c in chunks],
    }


def _merge_extracts(primary: dict, secondary: dict) -> dict:
    seen_chunk: set[str] = set()
    chunks: list[dict] = []
    for c in list(primary.get("chunks") or []) + list(secondary.get("chunks") or []):
        text = str(c.get("text") or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen_chunk:
            continue
        seen_chunk.add(key)
        chunks.append(
            {
                "text": text[:FACT_CHUNK_MAX],
                "bucket": str(c.get("bucket") or "facts")[:40],
            }
        )
    seen_rel: set[str] = set()
    relations: list[dict] = []
    for r in list(primary.get("relations") or []) + list(secondary.get("relations") or []):
        if not isinstance(r, dict):
            continue
        key = f"{r.get('subject','')}|{r.get('relation','')}|{r.get('object','')}".lower()
        if key in seen_rel or not key.strip("|"):
            continue
        seen_rel.add(key)
        relations.append(r)
    profile_facts = dict(primary.get("profile_facts") or {})
    for k, v in (secondary.get("profile_facts") or {}).items():
        profile_facts.setdefault(k, v)
    return {
        "relations": relations,
        "chunks": chunks,
        "profile_facts": profile_facts,
        "facts": [{"text": c["text"], "char_count": len(c["text"])} for c in chunks],
    }


def process_json_document(parsed: Any, on_progress=None) -> dict:
    """Structured AAC JSON → facts without a slow LLM round-trip."""
    if on_progress:
        on_progress(20, "Parsing structured JSON profile…")
    result = structured_json_extract(parsed)
    if on_progress:
        on_progress(
            55,
            f"JSON ready: {len(result['chunks'])} fact chunks, {len(result['relations'])} relations",
        )
    return result


def process_raw_text(text: str, on_progress=None) -> dict:
    """Context-enhanced raw dump → 400–500 char fact chunks via OpenAI Luna."""
    # Keep windows large so a typical ≤10k-char upload is 1–2 Luna calls
    # (input is capped at openai_max_input_tokens inside the client).
    windows = sliding_windows(text, window=9000, overlap=400)
    all_relations: list[dict] = []
    all_chunks: list[dict] = []
    profile_facts: dict[str, str] = {}
    seen_chunk: set[str] = set()
    seen_rel: set[str] = set()
    prior = ""
    n = max(len(windows), 1)

    for i, window in enumerate(windows):
        if on_progress:
            pct = 15 + int(45 * (i / n))
            on_progress(
                pct,
                f"Chunking raw text with Luna ({i + 1}/{len(windows)})…",
            )
        part = llm_raw_window_to_facts(
            window,
            prior_context=prior,
            window_idx=i + 1,
            window_total=len(windows),
            on_progress=on_progress,
        )
        for r in part["relations"]:
            key = f"{r['subject']}|{r['relation']}|{r['object']}".lower()
            if key in seen_rel:
                continue
            seen_rel.add(key)
            all_relations.append(r)
        for c in part["chunks"]:
            text_c = (c.get("text") or "").strip()
            if not text_c:
                continue
            if len(text_c) > FACT_CHUNK_MAX:
                text_c = text_c[:FACT_CHUNK_MAX].rsplit(" ", 1)[0] or text_c[:FACT_CHUNK_MAX]
            key = text_c.lower()
            if key in seen_chunk:
                continue
            seen_chunk.add(key)
            all_chunks.append({"text": text_c, "bucket": "facts"})
        for k, v in part["profile_facts"].items():
            profile_facts.setdefault(k, v)
        prior = _tail_context(window)

    if not all_chunks:
        all_chunks = _fallback_size_chunks(text)

    if on_progress:
        on_progress(60, f"Prepared {len(all_chunks)} fact chunks")

    return {
        "relations": all_relations,
        "chunks": all_chunks,
        "profile_facts": profile_facts,
        "facts": [
            {"text": c["text"], "char_count": len(c["text"])} for c in all_chunks
        ],
    }
