"""Account AAC chat: Luna generation + RAG over facts/memory + session turns."""

import json
import logging
import math
import uuid
from datetime import UTC, datetime
from typing import Any

from pgvector import Vector
from psycopg.types.json import Jsonb

from backend.config.settings import settings
from backend.process_user_data.db import flatten_facts, get_pool, merge_fact_list, merge_facts
from backend.process_user_data.embeddings import embed_documents, embed_query
from backend.process_user_data.openai_client import openai_chat
from backend.process_user_data.processor import extract_json_payload

_log = logging.getLogger(__name__)


def _session_limits() -> tuple[int, int]:
    return (
        int(settings.max_chat_sessions_per_user),
        int(settings.max_chat_turns_per_session),
    )


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return -1.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def load_account_row(user_id: str) -> dict:
    with get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT id, first_name, last_name, dob, relations, profile_facts, facts,
                   profile_summary
            FROM accounts WHERE id = %s
            """,
            (user_id,),
        ).fetchone()
    if not row:
        raise ValueError("account not found")
    return dict(row)


def build_profile_summary(user_id: str, *, force: bool = False) -> str:
    row = load_account_row(user_id)
    cached = (row.get("profile_summary") or "").strip()
    if cached and not force:
        return cached

    name = f"{row['first_name']} {row['last_name']}".strip()
    relations = row.get("relations") or []
    if isinstance(relations, str):
        relations = json.loads(relations)
    profile_facts = row.get("profile_facts") or {}
    if isinstance(profile_facts, str):
        profile_facts = json.loads(profile_facts)
    flat = flatten_facts(profile_facts if isinstance(profile_facts, dict) else {})
    facts = row.get("facts") or []
    if isinstance(facts, str):
        facts = json.loads(facts)

    rel_lines = []
    for r in relations[:20]:
        if not isinstance(r, dict):
            continue
        rel_lines.append(
            " — ".join(
                str(x)
                for x in (r.get("subject"), r.get("relation"), r.get("object"))
                if x
            )
        )
    fact_lines = [
        str(f.get("text") if isinstance(f, dict) else f).strip()
        for f in facts[:12]
        if (f.get("text") if isinstance(f, dict) else f)
    ]
    pf_lines = [f"{k}: {v}" for k, v in list(flat.items())[:30]]

    source = (
        f"Name: {name}\n"
        f"Profile facts:\n" + ("\n".join(pf_lines) or "(none)") + "\n"
        f"Relations:\n" + ("\n".join(rel_lines) or "(none)") + "\n"
        f"Sample facts:\n" + ("\n".join(fact_lines) or "(none)")
    )
    try:
        summary = openai_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Summarize this AAC user's durable identity for chat context. "
                        "Write 8-14 tight sentences in third person. No markdown."
                    ),
                },
                {"role": "user", "content": source},
            ],
            max_tokens=600,
            max_input_tokens=4096,
        ).strip()
    except Exception:
        _log.exception("profile summary LLM failed; using flat fallback")
        summary = source[:2500]

    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE accounts SET profile_summary = %s WHERE id = %s",
            (summary, user_id),
        )
    return summary


def retrieve_memory_chunks(user_id: str, query: str, *, k: int = 2) -> list[dict]:
    q = embed_query(query)
    with get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT id, chunk_text, bucket, source_kind,
                   1 - (embedding <=> %s::vector) AS score
            FROM account_memory_chunks
            WHERE user_id = %s
              AND embedding IS NOT NULL
              AND lower(bucket) <> 'facts'
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (Vector(q), user_id, Vector(q), k),
        ).fetchall()
        if len(rows) < k:
            # Fall back to any chunks if non-fact memories are sparse.
            rows = conn.execute(
                """
                SELECT id, chunk_text, bucket, source_kind,
                       1 - (embedding <=> %s::vector) AS score
                FROM account_memory_chunks
                WHERE user_id = %s AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (Vector(q), user_id, Vector(q), k),
            ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": str(r["id"]),
                "text": r["chunk_text"],
                "bucket": r.get("bucket") or "other",
                "source": "memory",
                "score": float(r["score"] or 0),
            }
        )
    return out


