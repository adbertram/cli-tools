"""Decode Grok Bot transcript entries into the CLI's public record shapes.

The Connect API returns transcript entries whose ``body`` is base64-encoded
JSON. Entry ids encode the turn they belong to (``t<n>u`` for a user message,
``t<n>s<m>`` for an agent send, ``t<n>a<m>`` for an agent-authored room
message) and the API's ``seq`` is a commit sequence rather than an entry
ordinal, so this module derives turn grouping from the ids and never re-sorts
by ``seq``.
"""
import base64
import binascii
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

KIND_AGENT = "AGENT"
KIND_ROOM = "ROOM"

# Card entry types that stand in for a tool call in Grok Bot's model.
TOOL_CALL_CARD_TYPES = (
    "local-tool-permission",
    "cursor-agent",
    "user-form",
    "widget",
)

_AGENT_KIND_PREFIX = "GROK_BOT_AGENT_KIND_"
_TURN_ID_RE = re.compile(r"^t(\d+)([usa])(\d*)$")
_TEXT_LIMIT = 160


def as_int(value: Any) -> Optional[int]:
    """Coerce a protobuf-es int64 field to ``int``.

    The Connect JSON encoding serializes int64 fields (``seq``, ``updatedSeq``,
    ``timestampMs``) as strings, so numeric comparison and arithmetic must
    coerce first.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return None


def epoch_to_iso(millis: Optional[Any]) -> str:
    """Convert a Grok Bot epoch-millisecond value to ISO 8601 UTC.

    The API serializes ``*Ms`` fields as strings, so numeric strings are
    accepted as well as ints.
    """
    millis = as_int(millis)
    if millis is None:
        return ""
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat()


def format_local_time(timestamp: str, format: str = "%b %d %H:%M") -> str:
    """Convert an ISO timestamp to local time and format it."""
    if not timestamp:
        return ""
    try:
        if timestamp.endswith("Z"):
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        else:
            parsed = datetime.fromisoformat(timestamp)
        return parsed.astimezone().strftime(format)
    except (ValueError, AttributeError):
        return timestamp[:16] if len(timestamp) > 16 else timestamp


def agent_kind(kind: Any) -> str:
    """Shorten ``GROK_BOT_AGENT_KIND_AGENT`` to ``AGENT``."""
    if not isinstance(kind, str) or not kind:
        return ""
    return kind[len(_AGENT_KIND_PREFIX):] if kind.startswith(_AGENT_KIND_PREFIX) else kind


def turn_index(identifier: Any) -> Optional[int]:
    """Return the 0-based turn number encoded in a Grok Bot entry id."""
    if not isinstance(identifier, str):
        return None
    match = _TURN_ID_RE.match(identifier)
    if match is None:
        return None
    return int(match.group(1))


def decode_body(raw_entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Decode one entry's base64 JSON ``body``.

    Returns ``None`` when the body is offloaded (``bodyOmitted``) or cannot be
    decoded, so the caller can surface a partial entry instead of crashing.
    """
    encoded = raw_entry.get("body")
    if not isinstance(encoded, str) or not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
    try:
        body = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def _initiation(body: Dict[str, Any]) -> Dict[str, Any]:
    value = body.get("initiation")
    return value if isinstance(value, dict) else {}


def _event(body: Dict[str, Any]) -> Dict[str, Any]:
    value = body.get("event")
    return value if isinstance(value, dict) else {}


def _message(body: Dict[str, Any]) -> Dict[str, Any]:
    value = body.get("message")
    return value if isinstance(value, dict) else {}


def body_entry_id(body: Dict[str, Any], fallback: str = "") -> str:
    """Return the entry id carried by a decoded body."""
    identifier = body.get("id")
    if isinstance(identifier, str) and identifier:
        return identifier
    initiation_id = _initiation(body).get("id")
    if isinstance(initiation_id, str) and initiation_id:
        return initiation_id
    return fallback


def body_turn_index(body: Dict[str, Any], fallback: str = "") -> Optional[int]:
    """Return the turn number for a decoded body.

    ``spend-initiation`` entries carry the initiating message id under
    ``initiation.id`` rather than an id of their own.
    """
    turn = turn_index(body.get("id"))
    if turn is not None:
        return turn
    return turn_index(_initiation(body).get("id")) if _initiation(body) else turn_index(fallback)


