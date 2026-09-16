import json
import logging
import queue
import re
import threading
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pgvector import Vector
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from backend.config.settings import settings
from backend.process_user_data.db import (
    create_session,
    flatten_facts,
    get_pool,
    hash_password,
    merge_fact_list,
    merge_facts,
    merge_relations,
    public_user,
    strip_upload_derived,
    user_dir,
    verify_password,
)
from backend.process_user_data.embeddings import embed_documents
from backend.process_user_data.processor import (
    process_json_document,
    process_raw_text,
    try_parse_json_document,
)

router = APIRouter(prefix="/account", tags=["account"])
_log = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z '\-]{0,79}$")
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{2,39}$")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    dob: date
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=128)


class PasteIn(BaseModel):
    filename: str | None = Field(default=None, max_length=120)
    content: str = Field(min_length=1, max_length=settings.max_text_file_chars)


def _clean_name(value: str, field: str) -> str:
    name = " ".join(value.split())
    if not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail=f"invalid {field}")
    return name


def _clean_username(value: str) -> str:
    username = "".join(value.strip().lower().split())
    if not _USERNAME_RE.match(username):
        raise HTTPException(
            status_code=400,
            detail="username must be 3–40 chars: lowercase letters, numbers, underscore",
        )
    return username


def _validate_dob(dob: date) -> None:
    if dob > date.today():
        raise HTTPException(status_code=400, detail="date of birth cannot be in the future")


def require_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="not signed in")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="not signed in")
    with get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT a.id, a.username, a.first_name, a.last_name, a.dob, a.voice_preference,
                   a.relations, a.profile_facts, a.facts, s.expires_at
            FROM account_sessions s
            JOIN accounts a ON a.id = s.user_id
            WHERE s.token = %s
            """,
            (token,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="not signed in")
    expires = row["expires_at"]
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        raise HTTPException(status_code=401, detail="session expired")
    return {"id": str(row["id"]), "row": row, "token": token}


def _upload_count(user_id: str) -> int:
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM account_uploads WHERE user_id = %s",
            (user_id,),
        ).fetchone()
    return int(row["n"]) if row else 0


def _safe_filename(name: str, fallback: str) -> str:
    base = Path(name or "").name.strip() or fallback
    if not base.lower().endswith(".txt"):
        base = f"{base}.txt"
    cleaned = _SAFE_NAME_RE.sub("_", base).strip("._") or fallback
    if not cleaned.lower().endswith(".txt"):
        cleaned = f"{cleaned}.txt"
    return cleaned[:120]


def _upload_out(row: dict) -> dict:
    created = row.get("created_at")
    processed = row.get("processed_at")
    return {
        "id": str(row["id"]),
        "kind": row["kind"],
        "filename": row["filename"],
        "char_count": row["char_count"],
        "content_type": row.get("content_type"),
        "process_status": row.get("process_status") or "pending",
        "process_progress": int(row.get("process_progress") or 0),
        "process_message": row.get("process_message") or "",
        "chunk_count": int(row.get("chunk_count") or 0),
        "processed_at": processed.isoformat() if processed else None,
        "created_at": created.isoformat() if created else None,
    }


def _set_progress(
    upload_id,
    pct: int | None,
    message: str,
    status: str | None = None,
) -> None:
    with get_pool().connection() as conn:
        if pct is None:
            if status:
                conn.execute(
                    """
                    UPDATE account_uploads
                    SET process_message = %s, process_status = %s
                    WHERE id = %s
                    """,
                    (message[:240], status, upload_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE account_uploads
                    SET process_message = %s
                    WHERE id = %s
                    """,
                    (message[:240], upload_id),
                )
            return
        pct_i = max(0, min(100, int(pct)))
        if status:
            conn.execute(
                """
                UPDATE account_uploads
                SET process_progress = %s, process_message = %s, process_status = %s
                WHERE id = %s
                """,
                (pct_i, message[:240], status, upload_id),
            )
        else:
            conn.execute(
                """
                UPDATE account_uploads
                SET process_progress = %s, process_message = %s
                WHERE id = %s
                """,
                (pct_i, message[:240], upload_id),
            )


