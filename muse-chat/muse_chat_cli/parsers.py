"""Validate records extracted from the live Muse DOM."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from cli_tools_shared.exceptions import ClientError


THREAD_PATH_RE = re.compile(r"^/thread/([0-9a-fA-F-]{36})/?$")


def normalize_messages(raw: Any) -> list[dict]:
    """Return validated chat messages in DOM order."""
    if not isinstance(raw, list):
        raise ClientError("Muse chat message data was not a list.")
    messages = []
    for row in raw:
        if not isinstance(row, dict):
            raise ClientError("Muse chat message data contained a non-object entry.")
        role = row.get("role")
        text = row.get("text")
        dom_index = row.get("dom_index")
        message_id = row.get("message_id")
        turn_id = row.get("turn_id")
        if role not in {"user", "assistant"} or not isinstance(text, str) or not text.strip():
            raise ClientError("Muse chat message data contained an invalid role or text.")
        if not isinstance(dom_index, int) or dom_index < 0:
            raise ClientError("Muse chat message data contained an invalid DOM index.")
        if not isinstance(message_id, str) or not message_id.strip():
            raise ClientError("Muse chat message data had no durable message ID.")
        message = {
            "role": role,
            "text": text.strip(),
            "dom_index": dom_index,
            "message_id": message_id.strip(),
        }
        if isinstance(turn_id, str) and turn_id.strip():
            message["turn_id"] = turn_id.strip()
        messages.append(message)
    return messages


def normalize_threads(raw: Any) -> list[dict]:
    """Extract unique durable side-chat IDs from switcher records."""
    if not isinstance(raw, list):
        raise ClientError("Muse side-chat data was not a list.")
    threads: list[dict] = []
    seen: set[str] = set()
    for row in raw:
        if not isinstance(row, dict):
            continue
        raw_id = str(row.get("thread_id") or "").strip()
        href = str(row.get("href") or "").strip()
        if not raw_id and href:
            match = THREAD_PATH_RE.fullmatch(urlparse(href).path)
            raw_id = match.group(1) if match else ""
        try:
            thread_id = str(UUID(raw_id))
        except ValueError:
            continue
        if thread_id in seen:
            continue
        seen.add(thread_id)
        title = str(row.get("title") or "").strip()
        threads.append(
            {
                "id": thread_id,
                "title": title or thread_id,
                "url": f"https://muse.ai/thread/{thread_id}",
                "kind": "side",
            }
        )
    return threads


def normalize_chat(raw: Any) -> dict:
    """Return one chat and its message history."""
    if not isinstance(raw, dict):
        raise ClientError("Muse chat data was not an object.")
    chat_id = raw.get("id")
    url = raw.get("url")
    if not isinstance(chat_id, str) or not chat_id:
        raise ClientError("Muse chat data had no ID.")
    if not isinstance(url, str) or not url.startswith("https://muse.ai/"):
        raise ClientError("Muse chat data had an invalid URL.")
    return {
        "id": chat_id,
        "url": url,
        "messages": normalize_messages(raw.get("messages")),
        "typing": bool(raw.get("typing")),
    }