def retrieve_fact_chunks(user_id: str, query: str, *, k: int = 2) -> list[dict]:
    qvec = embed_query(query)
    # Prefer vector search over fact-bucketed memory chunks.
    with get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT id, chunk_text, bucket, source_kind,
                   1 - (embedding <=> %s::vector) AS score
            FROM account_memory_chunks
            WHERE user_id = %s
              AND embedding IS NOT NULL
              AND lower(bucket) = 'facts'
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (Vector(qvec), user_id, Vector(qvec), k),
        ).fetchall()
    if rows:
        return [
            {
                "id": str(r["id"]),
                "text": r["chunk_text"],
                "bucket": "facts",
                "source": "facts",
                "score": float(r["score"] or 0),
            }
            for r in rows
        ]

    # Fallback: rank accounts.facts texts in-process.
    row = load_account_row(user_id)
    facts = row.get("facts") or []
    if isinstance(facts, str):
        facts = json.loads(facts)
    texts: list[tuple[str, str]] = []
    for i, f in enumerate(facts):
        text = str(f.get("text") if isinstance(f, dict) else f).strip()
        if text:
            texts.append((f"fact-{i}", text))
    if not texts:
        return []
    vecs = embed_documents([t for _, t in texts])
    ranked = []
    for (fid, text), vec in zip(texts, vecs):
        ranked.append(( _cosine(qvec, vec), fid, text))
    ranked.sort(reverse=True)
    return [
        {
            "id": fid,
            "text": text,
            "bucket": "facts",
            "source": "facts",
            "score": score,
        }
        for score, fid, text in ranked[:k]
    ]


def list_sessions(user_id: str) -> list[dict]:
    max_sessions, max_turns = _session_limits()
    with get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, turn_count, profile_summary, created_at, updated_at
            FROM account_chat_sessions
            WHERE user_id = %s
            ORDER BY updated_at DESC
            """,
            (user_id,),
        ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": str(r["id"]),
                "title": r["title"],
                "turn_count": int(r["turn_count"] or 0),
                "max_turns": max_turns,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
        )
    return out


def create_session(user_id: str, *, title: str | None = None) -> dict:
    max_sessions, max_turns = _session_limits()
    with get_pool().connection() as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM account_chat_sessions WHERE user_id = %s",
            (user_id,),
        ).fetchone()["n"]
    if int(n) >= max_sessions:
        raise ValueError(
            f"session limit reached ({max_sessions}). Delete an older conversation first."
        )

    summary = build_profile_summary(user_id, force=False)
    session_id = uuid.uuid4()
    label = (title or "Conversation").strip()[:80] or "Conversation"
    with get_pool().connection() as conn:
        row = conn.execute(
            """
            INSERT INTO account_chat_sessions (id, user_id, title, profile_summary)
            VALUES (%s, %s, %s, %s)
            RETURNING id, title, turn_count, created_at, updated_at
            """,
            (session_id, user_id, label, summary),
        ).fetchone()
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "turn_count": int(row["turn_count"] or 0),
        "max_turns": max_turns,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        "profile_summary": summary,
    }


def delete_session(user_id: str, session_id: str) -> None:
    with get_pool().connection() as conn:
        cur = conn.execute(
            "DELETE FROM account_chat_sessions WHERE id = %s AND user_id = %s",
            (session_id, user_id),
        )
        if cur.rowcount == 0:
            raise ValueError("session not found")


def get_session(user_id: str, session_id: str) -> dict:
    max_sessions, max_turns = _session_limits()
    del max_sessions
    with get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT id, title, turn_count, profile_summary, pending, aside_messages,
                   created_at, updated_at
            FROM account_chat_sessions
            WHERE id = %s AND user_id = %s
            """,
            (session_id, user_id),
        ).fetchone()
        if not row:
            raise ValueError("session not found")
        turns = conn.execute(
            """
            SELECT id, turn_index, partner_text, aac_text, retrieved, created_at
            FROM account_chat_turns
            WHERE session_id = %s
            ORDER BY turn_index ASC
            """,
            (session_id,),
        ).fetchall()

    asides = row.get("aside_messages") or []
    if isinstance(asides, str):
        try:
            asides = json.loads(asides)
        except json.JSONDecodeError:
            asides = []
    if not isinstance(asides, list):
        asides = []

    events: list[tuple] = []
    for t in turns:
        ts = t["created_at"]
        events.append(
            (
                ts,
                0,
                {
                    "role": "partner",
                    "text": t["partner_text"],
                    "turn_index": t["turn_index"],
                },
            )
        )
        events.append(
            (
                ts,
                1,
                {
                    "role": "aac_user",
                    "text": t["aac_text"],
                    "turn_index": t["turn_index"],
                },
            )
        )
    for a in asides:
        if not isinstance(a, dict):
            continue
        text = str(a.get("text") or "").strip()
        if not text:
            continue
        raw_ts = a.get("created_at")
        try:
            if isinstance(raw_ts, str):
                ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            else:
                ts = raw_ts
        except Exception:
            ts = None
        if ts is None:
            ts = datetime.now(UTC)
        events.append(
            (
                ts,
                2,
                {
                    "role": "aac_user",
                    "text": text,
                    "kind": "quick",
                    "id": a.get("id"),
                },
            )
        )
    events.sort(key=lambda e: (e[0] or datetime.min.replace(tzinfo=UTC), e[1]))
    messages = [e[2] for e in events]

    pending = row.get("pending")
    if isinstance(pending, str):
        try:
            pending = json.loads(pending)
        except json.JSONDecodeError:
            pending = None
    if pending is not None and not isinstance(pending, dict):
        pending = None
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "turn_count": int(row["turn_count"] or 0),
        "max_turns": max_turns,
        "profile_summary": row.get("profile_summary") or "",
        "pending": pending,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        "messages": messages,
        "turns": [
            {
                "id": str(t["id"]),
                "turn_index": t["turn_index"],
                "partner_text": t["partner_text"],
                "aac_text": t["aac_text"],
                "retrieved": t["retrieved"] if isinstance(t["retrieved"], dict) else {},
            }
            for t in turns
        ],
    }


