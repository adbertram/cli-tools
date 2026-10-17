"""Query layer over the Hermes Agent state store.

Every method is read-only. Nothing here writes to `state.db`, executes the
`hermes` binary, or returns raw transcript text: message bodies always leave
this module as bounded, redacted previews.
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple

from cli_tools_shared.exceptions import ClientError

from .config import Config, get_config
from .models import (
    Conversation,
    Project,
    SearchMatch,
    Session,
    SessionSummary,
    Skill,
    SubagentActivity,
    TimelineEvent,
    Todo,
    ToolCall,
    Turn,
)
from .parsers import (
    DEFAULT_MAX_CHARS,
    DELEGATE_TOOL,
    NO_WORKSPACE,
    SKILL_TOOLS,
    TODO_TOOL,
    effective_tokens,
    extract_todos,
    parse_tool_calls,
    preview,
    project_name,
    segment_conversations,
    segment_turns,
    skill_name_from_result,
    slash_command_name,
    to_iso,
    tool_status,
    workspace_key,
)
from .state import StateStore

# Session rows are small; message rows carry transcript text, so only the
# columns the CLI actually derives from are ever read.
SESSION_COLUMNS = (
    "id", "source", "user_id", "model", "parent_session_id", "started_at",
    "ended_at", "end_reason", "message_count", "tool_call_count", "api_call_count",
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    "reasoning_tokens", "estimated_cost_usd", "cwd", "title", "title_source",
    "profile_name", "chat_type", "archived", "hidden", "pinned",
    "last_activity_at", "system_prompt_hash", "tool_names",
)
MESSAGE_COLUMNS = (
    "id", "session_id", "role", "content", "tool_call_id", "tool_calls",
    "tool_name", "timestamp", "token_count", "finish_reason", "compacted",
    "_compressed_summary", "active", "display_kind",
)

# How many messages one session contributes to a derived view. The window is
# anchored to the NEWEST messages, never the oldest, so the current state of a
# long-running session is always in view; `Session.message_window_truncated`
# reports when older messages fell outside it.
MESSAGE_WINDOW = 5_000
# How many sessions a message-derived list may open while filling `--limit`.
MAX_SCANNED_SESSIONS = 500
# How far back a latest-state lookup scans for its newest matching tool call.
LATEST_CALL_SCAN = 200
# Upper bound on the distinct tool names one session reports.
MAX_TOOL_NAMES = 200


class SessionNotFound(ClientError):
    """Raised when a session id or title does not resolve."""


class HermesSessionsClient:
    """Read-only query interface over the Hermes state store."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self.store = StateStore(self.config.state_db_path)
        self._session_columns: Optional[List[str]] = None
        self._message_columns: Optional[List[str]] = None

    # ---------------------------------------------------------------- schema

    def _columns(self, table: str, wanted: Sequence[str]) -> List[str]:
        """Intersect the wanted columns with the ones this store actually has.

        The Hermes schema gains columns over time. Selecting the intersection
        keeps one query working across schema versions without branching on a
        version number.
        """
        available = set(self.store.columns(table))
        if not available:
            raise ClientError(f"Hermes state store has no '{table}' table")
        selected = [name for name in wanted if name in available]
        if not selected:
            raise ClientError(f"Hermes '{table}' table exposes none of the expected columns")
        return selected

    def _session_select(self) -> str:
        if self._session_columns is None:
            self._session_columns = self._columns("sessions", SESSION_COLUMNS)
        return ", ".join(f'"{name}"' for name in self._session_columns)

    def _message_select(self) -> str:
        if self._message_columns is None:
            self._message_columns = self._columns("messages", MESSAGE_COLUMNS)
        return ", ".join(f'"{name}"' for name in self._message_columns)

    # ------------------------------------------------------------ primitives

    @staticmethod
    def _last_activity(row: Dict[str, Any]) -> Optional[float]:
        """Most recent activity epoch for a session row.

        Hermes records `last_activity_at` only once a session has been touched
        after creation, so the documented order is last activity, then end, then
        start.
        """
        for key in ("last_activity_at", "ended_at", "started_at"):
            value = row.get(key)
            if value is not None:
                return value
        return None

    @staticmethod
    def _workspace_clause(keys: Sequence[Optional[str]], column: str = "cwd") -> Tuple[str, List[Any]]:
        """SQL predicate matching sessions whose workspace is one of `keys`.

        Comparison goes through the registered `hs_workspace` function so a
        NULL, empty, and whitespace-only `cwd` all match the same bucket that
        `projects list` counted them under.
        """
        if len(keys) == 1:
            return f"hs_workspace({column}) IS ?", [keys[0]]
        placeholders = ", ".join("?" for _ in keys)
        return f"hs_workspace({column}) IN ({placeholders})", list(keys)

    def _session_rows(
        self,
        *,
        project: Optional[str] = None,
        session_ids: Optional[Sequence[str]] = None,
        source: Optional[str] = None,
        since: Optional[float] = None,
        date_bounds: Optional[Tuple[float, float]] = None,
        include_subagents: bool = True,
        parent_session: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Fetch session rows newest-first under the given scope."""
        clauses: List[str] = []
        params: List[Any] = []

        if project is not None:
            clause, values = self._workspace_clause(self.resolve_project_cwds(project))
            clauses.append(clause)
            params.extend(values)
        if session_ids is not None:
            if not session_ids:
                return []
            placeholders = ", ".join("?" for _ in session_ids)
            clauses.append(f"id IN ({placeholders})")
            params.extend(session_ids)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if parent_session:
            clauses.append("parent_session_id = ?")
            params.append(parent_session)
        if not include_subagents:
            clauses.append("(source IS NULL OR source != 'subagent')")
        if since is not None:
            clauses.append("started_at >= ?")
            params.append(since)
        if date_bounds is not None:
            clauses.append("started_at >= ? AND started_at < ?")
            params.extend(date_bounds)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT {self._session_select()} FROM sessions {where} "
            "ORDER BY started_at DESC, id DESC LIMIT ?"
        )
        params.append(max(0, limit))
        return self.store.query(sql, params)

    def _has_message_column(self, name: str) -> bool:
        """Whether this store's `messages` table carries a column."""
        if self._message_columns is None:
            self._message_select()
        return name in (self._message_columns or [])

    def _message_total(self, session_id: str) -> int:
        """Exact message count for one session."""
        rows = self.store.query(
            "SELECT COUNT(*) AS total FROM messages WHERE session_id = ?", (session_id,)
        )
        return rows[0]["total"] if rows else 0

    def _message_window(
        self, session_id: str, window: int = MESSAGE_WINDOW
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """The NEWEST `window` messages of a session, returned in write order.

        Reading the newest end is what makes a long session usable: the oldest
        `window` messages describe a state the session left behind hours ago,
        while the newest describe what it is doing now. The boolean says
        whether older messages exist outside the window, so no caller can
        mistake a windowed view for a complete one.
        """
        size = max(1, window)
        sql = (
            f"SELECT {self._message_select()} FROM messages "
            "WHERE session_id = ? ORDER BY id DESC LIMIT ?"
        )
        rows = self.store.query(sql, (session_id, size))
        rows.reverse()
        return rows, len(rows) == size and self._message_total(session_id) > size

    def _count_messages(self, session_id: str, clause: str, params: Sequence[Any] = ()) -> int:
        sql = f"SELECT COUNT(*) AS total FROM messages WHERE session_id = ? AND {clause}"
        rows = self.store.query(sql, (session_id, *params))
        return rows[0]["total"] if rows else 0

    def _first_message(self, session_id: str) -> Optional[Dict[str, Any]]:
        rows = self.store.query(
            f"SELECT {self._message_select()} FROM messages "
            "WHERE session_id = ? ORDER BY id ASC LIMIT 1",
            (session_id,),
        )
        return rows[0] if rows else None

    def _window_start_indices(
        self, session_id: str, rows: List[Dict[str, Any]]
    ) -> Tuple[int, int]:
        """Global turn and conversation numbers for the window's first segment.

        A windowed view still numbers its rows the way the whole session does,
        so `turns get <session>:<n>` means the same thing whether or not the
        window covered the session start.
        """
        if not rows:
            return 1, 1
        first_id = rows[0]["id"]
        if self._count_messages(session_id, "id < ?", (first_id,)) == 0:
            return 1, 1

        opener = self._first_message(session_id) or {}
        summary_column = self._has_message_column("_compressed_summary")

        prior_users = self._count_messages(session_id, "role = 'user' AND id < ?", (first_id,))
        open_turn = prior_users + (0 if opener.get("role") == "user" else 1)
        turn_start = open_turn + 1 if rows[0].get("role") == "user" else open_turn

        if summary_column:
            prior_boundaries = self._count_messages(
                session_id, '"_compressed_summary" = 1 AND id < ?', (first_id,)
            )
        else:
            prior_boundaries = 0
        open_conversation = prior_boundaries + (0 if opener.get("_compressed_summary") else 1)
        conversation_start = (
            open_conversation + 1 if rows[0].get("_compressed_summary") else open_conversation
        )
        return max(1, turn_start), max(1, conversation_start)

    def _session_context(self, session_id: str) -> Tuple[List[Dict[str, Any]], bool, int, int]:
        """Window of messages plus the global indices its first segments carry."""
        rows, truncated = self._message_window(session_id)
        turn_start, conversation_start = self._window_start_indices(session_id, rows)
        return rows, truncated, turn_start, conversation_start

    # --------------------------------------------------------------- projects

    def _project_index(self) -> Dict[str, Dict[str, Any]]:
        """Aggregate every session into its workspace bucket."""
        sql = (
            "SELECT hs_workspace(cwd) AS workspace, source, COUNT(*) AS session_count, "
            "SUM(COALESCE(message_count, 0)) AS message_count, "
            "SUM(COALESCE(tool_call_count, 0)) AS tool_call_count, "
            "MIN(started_at) AS first_activity, "
            "MAX(COALESCE(ended_at, started_at)) AS last_activity "
            "FROM sessions GROUP BY hs_workspace(cwd), source"
        )
        buckets: Dict[str, Dict[str, Any]] = {}
        for row in self.store.iter_query(sql):
            workspace = row.get("workspace")
            key = workspace if workspace is not None else NO_WORKSPACE
            bucket = buckets.setdefault(
                key,
                {
                    "name": project_name(workspace),
                    "full_path": workspace,
                    "workspace": workspace,
                    "session_count": 0,
                    "subagent_session_count": 0,
                    "message_count": 0,
                    "tool_call_count": 0,
                    "first_activity": None,
                    "last_activity": None,
                },
            )
            bucket["session_count"] += row["session_count"]
            if row.get("source") == "subagent":
                bucket["subagent_session_count"] += row["session_count"]
            bucket["message_count"] += row["message_count"] or 0
            bucket["tool_call_count"] += row["tool_call_count"] or 0
            for field, better in (("first_activity", min), ("last_activity", max)):
                value = row.get(field)
                if value is None:
                    continue
                current = bucket[field]
                bucket[field] = value if current is None else better(current, value)
        return buckets

    def list_projects(self, limit: int = 100) -> List[Project]:
        """Every workspace that has Hermes sessions, busiest-recent first."""
        buckets = self._project_index().values()
        ordered = sorted(buckets, key=lambda row: (row["last_activity"] or 0), reverse=True)
        return [self._project(row) for row in ordered[: max(0, limit)]]

    @staticmethod
    def _project(row: Dict[str, Any]) -> Project:
        return Project(
            name=row["name"],
            full_path=row["full_path"],
            session_count=row["session_count"],
            subagent_session_count=row["subagent_session_count"],
            message_count=row["message_count"],
            tool_call_count=row["tool_call_count"],
            first_activity=to_iso(row["first_activity"]),
            last_activity=to_iso(row["last_activity"]),
        )

    def resolve_project_cwds(self, name: str) -> List[Optional[str]]:
        """Resolve a project name, absolute path, or bucket label to its cwds.

        Raises:
            ClientError: when the name is unknown, or when several distinct
                workspaces share the requested basename. Ambiguity is reported
                with every candidate path instead of silently picking one.
        """
        buckets = self._project_index()
        wanted = (name or "").strip()
        if not wanted:
            raise ClientError("project name is required")

        if wanted == NO_WORKSPACE:
            if NO_WORKSPACE not in buckets:
                raise ClientError("No Hermes sessions have an empty workspace")
            return [None]

        trimmed = workspace_key(wanted) or wanted
        if trimmed in buckets:
            return [buckets[trimmed]["workspace"]]

        matches = [key for key, row in buckets.items() if row["name"] == trimmed]
        if not matches:
            raise ClientError(
                f"Unknown project {name!r}. Use `hermes-sessions projects list` to see available projects."
            )
        if len(matches) > 1:
            candidates = ", ".join(sorted(matches))
            raise ClientError(
                f"Project name {name!r} is ambiguous across {len(matches)} workspaces; "
                f"pass the absolute path instead: {candidates}"
            )
        return [buckets[matches[0]]["workspace"]]

    def get_project(self, name: str) -> Project:
        """Details for one workspace."""
        cwds = self.resolve_project_cwds(name)
        buckets = self._project_index()
        key = NO_WORKSPACE if cwds == [None] else cwds[0]
        return self._project(buckets[key])

    # --------------------------------------------------------------- sessions

    def _summary(self, row: Dict[str, Any], *, subagent_count: Optional[int] = None,
                 turn_count: Optional[int] = None,
                 conversation_count: Optional[int] = None) -> SessionSummary:
        return SessionSummary(
            id=row["id"],
            title=row.get("title"),
            title_source=row.get("title_source"),
            project=project_name(row.get("cwd")),
            project_path=row.get("cwd"),
            source=row.get("source") or "unknown",
            profile=row.get("profile_name"),
            model=row.get("model"),
            created_at=to_iso(row.get("started_at")) or "",
            last_activity=to_iso(self._last_activity(row)) or "",
            ended_at=to_iso(row.get("ended_at")),
            end_reason=row.get("end_reason"),
            parent_session=row.get("parent_session_id"),
            is_subagent=row.get("source") == "subagent",
            subagent_count=subagent_count if subagent_count is not None else self._child_count(row["id"]),
            message_count=row.get("message_count") or 0,
            tool_call_count=row.get("tool_call_count") or 0,
            api_call_count=row.get("api_call_count") or 0,
            turn_count=turn_count or 0,
            conversation_count=conversation_count or 1,
            archived=bool(row.get("archived")),
            hidden=bool(row.get("hidden")),
            pinned=bool(row.get("pinned")),
            input_tokens=row.get("input_tokens") or 0,
            output_tokens=row.get("output_tokens") or 0,
            cache_read_tokens=row.get("cache_read_tokens") or 0,
            cache_write_tokens=row.get("cache_write_tokens") or 0,
            reasoning_tokens=row.get("reasoning_tokens") or 0,
            effective_tokens=effective_tokens(row),
            estimated_cost_usd=row.get("estimated_cost_usd") or 0.0,
        )

    def _child_count(self, session_id: str) -> int:
        rows = self.store.query(
            "SELECT COUNT(*) AS total FROM sessions WHERE parent_session_id = ?",
            (session_id,),
        )
        return rows[0]["total"] if rows else 0

    def list_sessions(
        self,
        project: Optional[str] = None,
        limit: int = 100,
        since: Optional[float] = None,
        date_bounds: Optional[Tuple[float, float]] = None,
        source: Optional[str] = None,
        include_subagents: bool = True,
        session_ids: Optional[Sequence[str]] = None,
    ) -> List[SessionSummary]:
        """Sessions newest-first under the given scope."""
        rows = self._session_rows(
            project=project,
            session_ids=session_ids,
            source=source,
            since=since,
            date_bounds=date_bounds,
            include_subagents=include_subagents,
            limit=limit,
        )
        return [self._summary(row) for row in rows]

    def _session_row(self, session_id: str) -> Dict[str, Any]:
        rows = self.store.query(
            f"SELECT {self._session_select()} FROM sessions WHERE id = ? LIMIT 1",
            (session_id,),
        )
        if not rows:
            raise SessionNotFound(f"Session {session_id!r} not found")
        return rows[0]

    def resolve_session_id(self, value: str, project: Optional[str] = None) -> str:
        """Resolve a session id or title to an exact session id.

        An exact id always wins. Otherwise the value is matched against session
        titles case-insensitively; several matches are reported as an error with
        every candidate id, never silently reduced to one.
        """
        wanted = (value or "").strip()
        if not wanted:
            raise ClientError("a session id or title is required")

        exact = self.store.query("SELECT id FROM sessions WHERE id = ? LIMIT 1", (wanted,))
        if exact:
            return exact[0]["id"]

        params: List[Any] = [wanted]
        clause = ""
        if project is not None:
            predicate, values = self._workspace_clause(self.resolve_project_cwds(project))
            clause = f" AND {predicate}"
            params.extend(values)
        # `hs_casefold` applies full Unicode case folding. SQLite's own
        # `lower()` folds ASCII only, so a title such as "über session" would
        # never match "ÜBER SESSION". The LIMIT keeps an ambiguous title from
        # materializing an unbounded candidate set.
        rows = self.store.query(
            "SELECT id, title FROM sessions WHERE title IS NOT NULL "
            f"AND hs_casefold(title) = hs_casefold(?){clause} "
            "ORDER BY started_at DESC LIMIT 25",
            params,
        )
        if not rows:
            raise SessionNotFound(f"No session with id or title {value!r}")
        if len(rows) > 1:
            ids = ", ".join(row["id"] for row in rows)
            raise ClientError(
                f"Session title {value!r} matches {len(rows)} sessions; "
                f"pass the session id instead: {ids}"
            )
        return rows[0]["id"]

    def _structural_counts(self, session_id: str) -> Dict[str, int]:
        """Exact whole-session counts, computed in SQL rather than from a window.

        Turn and conversation totals follow the same segmentation rules the row
        builders use: a turn opens at each user message (plus a leading turn
        when the session does not start with one), and a conversation opens at
        each compaction summary (the first message being a summary does not
        create an empty one).
        """
        total = self._message_total(session_id)
        if total == 0:
            return {
                "turn_count": 0, "conversation_count": 1, "error_count": 0,
                "skill_count": 0, "compacted_message_count": 0,
            }

        opener = self._first_message(session_id) or {}
        users = self._count_messages(session_id, "role = 'user'")
        turn_count = users + (0 if opener.get("role") == "user" else 1)

        if self._has_message_column("_compressed_summary"):
            boundaries = self._count_messages(session_id, '"_compressed_summary" = 1')
            conversation_count = boundaries + (0 if opener.get("_compressed_summary") else 1)
        else:
            conversation_count = 1

        errors = self._count_messages(
            session_id, "role = 'tool' AND hs_tool_status(content) = 'error'"
        )
        skills = self.store.query(
            "SELECT COALESCE(SUM(hs_skill_hits(role, content, tool_calls)), 0) AS total "
            "FROM messages WHERE session_id = ?",
            (session_id,),
        )
        compacted = (
            self._count_messages(session_id, "compacted = 1")
            if self._has_message_column("compacted")
            else 0
        )
        return {
            "turn_count": turn_count,
            "conversation_count": max(1, conversation_count),
            "error_count": errors,
            "skill_count": int(skills[0]["total"]) if skills else 0,
            "compacted_message_count": compacted,
        }

    def _edge_message(self, session_id: str, clause: str, order: str) -> Optional[Dict[str, Any]]:
        rows = self.store.query(
            f"SELECT {self._message_select()} FROM messages "
            f"WHERE session_id = ? AND {clause} ORDER BY id {order} LIMIT 1",
            (session_id,),
        )
        return rows[0] if rows else None

    def get_session(self, session_id: str, max_chars: int = DEFAULT_MAX_CHARS) -> Session:
        """Full metadata for one session. Never returns message bodies.

        Every count here is exact for the whole session, and the first and last
        message previews are read from the two ends directly, so a session far
        longer than `MESSAGE_WINDOW` still reports its current state rather
        than a stale prefix.
        """
        row = self._session_row(session_id)
        counts = self._structural_counts(session_id)
        summary = self._summary(
            row,
            turn_count=counts["turn_count"],
            conversation_count=counts["conversation_count"],
        )

        tool_names = [
            entry["tool_name"]
            for entry in self.store.query(
                "SELECT DISTINCT tool_name FROM messages "
                "WHERE session_id = ? AND tool_name IS NOT NULL ORDER BY tool_name LIMIT ?",
                (session_id, MAX_TOOL_NAMES),
            )
        ]
        first_user = self._edge_message(session_id, "role = 'user'", "ASC")
        last_assistant = self._edge_message(
            session_id, "role = 'assistant' AND content IS NOT NULL AND content != ''", "DESC"
        )
        total = self._message_total(session_id)
        return Session(
            **summary.model_dump(),
            cwd=row.get("cwd"),
            chat_type=row.get("chat_type"),
            user_id=row.get("user_id"),
            todo_count=len(self._session_todos(session_id, max_chars)),
            skill_count=counts["skill_count"],
            error_count=counts["error_count"],
            compacted_message_count=counts["compacted_message_count"],
            has_system_prompt=bool(row.get("system_prompt_hash")),
            tool_names=tool_names,
            stored_message_count=total,
            message_window_size=MESSAGE_WINDOW,
            message_window_truncated=total > MESSAGE_WINDOW,
            first_user_prompt=preview(first_user.get("content") if first_user else None, max_chars),
            last_assistant_message=preview(
                last_assistant.get("content") if last_assistant else None, max_chars
            ),
        )

    # ------------------------------------------------------------- scan scope

    def _scope_sessions(
        self,
        *,
        session_id: Optional[str],
        project: Optional[str],
        source: Optional[str],
        since: Optional[float],
        date_bounds: Optional[Tuple[float, float]],
        include_subagents: bool = True,
    ) -> List[Dict[str, Any]]:
        """Sessions a message-derived list may open, newest-first and bounded."""
        if session_id:
            return [self._session_row(session_id)]
        return self._session_rows(
            project=project,
            source=source,
            since=since,
            date_bounds=date_bounds,
            include_subagents=include_subagents,
            limit=MAX_SCANNED_SESSIONS,
        )

    @staticmethod
    def _take(rows: List[Any], limit: int) -> List[Any]:
        return rows[: max(0, limit)]

    @staticmethod
    def _newest(rows: List[Any], limit: int) -> List[Any]:
        """Keep the newest `limit` rows of one session's chronological output.

        A bounded view of a long session has to answer "what is happening now",
        so the cut is taken off the old end. Sessions themselves are already
        scanned newest-first, so the surrounding accumulation stays correct.
        """
        bounded = max(0, limit)
        if not bounded:
            return []
        return rows[-bounded:]

    # ---------------------------------------------------------- conversations

    def _session_conversations(
        self, session_id: str, messages: List[Dict[str, Any]], max_chars: int,
        start_index: int = 1,
    ) -> List[Conversation]:
        rows: List[Conversation] = []
        for index, segment in enumerate(segment_conversations(messages), start=start_index):
            first_user = next((m for m in segment if m.get("role") == "user"), None)
            rows.append(
                Conversation(
                    id=f"{session_id}:{index}",
                    session_id=session_id,
                    index=index,
                    started_by="session_start" if index == 1 else "compaction",
                    started_at=to_iso(segment[0].get("timestamp")) or "",
                    ended_at=to_iso(segment[-1].get("timestamp")),
                    message_count=len(segment),
                    user_message_count=sum(1 for m in segment if m.get("role") == "user"),
                    tool_call_count=sum(
                        len(parse_tool_calls(m.get("tool_calls"))) for m in segment
                    ),
                    first_user_prompt=preview(
                        first_user.get("content") if first_user else None, max_chars
                    ),
                )
            )
        return rows

    def list_conversations(
        self, session_id: Optional[str] = None, project: Optional[str] = None,
        source: Optional[str] = None, since: Optional[float] = None,
        date_bounds: Optional[Tuple[float, float]] = None,
        limit: int = 100, max_chars: int = DEFAULT_MAX_CHARS,
    ) -> List[Conversation]:
        """Context segments across the scoped sessions."""
        collected: List[Conversation] = []
        for row in self._scope_sessions(
            session_id=session_id, project=project, source=source,
            since=since, date_bounds=date_bounds,
        ):
            messages, _, _, conversation_start = self._session_context(row["id"])
            collected.extend(
                self._newest(
                    self._session_conversations(
                        row["id"], messages, max_chars, start_index=conversation_start
                    ),
                    limit,
                )
            )
            if len(collected) >= limit:
                break
        return self._take(collected, limit)

    @staticmethod
    def split_indexed_id(value: str) -> Tuple[str, int]:
        """Split a `<session id>:<n>` reference from the right.

        Splitting from the right keeps session ids that themselves contain a
        colon working.
        """
        session_id, separator, index = (value or "").rpartition(":")
        if not separator or not index.isdigit():
            raise ClientError(
                f"Invalid reference {value!r}; expected <session-id>:<number>"
            )
        return session_id, int(index)

    def get_conversation(self, reference: str, max_chars: int = DEFAULT_MAX_CHARS) -> Conversation:
        """One context segment, addressed as `<session id>:<n>`."""
        session_id, index = self.split_indexed_id(reference)
        session_id = self.resolve_session_id(session_id)
        messages, _, _, conversation_start = self._session_context(session_id)
        rows = self._session_conversations(
            session_id, messages, max_chars, start_index=conversation_start
        )
        for row in rows:
            if row.index == index:
                return row
        raise ClientError(
            f"Session {session_id} has {len(rows)} conversations; {index} is out of range"
        )

    # ------------------------------------------------------------------ turns

    def _session_turns(
        self, session_id: str, messages: List[Dict[str, Any]], max_chars: int,
        start_index: int = 1,
    ) -> List[Turn]:
        rows: List[Turn] = []
        for index, segment in enumerate(segment_turns(messages), start=start_index):
            opener = segment[0] if segment[0].get("role") == "user" else None
            calls = [call for m in segment for call in parse_tool_calls(m.get("tool_calls"))]
            started = segment[0].get("timestamp")
            ended = segment[-1].get("timestamp")
            assistant = [m for m in segment if m.get("role") == "assistant"]
            rows.append(
                Turn(
                    id=f"{session_id}:{index}",
                    session_id=session_id,
                    index=index,
                    started_at=to_iso(started) or "",
                    ended_at=to_iso(ended),
                    duration_seconds=(
                        round(ended - started, 3)
                        if started is not None and ended is not None
                        else None
                    ),
                    user_prompt=preview(opener.get("content") if opener else None, max_chars),
                    assistant_message_count=len(assistant),
                    tool_call_count=len(calls),
                    tools_used=sorted({call["name"] for call in calls}),
                    finish_reason=(assistant[-1].get("finish_reason") if assistant else None),
                    has_errors=any(
                        m.get("role") == "tool" and tool_status(m.get("content")) == "error"
                        for m in segment
                    ),
                )
            )
        return rows

    def list_turns(
        self, session_id: Optional[str] = None, project: Optional[str] = None,
        source: Optional[str] = None, since: Optional[float] = None,
        date_bounds: Optional[Tuple[float, float]] = None,
        limit: int = 100, max_chars: int = DEFAULT_MAX_CHARS,
    ) -> List[Turn]:
        """Turns across the scoped sessions."""
        collected: List[Turn] = []
        for row in self._scope_sessions(
            session_id=session_id, project=project, source=source,
            since=since, date_bounds=date_bounds,
        ):
            messages, _, turn_start, _ = self._session_context(row["id"])
            collected.extend(
                self._newest(
                    self._session_turns(row["id"], messages, max_chars, start_index=turn_start),
                    limit,
                )
            )
            if len(collected) >= limit:
                break
        return self._take(collected, limit)

    def get_turn(self, reference: str, max_chars: int = DEFAULT_MAX_CHARS) -> Turn:
        """One turn, addressed as `<session id>:<n>`."""
        session_id, index = self.split_indexed_id(reference)
        session_id = self.resolve_session_id(session_id)
        messages, _, turn_start, _ = self._session_context(session_id)
        rows = self._session_turns(session_id, messages, max_chars, start_index=turn_start)
        for row in rows:
            if row.index == index:
                return row
        raise ClientError(f"Session {session_id} has {len(rows)} turns; {index} is out of range")

    # ------------------------------------------------------------- tool calls

    def _session_tool_calls(
        self, session_id: str, messages: List[Dict[str, Any]], max_chars: int,
        turn_start: int = 1,
    ) -> List[ToolCall]:
        results = {
            m["tool_call_id"]: m for m in messages
            if m.get("role") == "tool" and m.get("tool_call_id")
        }
        turn_of: Dict[int, int] = {}
        for index, segment in enumerate(segment_turns(messages), start=turn_start):
            for message in segment:
                turn_of[message["id"]] = index

        rows: List[ToolCall] = []
        for message in messages:
            for call in parse_tool_calls(message.get("tool_calls")):
                result = results.get(call["id"])
                started = message.get("timestamp")
                finished = result.get("timestamp") if result else None
                rows.append(
                    ToolCall(
                        id=call["id"] or f"{session_id}:{message['id']}",
                        session_id=session_id,
                        turn=turn_of.get(message["id"]),
                        tool=call["name"],
                        timestamp=to_iso(started) or "",
                        status=tool_status(result.get("content") if result else None),
                        duration_seconds=(
                            round(finished - started, 3)
                            if started is not None and finished is not None
                            else None
                        ),
                        arguments=preview(call["arguments"], max_chars),
                        result=preview(result.get("content") if result else None, max_chars),
                    )
                )
        return rows

    def list_tool_calls(
        self, session_id: Optional[str] = None, project: Optional[str] = None,
        tool: Optional[str] = None, source: Optional[str] = None,
        since: Optional[float] = None,
        date_bounds: Optional[Tuple[float, float]] = None,
        limit: int = 100, max_chars: int = DEFAULT_MAX_CHARS,
    ) -> List[ToolCall]:
        """Tool invocations across the scoped sessions."""
        collected: List[ToolCall] = []
        for row in self._scope_sessions(
            session_id=session_id, project=project, source=source,
            since=since, date_bounds=date_bounds,
        ):
            messages, _, turn_start, _ = self._session_context(row["id"])
            calls = self._session_tool_calls(row["id"], messages, max_chars, turn_start=turn_start)
            if tool:
                calls = [call for call in calls if call.tool == tool]
            collected.extend(self._newest(calls, limit))
            if len(collected) >= limit:
                break
        return self._take(collected, limit)

    def get_tool_call(
        self, call_id: str, session_id: Optional[str] = None,
        project: Optional[str] = None, max_chars: int = DEFAULT_MAX_CHARS,
    ) -> ToolCall:
        """One tool call by its call id."""
        scope = self._scope_sessions(
            session_id=session_id, project=project, source=None,
            since=None, date_bounds=None,
        )
        for row in scope:
            messages, _, turn_start, _ = self._session_context(row["id"])
            for call in self._session_tool_calls(row["id"], messages, max_chars, turn_start=turn_start):
                if call.id == call_id:
                    return call
        raise ClientError(f"Tool call {call_id!r} not found in the scanned sessions")

    # ------------------------------------------------------------------ todos

    def _session_todos(self, session_id: str, max_chars: int = DEFAULT_MAX_CHARS) -> List[Todo]:
        """The final todo list of a session.

        Hermes rewrites the whole list on every `todo` call, so only the last
        call's payload describes the end state. This reads the newest matching
        calls directly instead of scanning a message window, so the answer is
        the live list even for a session with hundreds of thousands of
        messages. `content` goes through the same bounded, redacted preview as
        every other text field the CLI prints.
        """
        sql = (
            "SELECT id, timestamp, tool_calls FROM messages "
            "WHERE session_id = ? AND tool_calls IS NOT NULL AND tool_calls LIKE ? "
            "ORDER BY id DESC LIMIT ?"
        )
        candidates = self.store.query(sql, (session_id, '%"todo"%', LATEST_CALL_SCAN))
        for message in candidates:
            for call in parse_tool_calls(message.get("tool_calls")):
                if call["name"] != TODO_TOOL:
                    continue
                items = extract_todos(call["arguments"])
                if not items:
                    continue
                updated_at = to_iso(message.get("timestamp")) or ""
                return [
                    Todo(
                        id=f"{session_id}:{item['position']}",
                        session_id=session_id,
                        position=item["position"],
                        content=preview(item["content"], max_chars) or "",
                        status=item["status"],
                        updated_at=updated_at,
                    )
                    for item in items
                ]
        return []

    def list_todos(
        self, session_id: Optional[str] = None, project: Optional[str] = None,
        source: Optional[str] = None, since: Optional[float] = None,
        date_bounds: Optional[Tuple[float, float]] = None, limit: int = 100,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> List[Todo]:
        """Final todo lists across the scoped sessions."""
        collected: List[Todo] = []
        if limit <= 0:
            return []
        for row in self._scope_sessions(
            session_id=session_id, project=project, source=source,
            since=since, date_bounds=date_bounds,
        ):
            collected.extend(self._session_todos(row["id"], max_chars))
            if len(collected) >= limit:
                break
        return self._take(collected, limit)

    def get_todo(self, reference: str, max_chars: int = DEFAULT_MAX_CHARS) -> Todo:
        """One todo item, addressed as `<session id>:<position>`."""
        session_id, position = self.split_indexed_id(reference)
        session_id = self.resolve_session_id(session_id)
        rows = self._session_todos(session_id, max_chars)
        for row in rows:
            if row.position == position:
                return row
        raise ClientError(
            f"Session {session_id} has {len(rows)} todo items; position {position} is out of range"
        )

    # ----------------------------------------------------------------- skills

    def _session_skills(
        self, session_id: str, messages: List[Dict[str, Any]], max_chars: int
    ) -> List[Skill]:
        results = {
            m["tool_call_id"]: m for m in messages
            if m.get("role") == "tool" and m.get("tool_call_id")
        }
        rows: List[Skill] = []
        for message in messages:
            if message.get("role") == "user":
                name = slash_command_name(message.get("content"))
                if name:
                    rows.append(
                        Skill(
                            id=f"{session_id}:{message['id']}:0",
                            session_id=session_id,
                            kind="command",
                            name=name,
                            timestamp=to_iso(message.get("timestamp")) or "",
                            status="invoked",
                            detail=preview(message.get("content"), max_chars),
                        )
                    )
            for position, call in enumerate(parse_tool_calls(message.get("tool_calls"))):
                if call["name"] not in SKILL_TOOLS:
                    continue
                result = results.get(call["id"])
                content = result.get("content") if result else None
                rows.append(
                    Skill(
                        id=f"{session_id}:{message['id']}:{position}",
                        session_id=session_id,
                        kind="skill",
                        name=skill_name_from_result(content, call["arguments"]) or call["name"],
                        timestamp=to_iso(message.get("timestamp")) or "",
                        status=tool_status(content),
                        detail=preview(content, max_chars),
                    )
                )
        return rows

    def list_skills(
        self, session_id: Optional[str] = None, project: Optional[str] = None,
        source: Optional[str] = None, since: Optional[float] = None,
        date_bounds: Optional[Tuple[float, float]] = None,
        limit: int = 100, max_chars: int = DEFAULT_MAX_CHARS,
    ) -> List[Skill]:
        """Skill loads and slash commands across the scoped sessions."""
        collected: List[Skill] = []
        for row in self._scope_sessions(
            session_id=session_id, project=project, source=source,
            since=since, date_bounds=date_bounds,
        ):
            messages, _, _, _ = self._session_context(row["id"])
            collected.extend(self._newest(self._session_skills(row["id"], messages, max_chars), limit))
            if len(collected) >= limit:
                break
        return self._take(collected, limit)

    def get_skill(
        self, reference: str, session_id: Optional[str] = None,
        project: Optional[str] = None, max_chars: int = DEFAULT_MAX_CHARS,
    ) -> Skill:
        """One skill load or slash command by its id."""
        scope = self._scope_sessions(
            session_id=session_id, project=project, source=None,
            since=None, date_bounds=None,
        )
        for row in scope:
            messages, _, _, _ = self._session_context(row["id"])
            for skill in self._session_skills(row["id"], messages, max_chars):
                if skill.id == reference:
                    return skill
        raise ClientError(f"Skill record {reference!r} not found in the scanned sessions")

    # ------------------------------------------------------- subagent activity

    def _subagent(self, child: Dict[str, Any], max_chars: int) -> SubagentActivity:
        messages, _, _, _ = self._session_context(child["id"])
        first_user = next((m for m in messages if m.get("role") == "user"), None)
        last_assistant = next(
            (m for m in reversed(messages) if m.get("role") == "assistant" and m.get("content")),
            None,
        )
        started = child.get("started_at")
        completed = child.get("ended_at")
        return SubagentActivity(
            id=child["id"],
            parent_session=child.get("parent_session_id"),
            child_session=child["id"],
            label=preview(first_user.get("content") if first_user else child.get("title"), max_chars),
            status=child.get("end_reason") or ("running" if completed is None else "unknown"),
            started_at=to_iso(started) or "",
            completed_at=to_iso(completed),
            duration_seconds=(
                round(completed - started, 3)
                if started is not None and completed is not None
                else None
            ),
            model=child.get("model"),
            message_count=child.get("message_count") or 0,
            tool_call_count=child.get("tool_call_count") or 0,
            effective_tokens=effective_tokens(child),
            result=preview(last_assistant.get("content") if last_assistant else None, max_chars),
        )

    def list_subagent_activity(
        self, session_id: Optional[str] = None, project: Optional[str] = None,
        since: Optional[float] = None,
        date_bounds: Optional[Tuple[float, float]] = None,
        limit: int = 100, max_chars: int = DEFAULT_MAX_CHARS,
    ) -> List[SubagentActivity]:
        """Delegated subagent runs, scoped to a parent session or a project."""
        if session_id:
            rows = self._session_rows(parent_session=session_id, limit=limit)
        else:
            rows = self._session_rows(
                project=project, source="subagent", since=since,
                date_bounds=date_bounds, limit=limit,
            )
        return [self._subagent(row, max_chars) for row in rows]

    def get_subagent_activity(
        self, child_session_id: str, max_chars: int = DEFAULT_MAX_CHARS
    ) -> SubagentActivity:
        """One subagent run, addressed by its child session id."""
        return self._subagent(self._session_row(child_session_id), max_chars)

    # --------------------------------------------------------------- timeline

    def _session_timeline(
        self, session_id: str, messages: List[Dict[str, Any]], max_chars: int,
        subagent_session: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Chronological events for one session, as sortable dicts."""
        results = {
            m["tool_call_id"]: m for m in messages
            if m.get("role") == "tool" and m.get("tool_call_id")
        }
        events: List[Dict[str, Any]] = []

        def add(message, event_type, actor, summary, tool=None, status=None):
            events.append(
                {
                    "session_id": session_id,
                    "subagent_session": subagent_session,
                    "sort_key": (message.get("timestamp") or 0, message["id"]),
                    "timestamp": to_iso(message.get("timestamp")) or "",
                    "event_type": event_type,
                    "actor": actor,
                    "tool": tool,
                    "status": status,
                    "summary": summary,
                }
            )

        for message in messages:
            role = message.get("role")
            if message.get("_compressed_summary"):
                add(message, "compaction", role or "system",
                    preview(message.get("content"), max_chars))
                continue
            if role == "user":
                command = slash_command_name(message.get("content"))
                add(message, "command" if command else "user_message", "user",
                    preview(message.get("content"), max_chars),
                    tool=command, status="invoked" if command else None)
            elif role == "assistant":
                if message.get("content"):
                    add(message, "assistant_message", "assistant",
                        preview(message.get("content"), max_chars),
                        status=message.get("finish_reason"))
                for call in parse_tool_calls(message.get("tool_calls")):
                    result = results.get(call["id"])
                    content = result.get("content") if result else None
                    if call["name"] in SKILL_TOOLS:
                        event_type = "skill_load"
                    elif call["name"] == DELEGATE_TOOL:
                        event_type = "subagent_start"
                    elif call["name"] == TODO_TOOL:
                        event_type = "todo_write"
                    else:
                        event_type = "tool_call"
                    add(message, event_type, "assistant",
                        preview(call["arguments"], max_chars),
                        tool=call["name"], status=tool_status(content))
            elif role == "session_meta":
                add(message, "notice", "system",
                    preview(message.get("content") or message.get("display_kind"), max_chars),
                    status=message.get("display_kind"))
            elif role == "tool" and tool_status(message.get("content")) == "error":
                add(message, "error", "tool",
                    preview(message.get("content"), max_chars),
                    tool=message.get("tool_name"), status="error")
        return events

    @staticmethod
    def _number(events: List[Dict[str, Any]], limit: int) -> List[TimelineEvent]:
        """Order events chronologically and keep the newest `limit` of them."""
        bounded = max(0, limit)
        ordered = sorted(events, key=lambda event: event["sort_key"])
        ordered = ordered[-bounded:] if bounded else []
        return [
            TimelineEvent(index=index, **{k: v for k, v in event.items() if k != "sort_key"})
            for index, event in enumerate(ordered, start=1)
        ]

    def list_timeline(
        self, session_id: Optional[str] = None, project: Optional[str] = None,
        source: Optional[str] = None, since: Optional[float] = None,
        date_bounds: Optional[Tuple[float, float]] = None,
        errors_only: bool = False, limit: int = 100,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> List[TimelineEvent]:
        """Activity events across the scoped sessions."""
        collected: List[Dict[str, Any]] = []
        for row in self._scope_sessions(
            session_id=session_id, project=project, source=source,
            since=since, date_bounds=date_bounds,
        ):
            messages, _, _, _ = self._session_context(row["id"])
            events = self._session_timeline(row["id"], messages, max_chars)
            if errors_only:
                events = [e for e in events if e["status"] == "error" or e["event_type"] == "error"]
            collected.extend(events)
            if len(collected) >= limit:
                break
        return self._number(collected, limit)

    def get_timeline(
        self, session_id: str, errors_only: bool = False, limit: int = 100,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> List[TimelineEvent]:
        """Every event of one session."""
        messages, _, _, _ = self._session_context(session_id)
        events = self._session_timeline(session_id, messages, max_chars)
        if errors_only:
            events = [e for e in events if e["status"] == "error" or e["event_type"] == "error"]
        return self._number(events, limit)

    def consolidated_timeline(
        self, session_id: str, limit: int = 100, max_chars: int = DEFAULT_MAX_CHARS,
        include_subagents: bool = True,
    ) -> List[TimelineEvent]:
        """One session merged with its subagent sessions, chronologically.

        The merged view is bounded twice: `--limit` caps the event count and
        every summary is a bounded preview, so a consolidated view of a long
        run can never become a transcript dump.
        """
        messages, _, _, _ = self._session_context(session_id)
        events = self._session_timeline(session_id, messages, max_chars)
        if include_subagents:
            children = self._session_rows(parent_session=session_id, limit=MAX_SCANNED_SESSIONS)
            for child in children:
                child_messages, _, _, _ = self._session_context(child["id"])
                events.extend(
                    self._session_timeline(
                        child["id"], child_messages, max_chars,
                        subagent_session=child["id"],
                    )
                )
        return self._number(events, limit)

    # ----------------------------------------------------------------- search

    def search_messages(
        self, query: str, project: Optional[str] = None,
        session_id: Optional[str] = None, since: Optional[float] = None,
        limit: int = 100, max_chars: int = DEFAULT_MAX_CHARS,
    ) -> List[SearchMatch]:
        """Full-text search over message content using the Hermes FTS5 index."""
        if not (query or "").strip():
            raise ClientError("a search query is required")
        if not self.store.has_table("messages_fts"):
            raise ClientError("Hermes state store has no messages_fts index")

        clauses = ["messages_fts MATCH ?"]
        params: List[Any] = [query]
        if session_id:
            clauses.append("m.session_id = ?")
            params.append(session_id)
        if project is not None:
            predicate, values = self._workspace_clause(
                self.resolve_project_cwds(project), column="s.cwd"
            )
            clauses.append(predicate)
            params.extend(values)
        if since is not None:
            clauses.append("m.timestamp >= ?")
            params.append(since)

        sql = (
            "SELECT m.id AS id, m.session_id AS session_id, m.role AS role, "
            "m.tool_name AS tool_name, m.timestamp AS timestamp, m.content AS content, "
            "s.title AS title, s.cwd AS cwd "
            "FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid "
            "JOIN sessions s ON s.id = m.session_id "
            f"WHERE {' AND '.join(clauses)} ORDER BY m.timestamp DESC LIMIT ?"
        )
        params.append(max(0, limit))
        return [
            SearchMatch(
                id=str(row["id"]),
                session_id=row["session_id"],
                session_title=row.get("title"),
                project=project_name(row.get("cwd")),
                role=row.get("role") or "unknown",
                tool=row.get("tool_name"),
                timestamp=to_iso(row.get("timestamp")) or "",
                snippet=preview(row.get("content"), max_chars),
            )
            for row in self.store.query(sql, params)
        ]

    def search_sessions(
        self, query: str, project: Optional[str] = None,
        since: Optional[float] = None, limit: int = 100,
    ) -> List[SessionSummary]:
        """Sessions whose title contains the query, newest-first."""
        if not (query or "").strip():
            raise ClientError("a search query is required")
        clauses = ["title IS NOT NULL", "lower(title) LIKE lower(?)"]
        params: List[Any] = [f"%{query}%"]
        if project is not None:
            predicate, values = self._workspace_clause(self.resolve_project_cwds(project))
            clauses.append(predicate)
            params.extend(values)
        if since is not None:
            clauses.append("started_at >= ?")
            params.append(since)
        sql = (
            f"SELECT {self._session_select()} FROM sessions "
            f"WHERE {' AND '.join(clauses)} ORDER BY started_at DESC LIMIT ?"
        )
        params.append(max(0, limit))
        return [self._summary(row) for row in self.store.query(sql, params)]


_client: Optional[HermesSessionsClient] = None


def get_client(config: Optional[Config] = None) -> HermesSessionsClient:
    """Get or create the global client instance."""
    global _client
    if _client is None or config is not None:
        _client = HermesSessionsClient(config=config)
    return _client
