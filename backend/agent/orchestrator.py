"""Fixed-plan orchestrator. Same steps as before; tools do the work."""

from backend.agent.tools import get_registry
from backend.config.settings import settings


def _session_limits() -> tuple[int, int]:
    return (
        int(settings.max_chat_sessions_per_user),
        int(settings.max_chat_turns_per_session),
    )


def propose_aac_candidates(
    user_id: str,
    session_id: str,
    partner_text: str,
    sensing: dict | None = None,
    quick_phrases: list[str] | None = None,
) -> dict:
    """Generate 4 reply options; store as pending until AAC user picks one."""
    tools = get_registry()
    max_sessions, max_turns = _session_limits()
    del max_sessions
    partner_text = (partner_text or "").strip()
    if not partner_text:
        raise ValueError("empty partner message")

    live_phrases: list[str] = []
    for p in quick_phrases or []:
        text = (p or "").strip()
        if text and text not in live_phrases:
            live_phrases.append(text)

    session = tools.call("get_session", user_id=user_id, session_id=session_id)
    if session.get("pending"):
        raise ValueError("pick a reply first before the partner sends another message")
    if session["turn_count"] >= max_turns:
        raise ValueError(
            f"this conversation reached the {max_turns}-turn limit. Start a new session."
        )

    profile = tools.call(
        "load_profile", user_id=user_id, session_id=session_id, session=session
    )
    memory_hits = tools.call(
        "retrieve_memory", user_id=user_id, query=partner_text, k=2
    )
    fact_hits = tools.call("retrieve_facts", user_id=user_id, query=partner_text, k=2)
    history = tools.call(
        "format_history",
        session=session,
        exclude_quick_texts=set(live_phrases),
    )
    candidates = tools.call(
        "generate_reply_options",
        display_name=profile["display_name"],
        profile_summary=profile["profile_summary"],
        partner_text=partner_text,
        history=history,
        memory_hits=memory_hits,
        fact_hits=fact_hits,
        sensing=sensing,
        live_phrases=live_phrases,
    )
    retrieved = {"memory": memory_hits, "facts": fact_hits}
    return tools.call(
        "store_pending",
        user_id=user_id,
        session_id=session_id,
        session=session,
        partner_text=partner_text,
        candidates=candidates,
        retrieved=retrieved,
        sensing=sensing,
        live_phrases=live_phrases,
        max_turns=max_turns,
    )


def commit_picture_board_turn(
    user_id: str,
    session_id: str,
    partner_text: str,
    aac_text: str,
) -> dict:
    """Commit partner message + picture-board phrase as a completed turn (no picker)."""
    tools = get_registry()
    max_sessions, max_turns = _session_limits()
    del max_sessions
    partner_text = (partner_text or "").strip()
    aac_text = (aac_text or "").strip()
    if not partner_text:
        raise ValueError("empty partner message")
    if not aac_text:
        raise ValueError("empty picture-board reply")

    session = tools.call("get_session", user_id=user_id, session_id=session_id)
    if session.get("pending"):
        raise ValueError("pick a reply first before the partner sends another message")
    if session["turn_count"] >= max_turns:
        raise ValueError(
            f"this conversation reached the {max_turns}-turn limit. Start a new session."
        )

    title_update = None
    if int(session["turn_count"]) == 0:
        title_update = partner_text[:60].strip() or "Conversation"

    committed = tools.call(
        "commit_turn",
        user_id=user_id,
        session_id=session_id,
        session=session,
        partner_text=partner_text,
        aac_text=aac_text,
        retrieved={"source": "picture_board"},
        extra={"source": "picture_board"},
        title_update=title_update,
    )
    memory_update = tools.call(
        "write_memory",
        user_id=user_id,
        partner_text=partner_text,
        aac_text=aac_text,
    )
    return {
        "session_id": session_id,
        "turn_index": committed["turn_index"],
        "turn_id": committed["turn_id"],
        "partner_text": partner_text,
        "aac_text": aac_text,
        "turn_count": committed["turn_index"],
        "max_turns": max_turns,
        "memory_update": memory_update,
        "awaiting_pick": False,
        "direct_reply": True,
        "title": title_update or session.get("title"),
        "candidates": [],
    }


def pick_aac_candidate(
    user_id: str,
    session_id: str,
    candidate_id: str,
) -> dict:
    """Commit the AAC user's chosen candidate as the turn reply."""
    tools = get_registry()
    max_sessions, max_turns = _session_limits()
    del max_sessions
    session = tools.call("get_session", user_id=user_id, session_id=session_id)
    pending = session.get("pending")
    if not pending or not isinstance(pending, dict):
        raise ValueError("no pending replies to pick from")
    if session["turn_count"] >= max_turns:
        raise ValueError(
            f"this conversation reached the {max_turns}-turn limit. Start a new session."
        )

    candidates = pending.get("candidates") or []
    chosen = None
    for c in candidates:
        if str(c.get("id")) == str(candidate_id):
            chosen = c
            break
    if chosen is None:
        raise ValueError("candidate not found")

    partner_text = str(pending.get("partner_text") or "").strip()
    aac_text = str(chosen.get("text") or "").strip()
    if not partner_text or not aac_text:
        raise ValueError("invalid pending turn")
    retrieved = pending.get("retrieved") if isinstance(pending.get("retrieved"), dict) else {}

    committed = tools.call(
        "commit_turn",
        user_id=user_id,
        session_id=session_id,
        session=session,
        partner_text=partner_text,
        aac_text=aac_text,
        retrieved=retrieved,
        extra={
            "chosen": {
                "id": chosen.get("id"),
                "strategy": chosen.get("strategy"),
                "label": chosen.get("label"),
            }
        },
        title_update=None,
    )
    memory_update = tools.call(
        "write_memory",
        user_id=user_id,
        partner_text=partner_text,
        aac_text=aac_text,
    )
    return {
        "session_id": session_id,
        "turn_index": committed["turn_index"],
        "turn_id": committed["turn_id"],
        "partner_text": partner_text,
        "aac_text": aac_text,
        "chosen": chosen,
        "retrieved": retrieved,
        "turn_count": committed["turn_index"],
        "max_turns": max_turns,
        "memory_update": memory_update,
        "awaiting_pick": False,
    }