def append_quick_phrase(user_id: str, session_id: str, text: str) -> dict:
    """Persist a picture-board phrase into session dialogue history."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty phrase")
    text = text[:400]
    entry = {
        "id": str(uuid.uuid4()),
        "text": text,
        "kind": "quick",
        "created_at": datetime.now(UTC).isoformat(),
    }
    with get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT aside_messages
            FROM account_chat_sessions
            WHERE id = %s AND user_id = %s
            """,
            (session_id, user_id),
        ).fetchone()
        if not row:
            raise ValueError("session not found")
        asides = row.get("aside_messages") or []
        if isinstance(asides, str):
            try:
                asides = json.loads(asides)
            except json.JSONDecodeError:
                asides = []
        if not isinstance(asides, list):
            asides = []
        asides = [*asides, entry]
        conn.execute(
            """
            UPDATE account_chat_sessions
            SET aside_messages = %s, updated_at = now()
            WHERE id = %s AND user_id = %s
            """,
            (Jsonb(asides), session_id, user_id),
        )
    return {"role": "aac_user", "text": text, "kind": "quick", "id": entry["id"]}


def _history_for_prompt(
    turns: list[dict],
    *,
    messages: list[dict] | None = None,
    max_turns: int = 8,
    exclude_quick_texts: set[str] | None = None,
) -> str:
    skip_quick = {t.strip().lower() for t in (exclude_quick_texts or set()) if t.strip()}
    if messages:
        # Last ~2*max_turns lines of mixed partner / AAC / quick phrases.
        recent = messages[-(max_turns * 2) :]
        lines = []
        for m in recent:
            role = m.get("role")
            text = str(m.get("text") or "").strip()
            if not text:
                continue
            # Live picture-board input for this turn is injected separately
            # after the partner message; skip it here so it is not misread
            # as a prior utterance before the partner spoke.
            if (
                m.get("kind") == "quick"
                and text.lower() in skip_quick
            ):
                continue
            if role == "partner":
                lines.append(f"Partner: {text}")
            else:
                lines.append(f"AAC user: {text}")
        return "\n".join(lines) if lines else "(no prior turns)"

    recent = turns[-max_turns:]
    lines = []
    for t in recent:
        lines.append(f"Partner: {t['partner_text']}")
        lines.append(f"AAC user: {t['aac_text']}")
    return "\n".join(lines) if lines else "(no prior turns)"