def body_resolution(body: Dict[str, Any]) -> str:
    """Return a card entry's resolution state, if the user answered it."""
    if body.get("kind") != "send-message":
        return ""
    for key in ("respondedValue", "formResolution", "boxResolution"):
        value = body.get(key)
        if value not in (None, "", False):
            return str(value)
    return ""


def body_type(body: Dict[str, Any]) -> str:
    """Return the card, event, or initiation subtype for a decoded body."""
    if body.get("kind") == "send-message":
        return str(_message(body).get("type") or "")
    if body.get("kind") == "event":
        return str(_event(body).get("type") or "")
    if body.get("kind") == "spend-initiation":
        return str(_initiation(body).get("type") or "")
    return ""


def entry_text(body: Dict[str, Any]) -> str:
    """Return the human-readable text of a decoded body, if it has any."""
    kind = body.get("kind")
    message = _message(body)
    if kind == "message":
        content = body.get("content")
        return content if isinstance(content, str) else ""
    if kind == "send-message":
        content = message.get("content")
        if isinstance(content, str) and content:
            return content
        widget = message.get("widget")
        if isinstance(widget, dict):
            prompt = widget.get("prompt")
            return prompt if isinstance(prompt, str) else ""
        form = message.get("formRequest")
        if isinstance(form, dict):
            return str(form.get("instruction") or form.get("title") or "")
        secret = message.get("secretRequest")
        if isinstance(secret, dict):
            return str(secret.get("description") or secret.get("label") or "")
        ask = message.get("ask")
        if isinstance(ask, dict):
            return str(ask.get("target") or ask.get("action") or "")
        approval = message.get("approval")
        if isinstance(approval, dict):
            return str(approval.get("summary") or approval.get("reason") or "")
    return ""


def entry_summary(body: Dict[str, Any], entry_id: str = "") -> str:
    """Return a one-line description of a decoded body for table output."""
    if not body:
        return f"undecoded body ({entry_id})" if entry_id else "undecoded body"

    kind = body.get("kind")
    subtype = body_type(body)
    text = " ".join(entry_text(body).split())

    if kind == "message":
        role = body.get("role") or "message"
        return f"{role}: {text}" if text else str(role)
    if kind == "send-message":
        if subtype == "local-tool-permission":
            ask = _message(body).get("ask")
            if isinstance(ask, dict):
                return (
                    f"permission {ask.get('action', '')} "
                    f"{ask.get('target', '')} -> {ask.get('status', 'pending')}"
                ).strip()
        if subtype == "auto-review-approval":
            approval = _message(body).get("approval")
            if isinstance(approval, dict):
                return f"auto-review-approval -> {approval.get('status', 'pending')}"
        if subtype == "cursor-agent":
            return f"cursor-agent: {_message(body).get('title') or _message(body).get('bcId') or ''}".strip()
        if subtype == "user-form":
            form = _message(body).get("formRequest")
            if isinstance(form, dict):
                return f"user-form: {form.get('title') or form.get('instruction') or ''}".strip()
        if subtype == "secret-request":
            secret = _message(body).get("secretRequest")
            if isinstance(secret, dict):
                return f"secret-request: {secret.get('label') or ''}".strip()
        return f"send {subtype}: {text}" if text else f"send {subtype}".strip()
    if kind == "event":
        event = _event(body)
        detail = event.get("action") or event.get("to") or event.get("automationName") or ""
        return f"event {subtype} {detail}".strip()
    if kind == "spend-initiation":
        return f"spend-initiation: {text or subtype}".strip()
    return f"{kind} {subtype}".strip()


