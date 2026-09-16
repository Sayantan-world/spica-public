"""Agent tools: memory, profile, dialogue, reply generation, persist."""

from typing import Any

from backend.agent.registry import ToolRegistry, tool
from backend.process_user_data import account_chat as chat

_REGISTRY: ToolRegistry | None = None


@tool("get_session", "Load a chat session, turns, and dialogue history.")
def get_session(user_id: str, session_id: str) -> dict:
    return chat.get_session(user_id, session_id)


@tool("load_profile", "Load the AAC user's name and durable profile summary.")
def load_profile(user_id: str, session_id: str, session: dict) -> dict:
    return chat.tool_load_profile(user_id, session_id, session)


@tool("retrieve_memory", "Vector-search personal memory chunks for the partner turn.")
def retrieve_memory(user_id: str, query: str, k: int = 2) -> list[dict]:
    return chat.retrieve_memory_chunks(user_id, query, k=k)


@tool("retrieve_facts", "Vector-search stored facts for the partner turn.")
def retrieve_facts(user_id: str, query: str, k: int = 2) -> list[dict]:
    return chat.retrieve_fact_chunks(user_id, query, k=k)


@tool("format_history", "Format recent dialogue for the reply-generation prompt.")
def format_history(
    session: dict,
    exclude_quick_texts: set[str] | None = None,
) -> str:
    return chat._history_for_prompt(
        session.get("turns") or [],
        messages=session.get("messages") or [],
        exclude_quick_texts=exclude_quick_texts,
    )


@tool("generate_reply_options", "Call Luna to produce four first-person reply options.")
def generate_reply_options(
    display_name: str,
    profile_summary: str,
    partner_text: str,
    history: str,
    memory_hits: list[dict],
    fact_hits: list[dict],
    sensing: dict | None = None,
    live_phrases: list[str] | None = None,
) -> list[dict]:
    return chat.tool_generate_reply_options(
        display_name=display_name,
        profile_summary=profile_summary,
        partner_text=partner_text,
        history=history,
        memory_hits=memory_hits,
        fact_hits=fact_hits,
        sensing=sensing,
        live_phrases=live_phrases,
    )


@tool("store_pending", "Save the four options as a pending pick on the session.")
def store_pending(
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
    return chat.tool_store_pending(
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


@tool("commit_turn", "Write partner + AAC reply as a completed session turn.")
def commit_turn(
    user_id: str,
    session_id: str,
    session: dict,
    partner_text: str,
    aac_text: str,
    retrieved: dict,
    extra: dict | None = None,
    title_update: str | None = None,
) -> dict:
    return chat.tool_commit_turn(
        user_id=user_id,
        session_id=session_id,
        session=session,
        partner_text=partner_text,
        aac_text=aac_text,
        retrieved=retrieved,
        extra=extra,
        title_update=title_update,
    )


@tool("write_memory", "Extract durable details from a finished turn and store them.")
def write_memory(user_id: str, partner_text: str, aac_text: str) -> dict[str, Any]:
    return chat._persist_new_details(
        user_id, partner_text=partner_text, aac_text=aac_text
    )


def get_registry() -> ToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        registry = ToolRegistry()
        for fn in (
            get_session,
            load_profile,
            retrieve_memory,
            retrieve_facts,
            format_history,
            generate_reply_options,
            store_pending,
            commit_turn,
            write_memory,
        ):
            registry.register(fn._agent_tool)  # type: ignore[attr-defined]
        _REGISTRY = registry
    return _REGISTRY