def _store_text(user_id: str, kind: str, filename: str, text: str) -> dict:
    if _upload_count(user_id) >= settings.max_text_files_per_user:
        raise HTTPException(
            status_code=409,
            detail=f"file limit reached ({settings.max_text_files_per_user}). delete one to add another.",
        )
    if len(text) > settings.max_text_file_chars:
        raise HTTPException(
            status_code=400,
            detail=f"file exceeds {settings.max_text_file_chars} character limit",
        )
    upload_id = uuid.uuid4()
    stored = user_dir(user_id) / f"{upload_id}.txt"
    stored.write_text(text, encoding="utf-8")
    with get_pool().connection() as conn:
        row = conn.execute(
            """
            INSERT INTO account_uploads (
                id, user_id, kind, filename, char_count, stored_path,
                process_status, process_progress, process_message
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'pending', 0, '')
            RETURNING id, kind, filename, char_count, content_type, process_status,
                      process_progress, process_message, chunk_count, processed_at, created_at
            """,
            (upload_id, user_id, kind, filename, len(text), str(stored)),
        ).fetchone()
    return _upload_out(row)


def _process_upload(
    user_id: str,
    upload_id: uuid.UUID,
    on_progress: Callable[[int | None, str], None] | None = None,
) -> dict:
    last_pct = 0

    def progress(pct: int | None, message: str, status: str | None = None) -> None:
        nonlocal last_pct
        if pct is not None:
            last_pct = max(0, min(100, int(pct)))
        _set_progress(upload_id, pct, message, status=status)
        if on_progress:
            on_progress(last_pct if pct is None else pct, message)

    with get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT id, stored_path, filename, process_status
            FROM account_uploads
            WHERE id = %s AND user_id = %s
            """,
            (upload_id, user_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="file not found")
        acct = conn.execute(
            "SELECT relations, profile_facts, facts FROM accounts WHERE id = %s",
            (user_id,),
        ).fetchone()

    progress(2, "Starting…", status="processing")

    path = Path(row["stored_path"])
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        progress(0, "Could not read file", status="failed")
        raise HTTPException(status_code=500, detail="could not read uploaded file") from exc

    progress(8, "Detecting JSON vs raw text…")
    parsed = try_parse_json_document(text)
    content_type = "json" if parsed is not None else "raw_text"
    progress(
        12,
        "Detected JSON document" if content_type == "json" else "Detected raw text",
    )

    try:
        extracted = (
            process_json_document(parsed, on_progress=lambda p, m: progress(p, m))
            if parsed is not None
            else process_raw_text(text, on_progress=lambda p, m: progress(p, m))
        )
    except Exception as exc:
        _log.exception("process upload failed: %s", upload_id)
        progress(0, f"Processing failed: {exc}", status="failed")
        raise HTTPException(status_code=502, detail=f"processing failed: {exc}") from exc

    chunks = extracted.get("chunks") or []
    texts = [c["text"] for c in chunks if c.get("text")]
    vectors: list[list[float]] = []
    if texts:
        progress(65, f"Embedding {len(texts)} chunks with nomic…")
        try:
            vectors = embed_documents(texts)
        except Exception as exc:
            _log.exception("embedding failed for upload %s", upload_id)
            progress(0, f"Embedding failed: {exc}", status="failed")
            raise HTTPException(status_code=500, detail=f"embedding failed: {exc}") from exc
        progress(82, "Embeddings ready")
    else:
        progress(70, "No chunks to embed")

    existing_relations = acct["relations"] if acct else []
    existing_profile_facts = acct["profile_facts"] if acct else {}
    existing_fact_list = acct.get("facts") if acct else []
    if isinstance(existing_relations, str):
        existing_relations = json.loads(existing_relations)
    if isinstance(existing_profile_facts, str):
        existing_profile_facts = json.loads(existing_profile_facts)
    if isinstance(existing_fact_list, str):
        existing_fact_list = json.loads(existing_fact_list)

    upload_id_s = str(upload_id)
    merged_relations = merge_relations(
        existing_relations,
        extracted.get("relations") or [],
        upload_id=upload_id_s,
        replace_upload_id=upload_id_s,
    )
    merged_profile_facts = merge_facts(
        existing_profile_facts if isinstance(existing_profile_facts, dict) else {},
        extracted.get("profile_facts") or {},
        upload_id=upload_id_s,
        replace_upload_id=upload_id_s,
    )
    merged_fact_list = merge_fact_list(
        existing_fact_list if isinstance(existing_fact_list, list) else [],
        extracted.get("facts") or extracted.get("chunks") or [],
        upload_id=upload_id_s,
        replace_upload_id=upload_id_s,
    )

    progress(88, "Saving fact chunks…")
    with get_pool().connection() as conn:
        conn.execute(
            "DELETE FROM account_memory_chunks WHERE upload_id = %s AND user_id = %s",
            (upload_id, user_id),
        )
        for i, chunk in enumerate(chunks):
            text_i = chunk.get("text") or ""
            if not text_i:
                continue
            emb = vectors[i] if i < len(vectors) else None
            conn.execute(
                """
                INSERT INTO account_memory_chunks (
                    id, user_id, upload_id, chunk_text, bucket, source_kind, embedding
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid.uuid4(),
                    user_id,
                    upload_id,
                    text_i,
                    chunk.get("bucket") or ("facts" if content_type == "raw_text" else "other"),
                    content_type,
                    Vector(emb) if emb is not None else None,
                ),
            )
        conn.execute(
            """
            UPDATE accounts
            SET relations = %s, profile_facts = %s, facts = %s
            WHERE id = %s
            """,
            (
                Jsonb(merged_relations),
                Jsonb(merged_profile_facts),
                Jsonb(merged_fact_list),
                user_id,
            ),
        )
        out = conn.execute(
            """
            UPDATE account_uploads
            SET content_type = %s,
                process_status = 'done',
                processed_at = now(),
                chunk_count = %s,
                process_progress = 100,
                process_message = %s
            WHERE id = %s AND user_id = %s
            RETURNING id, kind, filename, char_count, content_type, process_status,
                      process_progress, process_message, chunk_count, processed_at, created_at
            """,
            (
                content_type,
                len(texts),
                "Done",
                upload_id,
                user_id,
            ),
        ).fetchone()

    if on_progress:
        on_progress(100, "Done")

    return {
        "upload": _upload_out(out),
        "content_type": content_type,
        "chunks_stored": len(texts),
        "relations_added": len(extracted.get("relations") or []),
        "relations_total": len(merged_relations),
        "profile_facts": flatten_facts(merged_profile_facts),
        "facts_stored": len(merged_fact_list),
    }


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/register")
def register(body: RegisterIn):
    username = _clean_username(body.username)
    first = _clean_name(body.first_name, "first name")
    last = _clean_name(body.last_name, "last name")
    _validate_dob(body.dob)
    user_id = uuid.uuid4()
    try:
        with get_pool().connection() as conn:
            row = conn.execute(
                """
                INSERT INTO accounts (id, username, first_name, last_name, dob, password_hash)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, username, first_name, last_name, dob, voice_preference,
                          relations, profile_facts, facts
                """,
                (user_id, username, first, last, body.dob, hash_password(body.password)),
            ).fetchone()
    except UniqueViolation as exc:
        detail = str(exc).lower()
        if "username" in detail:
            msg = "that username is already taken"
        else:
            msg = "an account with that name already exists"
        raise HTTPException(status_code=409, detail=msg) from exc
    token = create_session(row["id"])
    return {"token": token, "user": public_user(row)}