def normalize_agent(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map one ``ListGrokBotAgents`` record to the public session shape."""
    kind = agent_kind(raw.get("kind"))
    member_ids = [str(value) for value in (raw.get("memberAgentIds") or [])]
    legacy_id = raw.get("legacyAgentId") or raw.get("agentId") or ""
    return {
        "id": str(raw.get("id") or ""),
        "legacy_id": str(legacy_id),
        "name": raw.get("name") or "",
        "description": raw.get("description") or "",
        "title": raw.get("title") or "",
        "kind": kind,
        "is_group": kind == KIND_ROOM,
        "harness": raw.get("harness") or "",
        "role": raw.get("role") or "",
        "visibility": raw.get("visibility") or "",
        "avatar_shape": raw.get("avatarShape") or "",
        "avatar_color": raw.get("avatarColor") or "",
        "created_at": epoch_to_iso(raw.get("createdAtMs")),
        "updated_at": epoch_to_iso(raw.get("updatedAtMs")),
        "member_agent_ids": member_ids,
        "member_count": len(member_ids),
        "viewer_session_id": raw.get("viewerSessionId") or "",
        "raw": raw,
    }


def normalize_entry(raw: Dict[str, Any], agent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Map one transcript entry to the public timeline/tool-call shape."""
    agent = agent or {}
    body = decode_body(raw)
    fallback_id = str(raw.get("entryId") or "")
    entry_id = body_entry_id(body or {}, fallback_id) or fallback_id
    legacy_id = str(agent.get("legacy_id") or "")
    omitted = bool(raw.get("bodyOmitted"))
    return {
        "id": f"{legacy_id}:{entry_id}" if legacy_id and entry_id else entry_id,
        "entry_id": entry_id,
        "seq": raw.get("seq"),
        "updated_seq": raw.get("updatedSeq"),
        "entry_kind": raw.get("entryKind") or (body or {}).get("kind") or "",
        "kind": (body or {}).get("kind") or "",
        "type": body_type(body or {}),
        "role": (body or {}).get("role") or "",
        "turn": body_turn_index(body or {}, entry_id),
        "timestamp_ms": (body or {}).get("timestampMs"),
        "timestamp": epoch_to_iso((body or {}).get("timestampMs")),
        "request_id": (body or {}).get("requestId") or "",
        "resolution": body_resolution(body or {}),
        "blob_hash": raw.get("blobHash") or "",
        "body_omitted": omitted,
        "text": entry_text(body or {}),
        "summary": entry_summary(body or {}, entry_id),
        "agent_id": str(agent.get("id") or ""),
        "legacy_id": legacy_id,
        "agent_name": agent.get("name") or "",
        "is_group": bool(agent.get("is_group")),
        "payload": body or {},
    }


def entry_sort_key(entry: Dict[str, Any]) -> int:
    """Return a monotonic key for merging entries across agents."""
    return as_int(entry.get("timestamp_ms")) or 0


def _text_preview(text: Any, limit: int = _TEXT_LIMIT) -> str:
    flattened = " ".join(str(text or "").split())
    if len(flattened) <= limit:
        return flattened
    return flattened[: limit - 3] + "..."


def effective_generation(generation: Any) -> int:
    """Return a transcript's generation as an integer identity.

    The service labels most transcripts (``{"generation": 1}``) but omits the
    field entirely for some agents and rooms. An unlabelled transcript is that
    agent's first and only epoch, so 1 is used as the identity while
    ``generation_reported`` records that the service never labelled it.
    """
    return generation if isinstance(generation, int) else 1


def conversation_rows(
    agent: Dict[str, Any],
    entries: List[Dict[str, Any]],
    generation: Optional[int],
) -> List[Dict[str, Any]]:
    """Summarize one agent's transcript as one row per generation."""
    if not entries:
        return []
    generation_value = effective_generation(generation)
    timestamps = [entry["timestamp_ms"] for entry in entries if entry.get("timestamp_ms")]
    turns = {entry.get("turn") for entry in entries if entry.get("turn") is not None}
    user_entries = [entry for entry in entries if entry.get("role") == "user"]
    return [
        {
            "id": f"{agent.get('legacy_id', '')}:{generation_value}",
            "agent_id": agent.get("id") or "",
            "legacy_id": agent.get("legacy_id") or "",
            "agent_name": agent.get("name") or "",
            "is_group": bool(agent.get("is_group")),
            "conversation_id": generation_value,
            "generation": generation_value,
            "generation_reported": isinstance(generation, int),
            "entry_count": len(entries),
            "message_count": sum(1 for entry in entries if entry.get("kind") == "message"),
            "send_count": sum(1 for entry in entries if entry.get("kind") == "send-message"),
            "event_count": sum(1 for entry in entries if entry.get("kind") == "event"),
            "turn_count": len(turns),
            "first_prompt": _text_preview(user_entries[-1].get("text")) if user_entries else "",
            "created_at": epoch_to_iso(min(timestamps)) if timestamps else "",
            "last_activity": epoch_to_iso(max(timestamps)) if timestamps else "",
        }
    ]


def turn_rows(agent: Dict[str, Any], entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group one agent's entries into turns, newest turn first."""
    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for entry in entries:
        turn = entry.get("turn")
        if turn is None:
            continue
        grouped.setdefault(turn, []).append(entry)

    rows = []
    for turn in sorted(grouped, reverse=True):
        members = grouped[turn]
        timestamps = [entry["timestamp_ms"] for entry in members if entry.get("timestamp_ms")]
        user_entries = [entry for entry in members if entry.get("role") == "user"]
        assistant_entries = [
            entry for entry in members if entry.get("role") == "assistant"
        ] or [entry for entry in members if entry.get("kind") == "send-message"]
        rows.append(
            {
                "id": f"{agent.get('legacy_id', '')}:t{turn}",
                "agent_id": agent.get("id") or "",
                "legacy_id": agent.get("legacy_id") or "",
                "agent_name": agent.get("name") or "",
                "is_group": bool(agent.get("is_group")),
                "turn": turn,
                "entry_count": len(members),
                "message_count": sum(1 for entry in members if entry.get("kind") == "message"),
                "send_count": sum(1 for entry in members if entry.get("kind") == "send-message"),
                "tool_call_count": sum(
                    1 for entry in members if entry.get("type") in TOOL_CALL_CARD_TYPES
                ),
                "has_approval": any(
                    entry.get("type") in ("local-tool-permission", "auto-review-approval")
                    for entry in members
                ),
                "started_at": epoch_to_iso(min(timestamps)) if timestamps else "",
                "ended_at": epoch_to_iso(max(timestamps)) if timestamps else "",
                "user_text": _text_preview(user_entries[-1].get("text")) if user_entries else "",
                "agent_text": _text_preview(assistant_entries[0].get("text"))
                if assistant_entries
                else "",
                "entry_ids": [entry.get("entry_id") or "" for entry in members],
            }
        )
    return rows


def tool_call_rows(agent: Dict[str, Any], entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Derive tool-call records from Grok Bot's interactive card entries."""
    rows = []
    for entry in entries:
        card_type = entry.get("type")
        if card_type not in TOOL_CALL_CARD_TYPES:
            continue
        payload = entry.get("payload") or {}
        message = _message(payload)
        ask = message.get("ask") if isinstance(message.get("ask"), dict) else {}
        form = message.get("formRequest") if isinstance(message.get("formRequest"), dict) else {}
        widget = message.get("widget") if isinstance(message.get("widget"), dict) else {}
        rows.append(
            {
                "id": entry["id"],
                "entry_id": entry.get("entry_id") or "",
                "agent_id": agent.get("id") or "",
                "legacy_id": agent.get("legacy_id") or "",
                "agent_name": agent.get("name") or "",
                "turn": entry.get("turn"),
                "timestamp": entry.get("timestamp"),
                "timestamp_ms": entry.get("timestamp_ms"),
                "source": "card",
                "tool": ask.get("action") or card_type,
                "card_type": card_type,
                "action": ask.get("action") or "",
                "target": ask.get("target") or form.get("domain") or widget.get("prompt") or "",
                "status": ask.get("status") or entry.get("resolution") or "",
                "title": message.get("title") or form.get("title") or "",
                "request_id": ask.get("requestId") or entry.get("request_id") or "",
                "summary": entry.get("summary") or "",
                "payload": payload,
            }
        )
    return rows


def approval_rows(agent: Dict[str, Any], entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build approval records from permission and auto-review card entries."""
    rows = []
    for entry in entries:
        if entry.get("type") not in ("local-tool-permission", "auto-review-approval"):
            continue
        payload = entry.get("payload") or {}
        message = _message(payload)
        ask = message.get("ask") if isinstance(message.get("ask"), dict) else {}
        approval = message.get("approval") if isinstance(message.get("approval"), dict) else {}
        rows.append(
            {
                "id": entry["id"],
                "entry_id": entry.get("entry_id") or "",
                "agent_id": agent.get("id") or "",
                "legacy_id": agent.get("legacy_id") or "",
                "agent_name": agent.get("name") or "",
                "turn": entry.get("turn"),
                "timestamp": entry.get("timestamp"),
                "timestamp_ms": entry.get("timestamp_ms"),
                "kind": entry.get("type") or "",
                "request_id": ask.get("requestId")
                or approval.get("requestId")
                or entry.get("request_id")
                or "",
                "action": ask.get("action") or entry.get("type") or "",
                "target": ask.get("target") or approval.get("summary") or "",
                "machine_id": ask.get("machineId") or "",
                "machine_label": ask.get("machineLabel") or "",
                "status": ask.get("status") or approval.get("status") or "",
                "resolved_value": payload.get("respondedValue") or "",
                "reason": approval.get("reason") or "",
                "surface": approval.get("surface") or "",
                "proposed_rule": approval.get("proposedRule") or "",
                "summary": entry.get("summary") or "",
                "payload": payload,
            }
        )
    return rows


def subagent_rows(
    agents: List[Dict[str, Any]],
    entries_by_agent: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Describe Grok Bot's subagent surface: room members and cursor-agent runs.

    ``entries_by_agent`` both supplies the cursor-agent cards and scopes the
    result to the agents the caller selected; ``agents`` is the full roster so
    room members resolve to their names even when only the room is selected.
    """
    by_legacy = {agent.get("legacy_id"): agent for agent in agents}
    rows: List[Dict[str, Any]] = []
    for agent in agents:
        legacy_id = agent.get("legacy_id") or ""
        if legacy_id not in entries_by_agent:
            continue
        if agent.get("is_group"):
            for member_id in agent.get("member_agent_ids") or []:
                member = by_legacy.get(member_id)
                rows.append(
                    {
                        "id": member_id,
                        "kind": "room-member",
                        "room_id": agent.get("id") or "",
                        "room_legacy_id": legacy_id,
                        "room_name": agent.get("name") or "",
                        "member_id": member_id,
                        "member_name": (member or {}).get("name") or "",
                        "member_kind": (member or {}).get("kind") or "",
                        "member_harness": (member or {}).get("harness") or "",
                        "agent_id": agent.get("id") or "",
                        "legacy_id": legacy_id,
                        "agent_name": agent.get("name") or "",
                        "timestamp": "",
                        "summary": f"member of {agent.get('name') or legacy_id}",
                    }
                )
        for entry in entries_by_agent.get(legacy_id, []):
            if entry.get("type") != "cursor-agent":
                continue
            message = _message(entry.get("payload") or {})
            rows.append(
                {
                    "id": entry["id"],
                    "kind": "cursor-agent",
                    "room_id": "",
                    "room_legacy_id": "",
                    "room_name": "",
                    "member_id": "",
                    "member_name": "",
                    "member_kind": "",
                    "member_harness": "",
                    "agent_id": agent.get("id") or "",
                    "legacy_id": legacy_id,
                    "agent_name": agent.get("name") or "",
                    "bc_id": message.get("bcId") or "",
                    "title": message.get("title") or "",
                    "turn": entry.get("turn"),
                    "timestamp": entry.get("timestamp"),
                    "timestamp_ms": entry.get("timestamp_ms"),
                    "entry_id": entry.get("entry_id") or "",
                    "summary": entry.get("summary") or "",
                    "payload": entry.get("payload") or {},
                }
            )
    return rows


def automation_rows(agent: Dict[str, Any], automations: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map ``ListGrokBotAgentAutomations`` records to the public shape."""
    rows = []
    for raw in automations:
        record = raw.get("recordJson")
        if isinstance(record, str):
            try:
                record = json.loads(record)
            except ValueError:
                record = {"raw": raw.get("recordJson")}
        if not isinstance(record, dict):
            record = {}
        automation_id = raw.get("automationId") or record.get("id") or ""
        runs = record.get("runs") if isinstance(record.get("runs"), list) else []
        trigger = record.get("trigger") if isinstance(record.get("trigger"), dict) else {}
        rows.append(
            {
                "id": automation_id,
                "automation_id": automation_id,
                "agent_id": agent.get("id") or "",
                "legacy_id": agent.get("legacy_id") or "",
                "agent_name": agent.get("name") or "",
                "name": record.get("name") or "",
                "prompt": record.get("prompt") or "",
                "trigger_type": trigger.get("type") or "",
                "schedule": record.get("schedule") or trigger.get("schedule") or "",
                "trigger_description": record.get("triggerDescription") or "",
                "is_enabled": record.get("isEnabled"),
                "provenance": record.get("provenance") or "",
                "created_at": epoch_to_iso(record.get("createdAt")),
                "last_run_at": epoch_to_iso(record.get("lastRunAt")),
                "next_run_at": epoch_to_iso(record.get("nextRunAt")),
                "run_count": len(runs),
                "file_path": record.get("filePath") or "",
                "record": record,
            }
        )
    return rows


def snippet_around(text: str, keyword: str, radius: int = 120) -> str:
    """Return a bounded window of ``text`` around the first keyword match."""
    flattened = " ".join(str(text or "").split())
    position = flattened.lower().find(keyword.lower())
    if position == -1:
        return flattened[: radius * 2]
    start = max(0, position - radius)
    end = min(len(flattened), position + len(keyword) + radius)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(flattened) else ""
    return f"{prefix}{flattened[start:end]}{suffix}"