def _persist_new_details(
    user_id: str,
    *,
    partner_text: str,
    aac_text: str,
) -> dict[str, Any]:
    """Extract durable new details and write into facts + memory."""
    try:
        raw = openai_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Extract NEW durable personal details about the AAC user from this turn. "
                        "Reply ONLY with JSON: "
                        '{"new_facts":[{"text":"..."}],"profile_facts":{"key":"value"},'
                        '"skip":true|false}. '
                        "If nothing new, set skip=true and empty arrays/objects."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Partner said:\n{partner_text}\n\n"
                        f"AAC user replied:\n{aac_text}"
                    ),
                },
            ],
            max_tokens=800,
            max_input_tokens=4096,
        )
        data = extract_json_payload(raw)
    except Exception:
        _log.exception("new-detail extraction failed")
        return {"updated": False}

    if not isinstance(data, dict) or data.get("skip"):
        return {"updated": False}

    incoming_facts = data.get("new_facts") or []
    incoming_pf = data.get("profile_facts") or {}
    if not isinstance(incoming_facts, list):
        incoming_facts = []
    if not isinstance(incoming_pf, dict):
        incoming_pf = {}

    clean_facts = []
    for item in incoming_facts:
        if isinstance(item, str) and item.strip():
            clean_facts.append({"text": item.strip()[:500]})
        elif isinstance(item, dict) and str(item.get("text") or "").strip():
            clean_facts.append({"text": str(item["text"]).strip()[:500]})

    if not clean_facts and not incoming_pf:
        return {"updated": False}

    with get_pool().connection() as conn:
        acct = conn.execute(
            "SELECT facts, profile_facts FROM accounts WHERE id = %s",
            (user_id,),
        ).fetchone()
    existing_facts = acct["facts"] or []
    existing_pf = acct["profile_facts"] or {}
    if isinstance(existing_facts, str):
        existing_facts = json.loads(existing_facts)
    if isinstance(existing_pf, str):
        existing_pf = json.loads(existing_pf)

    merged_facts = merge_fact_list(
        existing_facts if isinstance(existing_facts, list) else [],
        clean_facts,
        upload_id=None,
    )
    merged_pf = merge_facts(
        existing_pf if isinstance(existing_pf, dict) else {},
        {str(k)[:80]: str(v)[:400] for k, v in incoming_pf.items()},
        upload_id=None,
    )

    texts = [f["text"] for f in clean_facts]
    vectors = embed_documents(texts) if texts else []
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE accounts SET facts = %s, profile_facts = %s WHERE id = %s",
            (Jsonb(merged_facts), Jsonb(merged_pf), user_id),
        )
        for i, fact in enumerate(clean_facts):
            emb = vectors[i] if i < len(vectors) else None
            conn.execute(
                """
                INSERT INTO account_memory_chunks (
                    id, user_id, upload_id, chunk_text, bucket, source_kind, embedding
                )
                VALUES (%s, %s, NULL, %s, 'facts', 'chat_update', %s)
                """,
                (
                    uuid.uuid4(),
                    user_id,
                    fact["text"],
                    Vector(emb) if emb is not None else None,
                ),
            )

    try:
        build_profile_summary(user_id, force=True)
    except Exception:
        _log.exception("profile summary refresh failed")
    return {"updated": True, "facts_added": len(clean_facts)}