@router.post("/login")
def login(body: LoginIn):
    username = "".join(body.username.strip().lower().split())
    with get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT id, username, first_name, last_name, dob, voice_preference, password_hash,
                   relations, profile_facts, facts
            FROM accounts
            WHERE lower(username) = lower(%s)
            """,
            (username,),
        ).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="username or password is incorrect")
    token = create_session(row["id"])
    return {"token": token, "user": public_user(row)}


@router.post("/logout")
def logout(user: dict = Depends(require_user)):
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM account_sessions WHERE token = %s", (user["token"],))
    return {"status": "ok"}


@router.get("/me")
def me(user: dict = Depends(require_user)):
    return {"user": public_user(user["row"])}


@router.get("/stored")
def stored_memory(user: dict = Depends(require_user)):
    """Return all stored facts/relations/chunks for the signed-in user."""
    with get_pool().connection() as conn:
        acct = conn.execute(
            """
            SELECT id, first_name, last_name, dob, relations, profile_facts, facts, username
            FROM accounts
            WHERE id = %s
            """,
            (user["id"],),
        ).fetchone()
        chunks = conn.execute(
            """
            SELECT id, upload_id, chunk_text, bucket, source_kind, created_at
            FROM account_memory_chunks
            WHERE user_id = %s
            ORDER BY created_at ASC
            """,
            (user["id"],),
        ).fetchall()
    pub = public_user(acct) if acct else {}
    chunk_out = []
    for c in chunks:
        created = c.get("created_at")
        chunk_out.append(
            {
                "id": str(c["id"]),
                "upload_id": str(c["upload_id"]) if c.get("upload_id") else None,
                "text": c["chunk_text"],
                "bucket": c.get("bucket") or "other",
                "source_kind": c.get("source_kind"),
                "created_at": created.isoformat() if created else None,
            }
        )
    return {
        "facts": pub.get("facts") or [],
        "relations": pub.get("relations") or [],
        "profile_facts": pub.get("profile_facts") or {},
        "chunks": chunk_out,
    }


@router.get("/uploads")
def list_uploads(user: dict = Depends(require_user)):
    with get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT id, kind, filename, char_count, content_type, process_status,
                   process_progress, process_message, chunk_count, processed_at, created_at
            FROM account_uploads
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (user["id"],),
        ).fetchall()
    return {
        "uploads": [_upload_out(r) for r in rows],
        "limit": settings.max_text_files_per_user,
        "max_chars": settings.max_text_file_chars,
    }


@router.post("/uploads/txt")
async def upload_txt(
    file: UploadFile = File(...),
    user: dict = Depends(require_user),
):
    filename = file.filename or "upload.txt"
    if not filename.lower().endswith(".txt"):
        raise HTTPException(status_code=400, detail="only .txt files are allowed")
    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="file must be UTF-8 text") from exc
    text = text.replace("\r\n", "\n")
    return _store_text(
        user["id"], "txt_file", _safe_filename(filename, "upload.txt"), text
    )


@router.post("/uploads/text")
def upload_pasted_text(body: PasteIn, user: dict = Depends(require_user)):
    text = body.content.replace("\r\n", "\n")
    filename = _safe_filename(body.filename or "notes.txt", "notes.txt")
    return _store_text(user["id"], "pasted_text", filename, text)


@router.post("/uploads/{upload_id}/process")
def process_upload(upload_id: str, user: dict = Depends(require_user)):
    try:
        uid = uuid.UUID(upload_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid upload id") from exc
    return _process_upload(user["id"], uid)


@router.post("/uploads/{upload_id}/process/stream")
def process_upload_stream(upload_id: str, user: dict = Depends(require_user)):
    try:
        uid = uuid.UUID(upload_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid upload id") from exc

    user_id = user["id"]
    q: queue.Queue[dict | None] = queue.Queue()

    def on_progress(pct: int | None, message: str) -> None:
        q.put(
            {
                "type": "progress",
                "pct": max(0, min(100, int(pct if pct is not None else 0))),
                "message": message,
            }
        )

    def worker() -> None:
        try:
            result = _process_upload(user_id, uid, on_progress=on_progress)
            q.put({"type": "complete", "result": result})
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            q.put({"type": "error", "message": detail, "pct": 0})
        except Exception as exc:
            _log.exception("stream process failed")
            q.put({"type": "error", "message": str(exc), "pct": 0})
        finally:
            q.put(None)

    def _gen() -> Iterator[str]:
        yield _sse({"type": "progress", "pct": 1, "message": "Queued…"})
        threading.Thread(target=worker, daemon=True).start()
        while True:
            item = q.get()
            if item is None:
                break
            yield _sse(item)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/uploads/{upload_id}")
def delete_upload(upload_id: str, user: dict = Depends(require_user)):
    try:
        uid = uuid.UUID(upload_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid upload id") from exc
    upload_id_s = str(uid)
    with get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT stored_path FROM account_uploads
            WHERE id = %s AND user_id = %s
            """,
            (uid, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="file not found")

        acct = conn.execute(
            "SELECT relations, profile_facts, facts FROM accounts WHERE id = %s",
            (user["id"],),
        ).fetchone()
        relations = acct["relations"] if acct else []
        profile_facts = acct["profile_facts"] if acct else {}
        fact_list = acct["facts"] if acct else []
        if isinstance(relations, str):
            relations = json.loads(relations)
        if isinstance(profile_facts, str):
            profile_facts = json.loads(profile_facts)
        if isinstance(fact_list, str):
            fact_list = json.loads(fact_list)
        cleaned_relations, cleaned_profile_facts, cleaned_facts = strip_upload_derived(
            relations if isinstance(relations, list) else [],
            profile_facts if isinstance(profile_facts, dict) else {},
            upload_id_s,
            existing_fact_list=fact_list if isinstance(fact_list, list) else [],
        )
        conn.execute(
            """
            UPDATE accounts
            SET relations = %s, profile_facts = %s, facts = %s
            WHERE id = %s
            """,
            (
                Jsonb(cleaned_relations),
                Jsonb(cleaned_profile_facts),
                Jsonb(cleaned_facts),
                user["id"],
            ),
        )

        # Chunks/embeddings: explicit delete + FK ON DELETE CASCADE as backup.
        conn.execute(
            "DELETE FROM account_memory_chunks WHERE upload_id = %s AND user_id = %s",
            (uid, user["id"]),
        )
        conn.execute(
            "DELETE FROM account_uploads WHERE id = %s AND user_id = %s",
            (uid, user["id"]),
        )
    path = Path(row["stored_path"])
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return {"status": "ok"}


