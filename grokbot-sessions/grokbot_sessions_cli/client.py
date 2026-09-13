"""Grok Bot Connect RPC client.

Grok Bot (an Electron app built on Anysphere's ``sand`` stack) keeps every
agent transcript in Cursor's cloud boxes, so the only complete source is the
live Connect RPC API at ``https://api2.cursor.sh/aiserver.v1.GrokBotService``.
Transcript calls require the agent's UUID ``legacyAgentId``; the numeric ``id``
returns HTTP 200 with an empty body, so every command resolves the UUID first.
"""
import base64
import random
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from . import parsers
from .config import get_config
from .secrets import AppAccount, account_at, account_labels, active_account

SERVICE_PATH = "aiserver.v1.GrokBotService"
TRANSCRIPT_PAGE_SIZE = 200
TRANSCRIPT_MAX_PAGES = 200
REQUEST_TIMEOUT_SECONDS = 45

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

SKILLS_UNAVAILABLE_NOTE = (
    "Grokbot exposes no agent-store entries through this API: "
    "aiserver.v1.GrokBotService/ListAgentStoreEntries returns HTTP 404 on "
    "Grok Bot 0.47.0, and the agent store lives in the cloud box rather than "
    "in this account's API surface. Returning an empty list rather than "
    "inventing skill records."
)

TODOS_UNAVAILABLE_NOTE = (
    "Grokbot has no todo/plan record: no transcript entry kind, card type, or "
    "API method carries a todo list. Returning an empty list rather than "
    "inventing todo records."
)

_PROJECT_NOTE = (
    "Grokbot has no working-directory-scoped project concept; each signed-in "
    "account scope is surfaced as one implicit project."
)


def masked_checksum(machine_id: str, seconds: Optional[int] = None) -> str:
    """Build the ``x-cursor-checksum`` header value.

    Reproduces the app bundle's ``l3e`` obfuscation of the 6-byte big-endian
    epoch-second counter, base64url-encoded without padding and suffixed with
    the machine id.
    """
    state = 165
    out = bytearray()
    secs = int(time.time()) if seconds is None else seconds
    raw = bytes((secs >> shift) & 255 for shift in (40, 32, 24, 16, 8, 0))
    for index, value in enumerate(raw):
        mixed = ((value ^ state) + index % 256) & 255
        out.append(mixed)
        state = mixed
    encoded = base64.urlsafe_b64encode(bytes(out)).decode("ascii").rstrip("=")
    return f"{encoded}{machine_id}"


def split_entry_id(entry_pk: str) -> Tuple[str, str]:
    """Split a ``<legacy agent id>:<entry id>`` transcript key."""
    if ":" not in entry_pk:
        raise ClientError(
            f"{entry_pk!r} is not a transcript entry id. Use the 'id' value from "
            "'grokbot-sessions timeline list' (form <agent legacy id>:<entry id>)."
        )
    legacy_id, entry_id = entry_pk.split(":", 1)
    return legacy_id, entry_id