CANDIDATE_SPECS = [
    {
        "id": "persona_a",
        "strategy": "persona",
        "label": "Persona · grounded",
        "brief": (
            "Persona-grounded reply #1: answer using profile/facts/memories; "
            "personal voice and concrete detail from the retrieved context."
        ),
    },
    {
        "id": "persona_b",
        "strategy": "persona",
        "label": "Persona · alternate",
        "brief": (
            "Persona-grounded reply #2: different angle or emphasis from #1, "
            "still first-person and grounded in the same profile/facts/memories."
        ),
    },
    {
        "id": "chitchat",
        "strategy": "chitchat",
        "label": "Chit-chat",
        "brief": (
            "Light generic social reply: warm, brief chit-chat that keeps the "
            "conversation going without relying on deep personal history."
        ),
    },
    {
        "id": "turnaround",
        "strategy": "turnaround",
        "label": "Turnaround · clarify",
        "brief": (
            "Turnaround: steer the conversation or ask a clarifying question about "
            "what the partner meant; invite them to rephrase or choose a direction."
        ),
    },
]


def _normalize_candidates(raw: Any) -> list[dict]:
    items: list = []
    if isinstance(raw, dict):
        items = raw.get("candidates") or raw.get("replies") or []
    elif isinstance(raw, list):
        items = raw
    by_id: dict[str, str] = {}
    ordered: list[dict] = []
    for item in items:
        if isinstance(item, str) and item.strip():
            ordered.append({"text": item.strip()})
            continue
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        cid = str(item.get("id") or item.get("strategy") or "").strip().lower()
        if cid:
            by_id[cid] = text
        ordered.append({"id": cid, "text": text})

    out: list[dict] = []
    for spec in CANDIDATE_SPECS:
        text = by_id.get(spec["id"]) or by_id.get(spec["strategy"])
        if not text and ordered:
            text = ordered.pop(0)["text"]
        if not text:
            continue
        out.append(
            {
                "id": spec["id"],
                "strategy": spec["strategy"],
                "label": spec["label"],
                "text": text[:1200],
            }
        )
    # Pad if model returned fewer than 4.
    while len(out) < 4 and ordered:
        spec = CANDIDATE_SPECS[len(out)]
        out.append(
            {
                "id": spec["id"],
                "strategy": spec["strategy"],
                "label": spec["label"],
                "text": ordered.pop(0)["text"][:1200],
            }
        )
    return out[:4]


def _fallback_candidates(display_name: str, partner_text: str) -> list[dict]:
    short = partner_text[:120].rstrip(".")
    texts = [
        f"Thanks for asking. From my side, I'd like to answer carefully about that.",
        f"That's important to me. Let me share how I see it, given who I am.",
        f"Nice to talk with you. I'm doing alright — how about you?",
        f"Just to make sure I understand — when you say \"{short}\", what would you like me to focus on?",
    ]
    out = []
    for spec, text in zip(CANDIDATE_SPECS, texts):
        out.append(
            {
                "id": spec["id"],
                "strategy": spec["strategy"],
                "label": spec["label"],
                "text": text,
            }
        )
    return out


def _sensing_line(sensing: dict | None) -> str | None:
    if not sensing:
        return None
    parts: list[str] = []
    for key, label in (
        ("emotion", "emotion"),
        ("hand_gesture", "hand gesture"),
        ("head_signal", "head"),
    ):
        val = (sensing.get(key) or "").strip()
        if not val or val.lower() in {"none", "null", "unknown"}:
            continue
        # Collapse legacy dissatisfied nod into plain nod.
        if key == "head_signal" and val.upper() == "HEAD_NOD_DISSATISFIED":
            val = "HEAD_NOD"
        parts.append(f"{label}={val}")
    if not parts:
        return None
    return "; ".join(parts)


def tool_load_profile(user_id: str, session_id: str, session: dict) -> dict:
    account = load_account_row(user_id)
    display_name = f"{account['first_name']} {account['last_name']}".strip()
    profile_summary = (session.get("profile_summary") or "").strip()
    if not profile_summary:
        profile_summary = build_profile_summary(user_id)
        with get_pool().connection() as conn:
            conn.execute(
                "UPDATE account_chat_sessions SET profile_summary = %s WHERE id = %s",
                (profile_summary, session_id),
            )
    return {"display_name": display_name, "profile_summary": profile_summary}