# ── Chat sessions (AAC user speaks; partner talks to them) ───────────────────


class ChatSessionCreate(BaseModel):
    title: str | None = None


class ChatTurnIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    emotion: str | None = None
    hand_gesture: str | None = None
    head_signal: str | None = None
    quick_phrases: list[str] | None = None


class ChatPickIn(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=40)


class ChatQuickIn(BaseModel):
    text: str = Field(min_length=1, max_length=400)


@router.get("/chat/sessions")
def chat_list_sessions(user: dict = Depends(require_user)):
    from backend.config.settings import settings as _settings
    from backend.process_user_data import account_chat as ac

    sessions = ac.list_sessions(user["id"])
    return {
        "sessions": sessions,
        "limit": _settings.max_chat_sessions_per_user,
        "max_turns": _settings.max_chat_turns_per_session,
    }


@router.post("/chat/sessions")
def chat_create_session(body: ChatSessionCreate, user: dict = Depends(require_user)):
    from backend.process_user_data import account_chat as ac

    try:
        session = ac.create_session(user["id"], title=body.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"session": session}


@router.get("/chat/sessions/{session_id}")
def chat_get_session(session_id: str, user: dict = Depends(require_user)):
    from backend.process_user_data import account_chat as ac

    try:
        return {"session": ac.get_session(user["id"], session_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/chat/sessions/{session_id}")
def chat_delete_session(session_id: str, user: dict = Depends(require_user)):
    from backend.process_user_data import account_chat as ac

    try:
        ac.delete_session(user["id"], session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok"}


@router.post("/chat/sessions/{session_id}/turn")
def chat_turn(session_id: str, body: ChatTurnIn, user: dict = Depends(require_user)):
    """Partner utterance → picture-board direct reply, or 4 AAC candidates."""
    from backend.process_user_data import account_chat as ac

    sensing = {
        "emotion": (body.emotion or "").strip() or None,
        "hand_gesture": (body.hand_gesture or "").strip() or None,
        "head_signal": (body.head_signal or "").strip() or None,
    }
    quick_phrases: list[str] = []
    for p in body.quick_phrases or []:
        text = (p or "").strip()
        if text and text not in quick_phrases:
            quick_phrases.append(text)
    try:
        # Picture-board signal during the wait window: commit as the AAC reply
        # and skip candidate generation.
        if quick_phrases:
            aac_text = " ".join(quick_phrases)
            result = ac.commit_picture_board_turn(
                user["id"],
                session_id,
                body.text,
                aac_text,
            )
        else:
            result = ac.propose_aac_candidates(
                user["id"],
                session_id,
                body.text,
                sensing=sensing,
            )
    except ValueError as exc:
        detail = str(exc)
        code = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=code, detail=detail) from exc
    except Exception as exc:
        _log.exception("chat turn failed")
        raise HTTPException(status_code=502, detail=f"chat failed: {exc}") from exc
    return result


@router.post("/chat/sessions/{session_id}/pick")
def chat_pick(session_id: str, body: ChatPickIn, user: dict = Depends(require_user)):
    """AAC user selects one of the 4 proposed replies."""
    from backend.process_user_data import account_chat as ac

    try:
        result = ac.pick_aac_candidate(user["id"], session_id, body.candidate_id)
    except ValueError as exc:
        detail = str(exc)
        code = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=code, detail=detail) from exc
    except Exception as exc:
        _log.exception("chat pick failed")
        raise HTTPException(status_code=502, detail=f"pick failed: {exc}") from exc
    return result


@router.post("/chat/sessions/{session_id}/quick")
def chat_quick_phrase(session_id: str, body: ChatQuickIn, user: dict = Depends(require_user)):
    """Picture-board phrase → persist in dialogue history (no TTS)."""
    from backend.process_user_data import account_chat as ac

    try:
        message = ac.append_quick_phrase(user["id"], session_id, body.text)
    except ValueError as exc:
        detail = str(exc)
        code = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=code, detail=detail) from exc
    return {"message": message}


class SpeechTtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: str | None = None
    emotion: str | None = None


class VoicePreferenceIn(BaseModel):
    voice: str = Field(min_length=2, max_length=40)


@router.get("/voice")
def get_voice_options(user: dict = Depends(require_user)):
    from backend.process_user_data import nim_speech

    pref = (user["row"].get("voice_preference") or "Jason").strip() or "Jason"
    return {
        "voice": pref,
        "options": nim_speech.VOICE_OPTIONS,
        "sample_text": nim_speech.SAMPLE_VOICE_TEXT,
    }


@router.put("/voice")
def set_voice_preference(body: VoicePreferenceIn, user: dict = Depends(require_user)):
    from backend.process_user_data import nim_speech

    voice = nim_speech.normalize_voice(body.voice)
    with get_pool().connection() as conn:
        row = conn.execute(
            """
            UPDATE accounts
            SET voice_preference = %s
            WHERE id = %s
            RETURNING id, username, first_name, last_name, dob, voice_preference,
                      relations, profile_facts, facts
            """,
            (voice, user["id"]),
        ).fetchone()
    return {"user": public_user(row), "voice": voice}


@router.post("/speech/transcribe")
async def speech_transcribe(
    file: UploadFile = File(...),
    user: dict = Depends(require_user),
):
    """Partner audio → text via NIM Whisper (Riva gRPC)."""
    del user
    from backend.process_user_data import nim_speech

    data = await file.read()
    try:
        result = nim_speech.transcribe_audio(
            data,
            filename=file.filename or "audio.wav",
            content_type=file.content_type or "audio/wav",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except nim_speech.NimSpeechUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        _log.exception("speech transcribe failed")
        raise HTTPException(
            status_code=503,
            detail="API is down, unable to use the service at this moment",
        ) from exc
    return {
        "text": result["text"],
        "provider": result["provider"],
        "model": result["model"],
    }


@router.post("/speech/tts")
def speech_tts(body: SpeechTtsIn, user: dict = Depends(require_user)):
    """AAC reply text → speech via NIM Magpie (Riva gRPC)."""
    from backend.process_user_data import nim_speech

    preferred = (body.voice or user["row"].get("voice_preference") or "Jason")
    try:
        result = nim_speech.synthesize_speech(
            body.text,
            voice=preferred,
            emotion=body.emotion,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except nim_speech.NimSpeechUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        _log.exception("speech tts failed")
        raise HTTPException(
            status_code=503,
            detail="API is down, unable to use the service at this moment",
        ) from exc
    return Response(
        content=result["audio"],
        media_type=result["media_type"],
        headers={
            "X-Speech-Provider": str(result["provider"]),
            "X-Speech-Model": str(result["model"]),
            "X-Speech-Voice": str(result.get("voice") or ""),
        },
    )


@router.get("/speech/phrases/status")
def phrase_audio_status(user: dict = Depends(require_user)):
    """Shared picture-board clip cache progress (server-side, all users)."""
    del user
    from backend.process_user_data import phrase_audio

    return phrase_audio.get_status()


@router.get("/speech/phrases/{voice}/{phrase_id}")
def phrase_audio_clip(
    voice: str,
    phrase_id: str,
    user: dict = Depends(require_user),
):
    """Serve a cached neutral phrase WAV for the picture board."""
    del user
    from backend.process_user_data import nim_speech, phrase_audio

    try:
        voice_n = nim_speech.normalize_voice(voice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    phrase_id = (phrase_id or "").strip().lower()
    if phrase_id not in phrase_audio.PHRASE_IDS:
        raise HTTPException(status_code=404, detail="unknown phrase")
    clip = phrase_audio.read_clip(voice_n, phrase_id)
    if not clip:
        # Kick warmup if somehow idle, then 404 until ready.
        phrase_audio.start_phrase_audio_warmup()
        raise HTTPException(status_code=404, detail="phrase audio not ready yet")
    data, media_type = clip
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Phrase-Voice": voice_n,
            "X-Phrase-Id": phrase_id,
        },
    )


@router.get("/speech/voices/{voice}/sample")
def voice_sample_clip(voice: str, user: dict = Depends(require_user)):
    """Serve cached neutral sample line for a Magpie speaker."""
    del user
    from backend.process_user_data import nim_speech, phrase_audio

    try:
        voice_n = nim_speech.normalize_voice(voice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    clip = phrase_audio.read_sample(voice_n)
    if not clip:
        phrase_audio.start_phrase_audio_warmup()
        raise HTTPException(status_code=404, detail="voice sample not ready yet")
    data, media_type = clip
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Speech-Voice": voice_n,
        },
    )
