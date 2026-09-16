import hashlib
import json
import re
import secrets
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from backend.config.settings import settings

_pool: ConnectionPool | None = None
_PBKDF2_ROUNDS = 120_000
_SESSION_DAYS = 30


def _configure_conn(conn):
    register_vector(conn)


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=4,
            kwargs={"row_factory": dict_row, "autocommit": True},
            configure=_configure_conn,
        )
    return _pool


def init_db() -> None:
    settings.user_data_dir.mkdir(parents=True, exist_ok=True)
    dim = int(settings.user_embed_dim)
    with get_pool().connection() as conn:
        try:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception:
            # Extension must be created by a superuser once; ignore if already present.
            pass
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id UUID PRIMARY KEY,
                username TEXT,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                dob DATE NOT NULL,
                password_hash TEXT NOT NULL,
                relations JSONB NOT NULL DEFAULT '[]'::jsonb,
                profile_facts JSONB NOT NULL DEFAULT '{}'::jsonb,
                facts JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            ALTER TABLE accounts
            ADD COLUMN IF NOT EXISTS relations JSONB NOT NULL DEFAULT '[]'::jsonb
            """
        )
        conn.execute(
            """
            ALTER TABLE accounts
            ADD COLUMN IF NOT EXISTS profile_facts JSONB NOT NULL DEFAULT '{}'::jsonb
            """
        )
        conn.execute(
            """
            ALTER TABLE accounts
            ADD COLUMN IF NOT EXISTS facts JSONB NOT NULL DEFAULT '[]'::jsonb
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS accounts_name_idx
            ON accounts (lower(first_name), lower(last_name))
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_sessions (
                token TEXT PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                expires_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_uploads (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                filename TEXT NOT NULL,
                char_count INT NOT NULL,
                stored_path TEXT NOT NULL,
                content_type TEXT,
                process_status TEXT NOT NULL DEFAULT 'pending',
                processed_at TIMESTAMPTZ,
                chunk_count INT NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        for col, ddl in [
            ("content_type", "ALTER TABLE account_uploads ADD COLUMN IF NOT EXISTS content_type TEXT"),
            (
                "process_status",
                "ALTER TABLE account_uploads ADD COLUMN IF NOT EXISTS process_status TEXT NOT NULL DEFAULT 'pending'",
            ),
            (
                "processed_at",
                "ALTER TABLE account_uploads ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ",
            ),
            (
                "chunk_count",
                "ALTER TABLE account_uploads ADD COLUMN IF NOT EXISTS chunk_count INT NOT NULL DEFAULT 0",
            ),
            (
                "process_progress",
                "ALTER TABLE account_uploads ADD COLUMN IF NOT EXISTS process_progress INT NOT NULL DEFAULT 0",
            ),
            (
                "process_message",
                "ALTER TABLE account_uploads ADD COLUMN IF NOT EXISTS process_message TEXT NOT NULL DEFAULT ''",
            ),
        ]:
            conn.execute(ddl)
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS account_memory_chunks (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                upload_id UUID REFERENCES account_uploads(id) ON DELETE CASCADE,
                chunk_text TEXT NOT NULL,
                bucket TEXT NOT NULL DEFAULT 'other',
                source_kind TEXT NOT NULL,
                embedding vector({dim}),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS account_memory_chunks_user_idx
            ON account_memory_chunks (user_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS account_memory_chunks_upload_idx
            ON account_memory_chunks (upload_id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_chat_sessions (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                title TEXT NOT NULL DEFAULT 'Conversation',
                profile_summary TEXT NOT NULL DEFAULT '',
                turn_count INT NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS account_chat_sessions_user_idx
            ON account_chat_sessions (user_id, updated_at DESC)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_chat_turns (
                id UUID PRIMARY KEY,
                session_id UUID NOT NULL REFERENCES account_chat_sessions(id) ON DELETE CASCADE,
                turn_index INT NOT NULL,
                partner_text TEXT NOT NULL,
                aac_text TEXT NOT NULL,
                retrieved JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (session_id, turn_index)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS account_chat_turns_session_idx
            ON account_chat_turns (session_id, turn_index)
            """
        )
        conn.execute(
            """
            ALTER TABLE accounts
            ADD COLUMN IF NOT EXISTS profile_summary TEXT NOT NULL DEFAULT ''
            """
        )
        conn.execute(
            """
            ALTER TABLE account_chat_sessions
            ADD COLUMN IF NOT EXISTS pending JSONB
            """
        )
        conn.execute(
            """
            ALTER TABLE account_chat_sessions
            ADD COLUMN IF NOT EXISTS aside_messages JSONB NOT NULL DEFAULT '[]'::jsonb
            """
        )
        conn.execute(
            """
            ALTER TABLE accounts
            ADD COLUMN IF NOT EXISTS username TEXT
            """
        )
        _backfill_usernames(conn)
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS accounts_username_idx
            ON accounts (lower(username))
            WHERE username IS NOT NULL
            """
        )
        conn.execute(
            """
            ALTER TABLE accounts
            ADD COLUMN IF NOT EXISTS voice_preference TEXT NOT NULL DEFAULT 'Jason'
            """
        )
        conn.execute(
            """
            UPDATE accounts
            SET voice_preference = 'Jason'
            WHERE voice_preference IS NULL OR btrim(voice_preference) = ''
            """
        )


def _slug_username(first_name: str, last_name: str) -> str:
    raw = f"{first_name or ''}{last_name or ''}".lower()
    slug = re.sub(r"[^a-z0-9]", "", raw)
    return slug or "user"


def _backfill_usernames(conn) -> None:
    rows = conn.execute(
        """
        SELECT id, first_name, last_name, username
        FROM accounts
        WHERE username IS NULL OR btrim(username) = ''
        """
    ).fetchall()
    if not rows:
        return
    taken = {
        str(r["username"]).lower()
        for r in conn.execute(
            "SELECT username FROM accounts WHERE username IS NOT NULL AND btrim(username) <> ''"
        ).fetchall()
    }
    for row in rows:
        base = _slug_username(row["first_name"], row["last_name"])
        candidate = base
        n = 2
        while candidate.lower() in taken:
            candidate = f"{base}{n}"
            n += 1
        conn.execute(
            "UPDATE accounts SET username = %s WHERE id = %s",
            (candidate, row["id"]),
        )
        taken.add(candidate.lower())


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), _PBKDF2_ROUNDS
    )
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds_s, salt, hexdigest = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("ascii"),
            int(rounds_s),
        )
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(digest.hex(), hexdigest)


def public_user(row: dict) -> dict:
    dob = row["dob"]
    dob_s = dob.isoformat() if isinstance(dob, date) else str(dob)
    relations = row.get("relations")
    if isinstance(relations, str):
        try:
            relations = json.loads(relations)
        except json.JSONDecodeError:
            relations = []
    profile_facts = row.get("profile_facts")
    if isinstance(profile_facts, str):
        try:
            profile_facts = json.loads(profile_facts)
        except json.JSONDecodeError:
            profile_facts = {}
    facts = row.get("facts")
    if isinstance(facts, str):
        try:
            facts = json.loads(facts)
        except json.JSONDecodeError:
            facts = []
    if not isinstance(relations, list):
        relations = []
    if not isinstance(facts, list):
        facts = []
    flat_facts = flatten_facts(profile_facts if isinstance(profile_facts, dict) else {})
    clean_facts = []
    for item in facts:
        if isinstance(item, str) and item.strip():
            clean_facts.append({"text": item.strip(), "char_count": len(item.strip())})
        elif isinstance(item, dict) and str(item.get("text") or "").strip():
            text = str(item["text"]).strip()
            clean_facts.append(
                {
                    "text": text,
                    "char_count": int(item.get("char_count") or len(text)),
                    "source_upload_id": item.get("source_upload_id"),
                }
            )
    return {
        "id": str(row["id"]),
        "username": row.get("username") or "",
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "dob": dob_s,
        "voice_preference": (row.get("voice_preference") or "Jason").strip() or "Jason",
        "relations": relations,
        "profile_facts": flat_facts,
        "facts": clean_facts,
    }


def create_session(user_id) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(days=_SESSION_DAYS)
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO account_sessions (token, user_id, expires_at)
            VALUES (%s, %s, %s)
            """,
            (token, user_id, expires),
        )
    return token


def user_dir(user_id: str) -> Path:
    path = settings.user_data_dir / user_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def merge_relations(
    existing: list,
    incoming: list,
    *,
    upload_id: str | None = None,
    replace_upload_id: str | None = None,
) -> list:
    seen: set[str] = set()
    out: list[dict] = []
    for r in list(existing or []):
        if not isinstance(r, dict):
            continue
        if replace_upload_id and str(r.get("source_upload_id") or "") == replace_upload_id:
            continue
        key = (
            f"{r.get('subject', '')}|{r.get('relation', '')}|{r.get('object', '')}"
        ).lower()
        if not key.strip("|") or key in seen:
            continue
        seen.add(key)
        out.append(r)
    for r in list(incoming or []):
        if not isinstance(r, dict):
            continue
        item = dict(r)
        if upload_id:
            item["source_upload_id"] = upload_id
        key = (
            f"{item.get('subject', '')}|{item.get('relation', '')}|{item.get('object', '')}"
        ).lower()
        if not key.strip("|") or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out[:200]


def _fact_value(entry) -> str:
    if isinstance(entry, dict) and "value" in entry:
        return str(entry.get("value") or "")[:400]
    return str(entry)[:400]


def merge_facts(
    existing: dict,
    incoming: dict,
    *,
    upload_id: str | None = None,
    replace_upload_id: str | None = None,
) -> dict:
    merged: dict = {}
    for k, v in (existing or {}).items():
        key = str(k)[:80]
        if replace_upload_id and isinstance(v, dict):
            if str(v.get("source_upload_id") or "") == replace_upload_id:
                continue
        if isinstance(v, dict) and "value" in v:
            merged[key] = {
                "value": str(v.get("value") or "")[:400],
                "source_upload_id": v.get("source_upload_id"),
            }
        else:
            merged[key] = {"value": str(v)[:400], "source_upload_id": None}
    for k, v in (incoming or {}).items():
        key = str(k)[:80]
        merged[key] = {
            "value": str(v)[:400],
            "source_upload_id": upload_id,
        }
    return merged


def flatten_facts(facts: dict | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in (facts or {}).items():
        out[str(k)] = _fact_value(v)
    return out


def merge_fact_list(
    existing: list,
    incoming: list,
    *,
    upload_id: str | None = None,
    replace_upload_id: str | None = None,
) -> list:
    """Merge narrative fact chunks (400–500 char) tagged by upload."""
    out: list[dict] = []
    seen: set[str] = set()
    for item in list(existing or []):
        if not isinstance(item, dict):
            continue
        if replace_upload_id and str(item.get("source_upload_id") or "") == replace_upload_id:
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    for item in list(incoming or []):
        if isinstance(item, str):
            text = item.strip()
            entry = {"text": text}
        elif isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            entry = dict(item)
            entry["text"] = text
        else:
            continue
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        if upload_id:
            entry["source_upload_id"] = upload_id
        entry["char_count"] = len(text)
        out.append(entry)
    return out[:500]


def strip_upload_derived(
    existing_relations: list,
    existing_facts: dict,
    upload_id: str,
    existing_fact_list: list | None = None,
):
    relations = [
        r
        for r in (existing_relations or [])
        if not (isinstance(r, dict) and str(r.get("source_upload_id") or "") == upload_id)
    ]
    facts = {}
    for k, v in (existing_facts or {}).items():
        if isinstance(v, dict) and str(v.get("source_upload_id") or "") == upload_id:
            continue
        facts[k] = v
    fact_list = [
        f
        for f in (existing_fact_list or [])
        if not (isinstance(f, dict) and str(f.get("source_upload_id") or "") == upload_id)
    ]
    return relations, facts, fact_list