def tool_generate_reply_options(
    *,
    display_name: str,
    profile_summary: str,
    partner_text: str,
    history: str,
    memory_hits: list[dict],
    fact_hits: list[dict],
    sensing: dict | None = None,
    live_phrases: list[str] | None = None,
) -> list[dict]:
    live_phrases = live_phrases or []
    live_board = " / ".join(live_phrases) if live_phrases else ""
    mem_block = "\n".join(f"- {h['text']}" for h in memory_hits) or "- (none)"
    fact_block = "\n".join(f"- {h['text']}" for h in fact_hits) or "- (none)"

    sensing_line = _sensing_line(sensing)
    briefs_lines: list[str] = []
    for s in CANDIDATE_SPECS:
        brief = s["brief"]
        if live_board:
            brief = (
                f"{brief} The AAC user just signaled via picture board "
                f'("{live_board}") in response to the partner\'s current message. '
                "Every candidate MUST honor that live intent (e.g. No = decline / "
                "disagree; Yes = accept / agree; Help = ask for help). Do not "
                "contradict the picture-board signal."
            )
        if sensing_line and s["id"] == "chitchat":
            brief = (
                f"{brief} Multimodal cues from the AAC user right now "
                f"({sensing_line}): weave these naturally into the chit-chat "
                "reply when relevant (e.g. nod/shake as yes/no tone, emotion "
                "as warmth or hesitation, hand gesture as emphasis). "
                "Do not list the sensor labels; just let them shape the reply."
            )
        elif sensing_line and s["id"] == "persona_b":
            brief = (
                f"{brief} Also ground this reply in live multimodal cues "
                f"({sensing_line}) captured just now. Combine persona "
                "facts/memories with those live signals. If a stored fact or "
                "memory conflicts with the live multimodal feed (e.g. profile "
                "says they like something but head shake / emotion / gesture "
                "says otherwise), prefer the live multimodal feed for this "
                "turn's stance and tone. Do not list sensor labels; let them "
                "shape a natural first-person reply."
            )
        briefs_lines.append(f"- id={s['id']}: {brief}")
    briefs = "\n".join(briefs_lines)

    sensing_block = (
        f"\nLIVE MULTIMODAL (apply to persona_b and chitchat; "
        f"persona_b: if facts clash with this feed, prefer the live feed):\n"
        f"{sensing_line}\n"
        if sensing_line
        else ""
    )
    board_block = (
        f"\nLIVE PICTURE-BOARD INPUT (AAC user just signaled this about the "
        f"partner's CURRENT message; ALL four candidates must honor this "
        f"intent and must not contradict it):\n"
        f"{live_board}\n"
        if live_board
        else ""
    )

    system = (
        f"You write reply OPTIONS for {display_name}, an AAC user (first person only). "
        "A partner is talking to them. Produce exactly 4 distinct candidate replies. "
        "Do not invent unsupported biography. When live multimodal cues are provided, "
        "persona_b must use them and prioritize them over conflicting retrieved facts. "
        "When live picture-board input is provided, EVERY candidate must respect that "
        "signal as the AAC user's intent toward the partner's current message. "
        "No markdown outside JSON."
    )
    user_prompt = (
        f"PROFILE SUMMARY:\n{profile_summary}\n\n"
        f"RETRIEVED FACTS (top 2):\n{fact_block}\n\n"
        f"RETRIEVED MEMORY (top 2):\n{mem_block}\n\n"
        f"RECENT DIALOGUE:\n{history}\n\n"
        f"Partner now says:\n{partner_text}\n"
        f"{board_block}"
        f"{sensing_block}\n"
        "Return ONLY JSON:\n"
        '{"candidates":[{"id":"persona_a","text":"..."},'
        '{"id":"persona_b","text":"..."},'
        '{"id":"chitchat","text":"..."},'
        '{"id":"turnaround","text":"..."}]}\n\n'
        f"Candidate briefs:\n{briefs}"
    )

    candidates: list[dict] = []
    try:
        raw = openai_chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1600,
            max_input_tokens=int(settings.openai_chat_max_input_tokens),
        )
        data = extract_json_payload(raw)
        candidates = _normalize_candidates(data)
    except Exception:
        _log.exception("candidate generation failed; using fallbacks")
        candidates = []

    if len(candidates) < 4:
        fallback = _fallback_candidates(display_name, partner_text)
        have = {c["id"] for c in candidates}
        for fb in fallback:
            if fb["id"] not in have:
                candidates.append(fb)
            if len(candidates) >= 4:
                break
    return candidates[:4]