class GrokBotClient:
    """Read-only client for the Grok Bot Connect RPC service."""

    def __init__(
        self,
        config=None,
        account_index: Optional[int] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        self.account_index = account_index
        self.base_url = self.config.api_base_url
        self.timeout = REQUEST_TIMEOUT_SECONDS
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self._account: Optional[AppAccount] = None

    # ==================== Credentials ====================

    @property
    def account(self) -> AppAccount:
        """The decrypted Grok Bot account used for every request."""
        if self._account is None:
            if self.account_index is None:
                self._account = active_account(self.config.app_dir)
            else:
                self._account = account_at(self.config.app_dir, self.account_index)
        return self._account

    @property
    def project_id(self) -> str:
        """The implicit project id for the account this client talks to."""
        return f"account-{self.account.index}"

    @property
    def cache_scope(self) -> str:
        """Identity of the data source, folded into every cache key.

        The shared ``@cached`` key hashes only the method name and arguments, so
        the endpoint and app directory have to travel as an argument. Without
        this, a roster cached from the real API would still be served after
        ``GROKBOT_SESSIONS_API_BASE`` or ``GROKBOT_SESSIONS_APP_DIR`` pointed
        somewhere else, hiding the override entirely.
        """
        account = self.account_index if self.account_index is not None else "active"
        return f"{self.base_url}|{self.config.app_dir}|{account}"

    def adopt_status(self) -> Dict[str, Any]:
        """Describe the adopted session without revealing credential material."""
        account = self.account
        return {
            "account": f"account-{account.index}",
            "active": account.active,
            "app_dir": str(self.config.app_dir),
            "api_base": self.base_url,
            "client_version": self.config.client_version,
        }

    # ==================== Transport ====================

    def _headers(self) -> Dict[str, str]:
        account = self.account
        return {
            "authorization": f"Bearer {account.access_token}",
            "content-type": "application/json",
            "connect-protocol-version": "1",
            "x-cursor-client-type": "sand",
            "x-cursor-client-version": self.config.client_version,
            "x-cursor-checksum": masked_checksum(account.machine_id),
            "x-ghost-mode": "false",
        }

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return max(0.0, min(retry_after, self.max_delay))
        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        return max(0.0, min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay))

    @staticmethod
    def _retry_after(response: requests.Response) -> Optional[float]:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    @staticmethod
    def _error_detail(response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return (response.text or "")[:400]
        if isinstance(payload, dict):
            parts = [str(payload.get("code") or ""), str(payload.get("message") or "")]
            details = payload.get("details")
            if isinstance(details, list):
                for detail in details:
                    if not isinstance(detail, dict):
                        continue
                    debug = detail.get("debug")
                    if isinstance(debug, dict) and isinstance(debug.get("details"), dict):
                        nested_detail = debug["details"].get("detail")
                        if nested_detail:
                            parts.append(str(nested_detail))
            text = " ".join(part for part in parts if part)
            return text[:400] or str(payload)[:400]
        return str(payload)[:400]

    def _call(self, method: str, body: Optional[Dict[str, Any]] = None, retry: bool = True) -> Dict[str, Any]:
        """POST one unary Connect RPC method and return its JSON body."""
        url = f"{self.base_url}/{SERVICE_PATH}/{method}"
        payload = body or {}
        max_attempts = (self.max_retries + 1) if retry else 1
        last_error: Optional[Exception] = None

        for attempt in range(max_attempts):
            try:
                response = requests.post(
                    url, headers=self._headers(), json=payload, timeout=self.timeout
                )
            except requests.exceptions.RequestException as exc:
                last_error = exc
                if retry and attempt < self.max_retries and isinstance(
                    exc,
                    (
                        requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout,
                        requests.exceptions.ChunkedEncodingError,
                    ),
                ):
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                raise ClientError(f"{method} request failed: {exc}") from exc

            if retry and attempt < self.max_retries and response.status_code in RETRYABLE_STATUS_CODES:
                time.sleep(self._calculate_retry_delay(attempt, self._retry_after(response)))
                continue

            if not response.ok:
                raise ClientError(
                    f"{method} failed with HTTP {response.status_code}: {self._error_detail(response)}"
                )

            if not response.content:
                # The service answers HTTP 200 with an empty body when a
                # transcript is requested by numeric agent id.
                return {}
            try:
                decoded = response.json()
            except ValueError as exc:
                raise ClientError(
                    f"{method} returned a non-JSON response: {(response.text or '')[:200]}"
                ) from exc
            if not isinstance(decoded, dict):
                raise ClientError(
                    f"{method} returned an unexpected JSON {type(decoded).__name__} root"
                )
            return decoded

        raise ClientError(f"{method} request failed after {max_attempts} attempts: {last_error}")

    # ==================== Agents ====================

    @cached
    def _agent_records(self, cache_scope: str) -> List[Dict[str, Any]]:
        payload = self._call("ListGrokBotAgents", {})
        agents = payload.get("agents")
        if not isinstance(agents, list):
            raise ClientError("ListGrokBotAgents returned no 'agents' list")
        return [parsers.normalize_agent(agent) for agent in agents]

    def list_agents(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """List Grok Bot agents (one per session)."""
        records = self._agent_records(self.cache_scope)
        return records[:limit] if limit is not None else records

    def resolve_agent(self, identifier: str) -> Dict[str, Any]:
        """Resolve a numeric id, legacy UUID, or name to one agent record."""
        records = self._agent_records(self.cache_scope)
        wanted = str(identifier).strip()
        for record in records:
            if record["id"] == wanted:
                return record
        lowered = wanted.lower()
        for record in records:
            if record["legacy_id"].lower() == lowered:
                return record
        for record in records:
            if (record["name"] or "").lower() == lowered:
                return record
        available = ", ".join(
            f"{record['name']} ({record['id']}/{record['legacy_id']})" for record in records
        )
        raise ClientError(f"No Grok Bot agent matches {identifier!r}. Available: {available}")

    def resolve_agents(self, identifiers: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        """Resolve ``--agent`` values, or return every agent when none are given."""
        values = [value for value in (identifiers or []) if value]
        if not values:
            return self._agent_records(self.cache_scope)
        return [self.resolve_agent(value) for value in values]

    # ==================== Transcripts ====================

    @cached
    def _transcript_page(
        self,
        cache_scope: str,
        legacy_id: str,
        limit: int,
        before_seq: Optional[int],
        generation: Optional[int],
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"agentId": legacy_id, "limit": limit}
        if before_seq is not None:
            body["beforeSeq"] = before_seq
        if generation is not None:
            body["generation"] = generation
        return self._call("ListGrokBotTranscriptEntries", body)

    @cached
    def transcript(
        self, cache_scope: str, legacy_id: str, limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """Page the transcript newest-to-oldest, preserving server order.

        ``seq`` is a commit sequence shared by several entries and arrives as a
        protobuf-es int64 *string*. ``beforeSeq`` is exclusive, so a page
        boundary inside a shared ``seq`` bucket would drop entries; each page
        therefore steps one past the numeric minimum and duplicates are removed
        by entry id. Ordering is always the server's own — never re-sorted.

        A small ``limit`` is passed straight to the API as the page size, so
        ``--limit 1`` asks the server for one entry rather than downloading the
        transcript and slicing it.
        """
        page_size = TRANSCRIPT_PAGE_SIZE
        if limit is not None:
            page_size = max(1, min(TRANSCRIPT_PAGE_SIZE, limit))
        collected: List[Dict[str, Any]] = []
        seen: set = set()
        before_seq: Optional[int] = None
        generation: Optional[int] = None
        pages = 0

        while True:
            page = self._transcript_page(cache_scope, legacy_id, page_size, before_seq, generation)
            entries = page.get("entries")
            if not isinstance(entries, list):
                entries = []
            page_generation = page.get("generation")
            if isinstance(page_generation, int):
                generation = page_generation

            added = 0
            for entry in entries:
                entry_id = entry.get("entryId")
                if entry_id:
                    if entry_id in seen:
                        continue
                    seen.add(entry_id)
                collected.append(entry)
                added += 1
            pages += 1

            if limit is not None and len(collected) >= limit:
                collected = collected[:limit]
                break
            if (
                not entries
                or len(entries) < page_size
                or pages >= TRANSCRIPT_MAX_PAGES
                or added == 0
            ):
                break
            numeric_seqs = [
                value
                for value in (parsers.as_int(entry.get("seq")) for entry in entries)
                if value is not None
            ]
            if not numeric_seqs:
                break
            before_seq = min(numeric_seqs) + 1

        return {
            "legacy_id": legacy_id,
            "generation": generation,
            "entries": collected,
            "pages": pages,
        }

    def entries_for(
        self, agent: Dict[str, Any], limit: Optional[int] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """Decoded, normalized transcript entries for one agent."""
        result = self.transcript(self.cache_scope, agent["legacy_id"], limit)
        normalized = [parsers.normalize_entry(raw, agent) for raw in result["entries"]]
        return normalized, result["generation"]

    # ==================== Sessions and projects ====================

    def list_sessions(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        return self.list_agents(limit)

    def get_session(self, identifier: str) -> Dict[str, Any]:
        return self.resolve_agent(identifier)

    def list_projects(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """One implicit project per Grok Bot account scope."""
        rows = []
        for label in account_labels(self.config.app_dir):
            rows.append(
                {
                    "id": label["id"],
                    "name": f"Grok Bot {label['id']}",
                    "kind": "implicit",
                    "source": "sand-secrets.json",
                    "account_index": label["index"],
                    "active": label["active"],
                    "has_token": label["has_token"],
                    "has_profile": label["has_profile"],
                    "path": str(self.config.app_dir),
                    "cwd": "",
                    "note": _PROJECT_NOTE,
                }
            )
        return rows[:limit] if limit is not None else rows

    def get_project(self, identifier: str) -> Dict[str, Any]:
        rows = self.list_projects()
        for row in rows:
            if identifier in (row["id"], row["name"]):
                return row
        available = ", ".join(row["id"] for row in rows)
        raise ClientError(f"No project matches {identifier!r}. Available: {available}")

    # ==================== Conversations ====================

    def list_conversations(
        self, agents: List[Dict[str, Any]], limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for agent in agents:
            entries, generation = self.entries_for(agent)
            rows.extend(parsers.conversation_rows(agent, entries, generation))
            if limit is not None and len(rows) >= limit:
                return rows[:limit]
        return rows

    def get_conversation(self, conversation_id: str) -> Dict[str, Any]:
        if ":" not in conversation_id:
            raise ClientError(
                f"{conversation_id!r} is not a conversation id. Use the 'id' value "
                "from 'grokbot-sessions conversations list' (form <agent legacy id>:<generation>)."
            )
        legacy_id, raw_generation = conversation_id.split(":", 1)
        try:
            generation = int(raw_generation)
        except ValueError as exc:
            raise ClientError(
                f"Conversation id {conversation_id!r} has a non-numeric generation "
                f"{raw_generation!r}."
            ) from exc
        agent = self.resolve_agent(legacy_id)
        entries, reported_generation = self.entries_for(agent)
        rows = parsers.conversation_rows(agent, entries, reported_generation)
        row = next((item for item in rows if item["generation"] == generation), None)
        if row is None:
            effective = parsers.effective_generation(reported_generation)
            raise ClientError(
                f"Agent {agent['name']} has no conversation generation {generation} "
                f"(this transcript is generation {effective})."
            )
        detail = dict(row)
        detail["entries"] = entries
        return detail

    # ==================== Turns ====================

    def list_turns(
        self, agents: List[Dict[str, Any]], limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for agent in agents:
            entries, _generation = self.entries_for(agent)
            rows.extend(parsers.turn_rows(agent, entries))
            if limit is not None and len(rows) >= limit:
                return rows[:limit]
        return rows

    def get_turn(self, turn_id: str) -> Dict[str, Any]:
        if ":" not in turn_id:
            raise ClientError(
                f"{turn_id!r} is not a turn id. Use the 'id' value from "
                "'grokbot-sessions turns list' (form <agent legacy id>:t<turn>)."
            )
        legacy_id, raw_turn = turn_id.split(":", 1)
        if not raw_turn.startswith("t") or not raw_turn[1:].isdigit():
            raise ClientError(f"Turn id {turn_id!r} must end with 't<turn>'.")
        turn = int(raw_turn[1:])
        agent = self.resolve_agent(legacy_id)
        entries, _generation = self.entries_for(agent)
        row = next(
            (item for item in parsers.turn_rows(agent, entries) if item["turn"] == turn),
            None,
        )
        if row is None:
            raise ClientError(f"Agent {agent['name']} has no turn {turn}.")
        detail = dict(row)
        detail["entries"] = sorted(
            (entry for entry in entries if entry.get("turn") == turn),
            key=parsers.entry_sort_key,
        )
        return detail

    # ==================== Timeline ====================

    def list_timeline(
        self,
        agents: List[Dict[str, Any]],
        limit: Optional[int] = None,
        merge: bool = False,
    ) -> List[Dict[str, Any]]:
        """Transcript entries in server order, optionally merged newest-first.

        For the unmerged (per-agent) view the remaining ``--limit`` is pushed
        into the transcript paging request, so a small limit does not download
        the whole transcript. Merging must read every selected agent before it
        can order them by timestamp.
        """
        rows: List[Dict[str, Any]] = []
        for agent in agents:
            per_agent: Optional[int] = None
            if not merge and limit is not None:
                per_agent = max(0, limit - len(rows))
                if per_agent == 0:
                    break
            entries, _generation = self.entries_for(agent, per_agent)
            rows.extend(entries)
            if not merge and limit is not None and len(rows) >= limit:
                return rows[:limit]
        if merge:
            rows.sort(key=parsers.entry_sort_key, reverse=True)
        return rows[:limit] if limit is not None else rows

    def get_entry(self, entry_pk: str) -> Dict[str, Any]:
        legacy_id, entry_id = split_entry_id(entry_pk)
        agent = self.resolve_agent(legacy_id)
        entries, _generation = self.entries_for(agent)
        row = next((entry for entry in entries if entry["entry_id"] == entry_id), None)
        if row is None:
            raise ClientError(f"Transcript entry not found in agent {agent['name']}: {entry_pk}")
        return row

    # ==================== Tool calls and approvals ====================

    def list_tool_calls(
        self, agents: List[Dict[str, Any]], limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for agent in agents:
            entries, _generation = self.entries_for(agent)
            rows.extend(parsers.tool_call_rows(agent, entries))
            if limit is not None and len(rows) >= limit:
                return rows[:limit]
        return rows

    def get_tool_call(self, tool_call_id: str) -> Dict[str, Any]:
        for row in self.list_tool_calls(self._agent_records(self.cache_scope)):
            if tool_call_id in (row["id"], row["entry_id"]):
                return row
        raise ClientError(f"Tool call not found: {tool_call_id}")

    def list_approvals(
        self, agents: List[Dict[str, Any]], limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for agent in agents:
            entries, _generation = self.entries_for(agent)
            rows.extend(parsers.approval_rows(agent, entries))
            if limit is not None and len(rows) >= limit:
                return rows[:limit]
        return rows

    def get_approval(self, approval_id: str) -> Dict[str, Any]:
        for row in self.list_approvals(self._agent_records(self.cache_scope)):
            if approval_id in (row["id"], row["entry_id"], row["request_id"]):
                return row
        raise ClientError(f"Approval not found: {approval_id}")

    # ==================== Subagent activity ====================

    def list_subagent_activity(
        self, agents: List[Dict[str, Any]], limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        roster = self._agent_records(self.cache_scope)
        rows: List[Dict[str, Any]] = []
        for agent in agents:
            entries, _generation = self.entries_for(agent)
            rows.extend(parsers.subagent_rows(roster, {agent["legacy_id"]: entries}))
            if limit is not None and len(rows) >= limit:
                return rows[:limit]
        return rows

    def get_subagent(self, identifier: str) -> Dict[str, Any]:
        for row in self.list_subagent_activity(self._agent_records(self.cache_scope)):
            if identifier in (row["id"], row.get("entry_id"), row.get("bc_id")):
                detail = dict(row)
                if row["kind"] == "room-member":
                    member = self.resolve_agent(row["member_id"])
                    entries, generation = self.entries_for(member)
                    conversations = parsers.conversation_rows(member, entries, generation)
                    detail["member"] = member
                    detail["conversation"] = conversations[0] if conversations else {}
                return detail
        raise ClientError(f"Subagent activity not found: {identifier}")

    # ==================== Automations ====================

    @cached
    def _automations(self, cache_scope: str, legacy_id: str) -> Dict[str, Any]:
        return self._call("ListGrokBotAgentAutomations", {"agentId": legacy_id})

    def list_automations(
        self, agents: List[Dict[str, Any]], limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for agent in agents:
            payload = self._automations(self.cache_scope, agent["legacy_id"])
            automations = payload.get("automations")
            if not isinstance(automations, list):
                automations = []
            rows.extend(parsers.automation_rows(agent, automations))
            if limit is not None and len(rows) >= limit:
                return rows[:limit]
        return rows

    def get_automation(self, automation_id: str) -> Dict[str, Any]:
        for row in self.list_automations(self._agent_records(self.cache_scope)):
            if automation_id in (row["automation_id"], row["id"]):
                return row
        raise ClientError(f"Automation not found: {automation_id}")

    # ==================== Unsupported surfaces ====================

    def list_skills(self) -> Tuple[List[Dict[str, Any]], str]:
        """Grokbot exposes no agent-store entries through this API."""
        return [], SKILLS_UNAVAILABLE_NOTE

    def list_todos(self) -> Tuple[List[Dict[str, Any]], str]:
        """Grokbot records no todo items."""
        return [], TODOS_UNAVAILABLE_NOTE

    # ==================== Search ====================

    def search(
        self,
        query: str,
        agents: List[Dict[str, Any]],
        limit: Optional[int] = None,
        max_matches: int = 5,
    ) -> List[Dict[str, Any]]:
        """Client-side keyword search across decoded transcript entries."""
        needle = query.lower()
        results: List[Dict[str, Any]] = []
        for agent in agents:
            entries, _generation = self.entries_for(agent)
            matches: List[Dict[str, Any]] = []
            for entry in entries:
                text = entry.get("text") or ""
                summary = entry.get("summary") or ""
                occurrences = text.lower().count(needle) if needle else 0
                if needle not in text.lower() and needle not in summary.lower():
                    continue
                matches.append(
                    {
                        "entry_id": entry.get("entry_id") or "",
                        "id": entry.get("id") or "",
                        "kind": entry.get("kind") or "",
                        "type": entry.get("type") or "",
                        "role": entry.get("role") or "",
                        "turn": entry.get("turn"),
                        "timestamp": entry.get("timestamp") or "",
                        "count": occurrences,
                        "snippet": parsers.snippet_around(text or summary, needle),
                    }
                )
            if not matches:
                continue
            timestamps = [entry["timestamp_ms"] for entry in entries if entry.get("timestamp_ms")]
            results.append(
                {
                    "id": agent["id"],
                    "session_id": agent["id"],
                    "legacy_id": agent["legacy_id"],
                    "name": agent["name"],
                    "kind": agent["kind"],
                    "project": self.project_id,
                    "match_count": sum(match["count"] for match in matches),
                    "matches": matches[:max_matches],
                    "created_at": agent["created_at"],
                    "model": "",
                    "origin": agent["kind"].lower(),
                    "last_activity": parsers.epoch_to_iso(max(timestamps))
                    if timestamps
                    else agent["updated_at"],
                }
            )
            if limit is not None and len(results) >= limit:
                break
        return results


_client: Optional[GrokBotClient] = None


def get_client() -> GrokBotClient:
    """Get or create the global Grok Bot client instance."""
    global _client
    if _client is None:
        _client = GrokBotClient()
    return _client