def tool_store_pending(
    *,
    user_id: str,
    session_id: str,
    session: dict,
    partner_text: str,
    candidates: list[dict],
    retrieved: dict,
    sensing: dict | None,
    live_phrases: list[str],
    max_turns: int,
) -> dict:
    pending = {
        "partner_text": partner_text,
        "candidates": candidates,
        "retrieved": retrieved,
        "sensing": {
            "emotion": (sensing or {}).get("emotion"),
            "hand_gesture": (sensing or {}).get("hand_gesture"),
            "head_signal": (sensing or {}).get("head_signal"),
        }
        if sensing
        else None,
        "quick_phrases": live_phrases or None,
    }
    title_update = None
    if int(session["turn_count"]) == 0:
        title_update = partner_text[:60].strip() or "Conversation"

    with get_pool().connection() as conn:
        if title_update:
            conn.execute(
                """
                UPDATE account_chat_sessions
                SET pending = %s, updated_at = now(), title = %s
                WHERE id = %s AND user_id = %s
                """,
                (Jsonb(pending), title_update, session_id, user_id),
            )
        else:
            conn.execute(
                """
                UPDATE account_chat_sessions
                SET pending = %s, updated_at = now()
                WHERE id = %s AND user_id = %s
                """,
                (Jsonb(pending), session_id, user_id),
            )

    return {
        "session_id": session_id,
        "partner_text": partner_text,
        "candidates": candidates,
        "retrieved": retrieved,
        "turn_count": int(session["turn_count"]),
        "max_turns": max_turns,
        "awaiting_pick": True,
        "title": title_update or session.get("title"),
    }


def tool_commit_turn(
    *,
    user_id: str,
    session_id: str,
    session: dict,
    partner_text: str,
    aac_text: str,
    retrieved: dict,
    extra: dict | None = None,
    title_update: str | None = None,
) -> dict:
    turn_index = int(session["turn_count"]) + 1
    turn_id = uuid.uuid4()
    payload = {**(retrieved or {}), **(extra or {})}
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO account_chat_turns (
                id, session_id, turn_index, partner_text, aac_text, retrieved
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                turn_id,
                session_id,
                turn_index,
                partner_text,
                aac_text,
                Jsonb(payload),
            ),
        )
        if title_update:
            conn.execute(
                """
                UPDATE account_chat_sessions
                SET turn_count = %s, pending = NULL, updated_at = now(), title = %s
                WHERE id = %s AND user_id = %s
                """,
                (turn_index, title_update, session_id, user_id),
            )
        else:
            conn.execute(
                """
                UPDATE account_chat_sessions
                SET turn_count = %s, pending = NULL, updated_at = now()
                WHERE id = %s AND user_id = %s
                """,
                (turn_index, session_id, user_id),
            )
    return {
        "turn_index": turn_index,
        "turn_id": str(turn_id),
    }


def propose_aac_candidates(
    user_id: str,
    session_id: str,
    partner_text: str,
    sensing: dict | None = None,
    quick_phrases: list[str] | None = None,
) -> dict:
    from backend.agent.orchestrator import propose_aac_candidates as _run

    return _run(user_id, session_id, partner_text, sensing, quick_phrases)


def commit_picture_board_turn(
    user_id: str,
    session_id: str,
    partner_text: str,
    aac_text: str,
) -> dict:
    from backend.agent.orchestrator import commit_picture_board_turn as _run

    return _run(user_id, session_id, partner_text, aac_text)


def pick_aac_candidate(
    user_id: str,
    session_id: str,
    candidate_id: str,
) -> dict:
    from backend.agent.orchestrator import pick_aac_candidate as _run

    return _run(user_id, session_id, candidate_id)


def generate_aac_reply(user_id: str, session_id: str, partner_text: str) -> dict:
    return propose_aac_candidates(user_id, session_id, partner_text)
