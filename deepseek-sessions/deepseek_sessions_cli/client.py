"""DeepSeek Sessions client for reading local dsh session data.

Layout this client walks:

    <dsh home>/sessions/
      --Users-adam-Dropbox-GitRepos-Agents-LegoScout--/   project key
        session-<uuid>/session.jsonl.zstd                 a session the user drove
        <uuid>/session.jsonl.zstd                         a spawned subagent session
      _no-cwd/                                            sessions with no cwd

The project directory name is a lossy encoding of the working directory, so the
real path always comes from each log's header `cwd` field, never from decoding
the directory name.
"""
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cli_tools_shared.output import print_warning

from .config import get_config
from .logfile import (
    SessionLog,
    SessionLogError,
    find_log_path,
    load_log,
    load_log_header,
    read_log_text,
)
from .models import (
    ApprovalSummary,
    ConversationDetail,
    ConversationSummary,
    GoalSummary,
    Project,
    RetrySummary,
    SearchResult,
    Session,
    SessionSummary,
    SkillInvocation,
    StepSummary,
    Subagent,
    SubagentSummary,
    TimelineEntry,
    TodoSummary,
    ToolCallSummary,
    TurnSummary,
)
from .parsers import (
    build_subagent,
    extract_approvals,
    extract_goals,
    extract_retries,
    extract_skill_invocations,
    extract_steps,
    extract_subagent_spawns,
    extract_timeline,
    extract_todo_write_time,
    extract_todos,
    extract_tool_calls,
    extract_turns,
    format_local_time,
    in_date_window,
    is_after_cutoff,
    parse_conversation_summaries,
    parse_full_session,
    parse_session_summary,
    parse_since,
    project_key,
    project_name_from_cwd,
    search_log,
    summarize_subagent_session,
)

# dsh session ids are either `session-<uuid>` (a session the user drove) or a
# bare `<uuid>` (a spawned subagent session). Anything else is a name.
SESSION_ID_RE = re.compile(
    r"^(session-)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class ClientError(Exception):
    """Raised when dsh session data cannot be read or resolved."""


class DeepSeekSessionsClient:
    """Client for reading DeepSeek Harness session data from the dsh home."""

    def __init__(self):
        self.config = get_config()
        self.dsh_home = self.config.dsh_home
        self.sessions_dir = self.config.sessions_dir

        if not self.dsh_home.exists():
            raise ClientError(
                f"DeepSeek Harness data directory not found: {self.dsh_home}. "
                "Have you used dsh before? Set DSH_HOME if it lives elsewhere."
            )

    # ==================== Log discovery ====================

    def _project_dirs(self) -> List[Path]:
        if not self.sessions_dir.exists():
            return []
        return sorted(path for path in self.sessions_dir.iterdir() if path.is_dir())

    def _session_dirs(self, project_dir: Path) -> List[Path]:
        """Return the session directories inside a project directory.

        dsh rejects the obsolete flat-file layout, so only directories count.
        """
        return sorted(path for path in project_dir.iterdir() if path.is_dir())

    def _load(self, session_dir: Path, *, strict: bool = False) -> Optional[SessionLog]:
        """Decode one session log, or return None when it holds none or is unreadable.

        A corrupt or malformed log (an unreadable header, a truncated header
        frame, an empty file) must never abort a command that is walking many
        sessions: one bad file is skipped with a warning to stderr, and every
        other session is still returned. A line that fails to parse inside an
        otherwise-good log is handled the same way by `load_log` itself and
        reported here too.

        `strict=True` is for a caller resolving one specific, explicitly
        requested session id (`sessions get`, `subagent-activity get`, ...):
        there is no "other session" to fall back to, so the real parse error
        is raised instead of being silently swallowed into a confusing
        "not found".
        """
        log_path = find_log_path(session_dir)
        if log_path is None:
            return None
        try:
            log = load_log(log_path)
        except SessionLogError as exc:
            if strict:
                raise ClientError(str(exc)) from exc
            print_warning(f"skipping unreadable session log: {exc}")
            return None

        if log.skipped_lines:
            lines = ", ".join(str(number) for number in log.skipped_lines)
            print_warning(
                f"skipped {len(log.skipped_lines)} malformed line(s) "
                f"({lines}) in {log_path}"
            )
        return log

    def _iter_logs(self, project_dir: Path) -> List[SessionLog]:
        logs = []
        for session_dir in self._session_dirs(project_dir):
            log = self._load(session_dir)
            if log is not None:
                logs.append(log)
        return logs

    def _project_name(self, project_dir: Path, log: Optional[SessionLog] = None) -> str:
        """Resolve a project's display name from a session header's cwd."""
        if log is not None and log.cwd:
            return project_name_from_cwd(log.cwd)
        for session_dir in self._session_dirs(project_dir):
            candidate = self._load(session_dir)
            if candidate is not None and candidate.cwd:
                return project_name_from_cwd(candidate.cwd)
        return project_dir.name

    def _resolve_project_dir(self, project: str) -> Path:
        """Find a project directory by name, absolute path, or directory key."""
        if project.startswith("/"):
            candidate = self.sessions_dir / project_key(project)
            if candidate.is_dir():
                return candidate
            raise ClientError(f"No dsh sessions found for path: {project}")

        matches = []
        for project_dir in self._project_dirs():
            if project_dir.name == project:
                return project_dir
            if self._project_name(project_dir) == project:
                matches.append(project_dir)

        if not matches:
            raise ClientError(f"Project not found: {project}")
        if len(matches) > 1:
            keys = ", ".join(sorted(path.name for path in matches))
            raise ClientError(
                f'{len(matches)} projects are named "{project}": {keys}. '
                "Re-run with the full project path or the directory key."
            )
        return matches[0]

    # ==================== Auth ====================
    # Local file access is always available; there is no remote credential.

    def auth_status(self) -> Dict[str, Any]:
        """Report whether the local dsh session store is readable."""
        project_dirs = self._project_dirs()
        return {
            "authenticated": self.sessions_dir.exists(),
            "dsh_home": str(self.dsh_home),
            "sessions_dir": str(self.sessions_dir),
            "sessions_dir_exists": self.sessions_dir.exists(),
            "project_count": len(project_dirs),
        }

    # ==================== Projects ====================

    def list_projects(self, limit: int = 100) -> List[Project]:
        """List every project directory that holds at least one session log."""
        projects: List[Project] = []

        for project_dir in self._project_dirs():
            log_paths = [
                log_path
                for session_dir in self._session_dirs(project_dir)
                if (log_path := find_log_path(session_dir)) is not None
            ]
            if not log_paths:
                continue

            headers = []
            for log_path in log_paths:
                try:
                    headers.append(load_log_header(log_path))
                except SessionLogError as exc:
                    print_warning(f"skipping unreadable session log: {exc}")

            cwd = next((header.get("cwd") for header in headers if header.get("cwd")), "")
            subagents = sum(1 for header in headers if header.get("origin") == "subagent")
            newest_mtime = max(log_path.stat().st_mtime for log_path in log_paths)
            last_activity = datetime.fromtimestamp(
                newest_mtime,
                tz=timezone.utc,
            ).isoformat().replace("+00:00", "Z")

            projects.append(
                Project(
                    name=project_name_from_cwd(cwd) if cwd else project_dir.name,
                    full_path=cwd or "",
                    encoded_path=project_dir.name,
                    session_count=len(headers),
                    subagent_session_count=subagents,
                    last_activity=last_activity,
                )
            )

        projects.sort(key=lambda project: project.last_activity or "", reverse=True)
        return projects[:limit]

    def get_project(self, name: str) -> Project:
        """Get one project by name, absolute path, or directory key."""
        project_dir = self._resolve_project_dir(name)
        for project in self.list_projects(limit=100000):
            if project.encoded_path == project_dir.name:
                return project
        raise ClientError(f"Project not found: {name}")

    # ==================== Sessions ====================

    def resolve_session_id(self, identifier: str, project: Optional[str] = None) -> str:
        """Resolve a session id or title to a session id.

        A `session-<uuid>` or bare `<uuid>` value is returned unchanged.
        Anything else is matched case-insensitively against session titles,
        scoped to the project when one is given. A name that matches more than
        one session raises rather than silently picking one.
        """
        if SESSION_ID_RE.match(identifier):
            return identifier

        wanted = identifier.strip().lower()

        def scan(dirs: List[Path]) -> List[Tuple[str, str, str]]:
            found = []
            for project_dir in dirs:
                for log in self._iter_logs(project_dir):
                    summary = parse_session_summary(
                        log, self._project_name(project_dir, log)
                    )
                    title = summary.custom_title
                    if title and title.strip().lower() == wanted:
                        found.append(
                            (summary.id, summary.project, summary.last_activity)
                        )
            return found

        scoped = [self._resolve_project_dir(project)] if project else self._project_dirs()
        matches = scan(scoped)

        if not matches:
            if project:
                elsewhere = scan(self._project_dirs())
                if elsewhere:
                    found_in = ", ".join(sorted({row[1] for row in elsewhere}))
                    raise ClientError(
                        f'Session "{identifier}" not found in project "{project}". '
                        f"Found in: {found_in}. "
                        "Omit --project to auto-resolve, or pass the correct project."
                    )
            raise ClientError(
                f'No session named "{identifier}". '
                "Run 'deepseek-sessions sessions list' to see names, "
                "or pass a session ID."
            )

        if len(matches) > 1:
            matches.sort(key=lambda row: row[2] or "", reverse=True)
            lines = [f'{len(matches)} sessions match "{identifier}":']
            for session_id, project_name, last_activity in matches:
                lines.append(
                    f"  {session_id}  {project_name}   {format_local_time(last_activity)}"
                )
            lines.append("Re-run with a session ID.")
            raise ClientError("\n".join(lines))

        return matches[0][0]

    def _find_session_dir(self, session_id: str) -> Tuple[Path, Path]:
        """Return (project_dir, session_dir) for a session id."""
        for project_dir in self._project_dirs():
            session_dir = project_dir / session_id
            if session_dir.is_dir():
                return project_dir, session_dir
        raise ClientError(f"Session not found: {session_id}")

    def load_session_log(self, session_id: str) -> Tuple[SessionLog, str]:
        """Load one session log and its project name."""
        project_dir, session_dir = self._find_session_dir(session_id)
        log = self._load(session_dir, strict=True)
        if log is None:
            raise ClientError(f"Session directory holds no log: {session_dir}")
        return log, self._project_name(project_dir, log)

    def get_session_project(self, session_id: str) -> str:
        """Return the project name that owns a session."""
        project_dir, session_dir = self._find_session_dir(session_id)
        return self._project_name(project_dir, self._load(session_dir, strict=True))

    def _collect_summaries(
        self,
        project_dir: Path,
        since: Optional[str] = None,
        date_bounds: Optional[tuple] = None,
        min_tool_calls: Optional[int] = None,
        include_subagents: bool = True,
    ) -> List[SessionSummary]:
        cutoff = parse_since(since) if since else None
        summaries: List[SessionSummary] = []

        for log in self._iter_logs(project_dir):
            if not include_subagents and log.header.get("origin") == "subagent":
                continue

            summary = parse_session_summary(log, self._project_name(project_dir, log))

            if cutoff and not is_after_cutoff(summary.last_activity, cutoff):
                continue
            if date_bounds is not None and not in_date_window(
                summary.last_activity, date_bounds
            ):
                continue
            if min_tool_calls is not None and min_tool_calls > 0:
                if (summary.tool_call_count or 0) < min_tool_calls:
                    continue

            summaries.append(summary)

        return summaries

    def list_sessions(
        self,
        project: Optional[str] = None,
        limit: int = 100,
        since: Optional[str] = None,
        date_bounds: Optional[tuple] = None,
        min_tool_calls: Optional[int] = None,
        include_subagents: bool = True,
    ) -> List[SessionSummary]:
        """List sessions in a project, or across every project when None."""
        project_dirs = (
            [self._resolve_project_dir(project)] if project else self._project_dirs()
        )

        merged: List[SessionSummary] = []
        for project_dir in project_dirs:
            merged.extend(
                self._collect_summaries(
                    project_dir,
                    since=since,
                    date_bounds=date_bounds,
                    min_tool_calls=min_tool_calls,
                    include_subagents=include_subagents,
                )
            )

        merged.sort(key=lambda summary: summary.last_activity or "", reverse=True)
        return merged[:limit]

    def get_session(self, session_id: str) -> Session:
        """Get one full session, with its subagent child sessions attached."""
        project_dir, session_dir = self._find_session_dir(session_id)
        log = self._load(session_dir, strict=True)
        if log is None:
            raise ClientError(f"Session directory holds no log: {session_dir}")

        project_name = self._project_name(project_dir, log)
        session = parse_full_session(log, project_name)

        spawns = extract_subagent_spawns(log)
        for child_id, spawn in spawns.items():
            child_dir = project_dir / child_id
            child = self._load(child_dir) if child_dir.is_dir() else None
            if child is not None:
                session.subagents[child_id] = build_subagent(child, project_name, spawn)

        return session

    def search_sessions(
        self,
        query: str,
        project: Optional[str] = None,
        limit: int = 100,
        since: Optional[str] = None,
    ) -> List[SessionSummary]:
        """Return session summaries whose transcript contains a query string."""
        matched_ids = {
            result.session_id
            for result in self.search_all(
                query=query, project=project, limit=100000, since=since, max_matches_per_session=1
            )
        }
        return [
            summary
            for summary in self.list_sessions(project=project, limit=100000, since=since)
            if summary.id in matched_ids
        ][:limit]

    def search_all(
        self,
        query: str,
        project: Optional[str] = None,
        limit: int = 20,
        since: Optional[str] = None,
        max_matches_per_session: int = 5,
    ) -> List[SearchResult]:
        """Search every session transcript for a keyword.

        Each log is decoded once for a cheap raw-text containment check before
        the full event walk, so non-matching sessions cost only the decode.
        """
        cutoff = parse_since(since) if since else None
        lowered = query.lower()
        results: List[SearchResult] = []

        project_dirs = (
            [self._resolve_project_dir(project)] if project else self._project_dirs()
        )

        for project_dir in project_dirs:
            for session_dir in self._session_dirs(project_dir):
                log_path = find_log_path(session_dir)
                if log_path is None:
                    continue
                if lowered not in read_log_text(log_path).lower():
                    continue

                log = self._load(session_dir)
                if log is None:
                    continue
                project_name = self._project_name(project_dir, log)
                result = search_log(log, query, project_name, max_matches_per_session)
                if result is None:
                    continue
                if cutoff and not is_after_cutoff(result.last_activity, cutoff):
                    continue
                results.append(result)

        results.sort(key=lambda result: result.last_activity, reverse=True)
        return results[:limit]

    # ==================== Conversations ====================

    def list_conversations(
        self,
        project: str,
        session_id: Optional[str] = None,
        limit: int = 100,
        since: Optional[str] = None,
    ) -> List[ConversationSummary]:
        """List compaction-delimited conversations across a project's sessions."""
        project_dir = self._resolve_project_dir(project)
        cutoff = parse_since(since) if since else None

        conversations: List[ConversationSummary] = []
        for session_dir in self._session_dirs(project_dir):
            if session_id and session_dir.name != session_id:
                continue
            log = self._load(session_dir)
            if log is None:
                continue
            for summary in parse_conversation_summaries(
                log, self._project_name(project_dir, log)
            ):
                if cutoff and not is_after_cutoff(summary.ended_at or "", cutoff):
                    continue
                conversations.append(summary)

        conversations.sort(key=lambda item: item.created_at or "", reverse=True)
        return conversations[:limit]

    def get_conversation(
        self, project: Optional[str], session_id: str, conversation_id: int
    ) -> Optional[ConversationDetail]:
        """Get one conversation with its user and assistant message content."""
        log, project_name = self.load_session_log(session_id)

        summary = next(
            (
                item
                for item in parse_conversation_summaries(log, project_name)
                if item.conversation_id == conversation_id
            ),
            None,
        )
        if summary is None:
            return None

        session = parse_full_session(log, project_name)
        return ConversationDetail(
            **summary.model_dump(exclude={"effective_tokens"}),
            messages=[
                {
                    "type": message.type,
                    "timestamp": message.timestamp,
                    "content": message.content,
                }
                for message in session.messages
                if message.conversation_id == conversation_id
            ],
        )

    # ==================== Per-session extraction helpers ====================

    def _project_scope(
        self, project: str, session_id: Optional[str] = None
    ) -> List[Tuple[SessionLog, str]]:
        """Load the logs a project-scoped list command should walk."""
        project_dir = self._resolve_project_dir(project)
        scope: List[Tuple[SessionLog, str]] = []
        for session_dir in self._session_dirs(project_dir):
            if session_id and session_dir.name != session_id:
                continue
            log = self._load(session_dir)
            if log is not None:
                scope.append((log, self._project_name(project_dir, log)))
        return scope

    @staticmethod
    def _filter_since(rows: List[Any], since: Optional[str]) -> List[Any]:
        if not since:
            return rows
        cutoff = parse_since(since)
        return [row for row in rows if is_after_cutoff(getattr(row, "timestamp", ""), cutoff)]

    # ==================== Subagent activity ====================

    def list_subagent_activity(
        self,
        project: str,
        session_id: Optional[str] = None,
        limit: int = 100,
        since: Optional[str] = None,
    ) -> List[SubagentSummary]:
        """List every subagent session spawned inside a project.

        Each child session log is summarized and joined to the parent's
        `subagent` tool call, so the prompt and the child's own token cost
        appear on one row.
        """
        project_dir = self._resolve_project_dir(project)

        spawns: Dict[str, Dict[str, Any]] = {}
        children: List[Tuple[SessionLog, str]] = []

        for child_dir in self._session_dirs(project_dir):
            log = self._load(child_dir)
            if log is None:
                continue
            if log.header.get("origin") == "subagent":
                children.append((log, self._project_name(project_dir, log)))
            else:
                spawns.update(extract_subagent_spawns(log))

        rows = [
            summarize_subagent_session(log, project_name, spawns.get(log.session_id))
            for log, project_name in children
            if not session_id or log.header.get("parentSession") == session_id
        ]

        rows = self._filter_since(rows, since)
        rows.sort(key=lambda row: row.timestamp or "", reverse=True)
        return rows[:limit]

    def get_subagent(self, subagent_id: str, project: Optional[str] = None) -> Subagent:
        """Get one subagent's full child session."""
        log, project_name = self.load_session_log(subagent_id)
        if log.header.get("origin") != "subagent":
            raise ClientError(
                f"Session {subagent_id} is not a subagent session "
                "(its header has no origin: subagent)."
            )

        spawn = None
        parent_id = log.header.get("parentSession")
        if parent_id:
            project_dir, _ = self._find_session_dir(subagent_id)
            parent_dir = project_dir / parent_id
            if parent_dir.is_dir():
                parent = self._load(parent_dir)
                if parent is not None:
                    spawn = extract_subagent_spawns(parent).get(subagent_id)

        return build_subagent(log, project_name, spawn)

    # ==================== Tool calls ====================

    def list_tool_calls(
        self,
        project: str,
        session_id: Optional[str] = None,
        limit: int = 100,
        since: Optional[str] = None,
        include_subagents: bool = False,
        include_code_dispatch: bool = True,
    ) -> List[ToolCallSummary]:
        """List tool calls in a project, optionally including subagent sessions."""
        project_dir = self._resolve_project_dir(project)

        spawns: Dict[str, Dict[str, Any]] = {}
        for parent_dir in self._session_dirs(project_dir):
            log = self._load(parent_dir)
            if log is not None and log.header.get("origin") != "subagent":
                spawns.update(extract_subagent_spawns(log))

        rows: List[ToolCallSummary] = []
        for session_dir in self._session_dirs(project_dir):
            log = self._load(session_dir)
            if log is None:
                continue
            is_subagent = log.header.get("origin") == "subagent"
            if is_subagent and not include_subagents:
                continue
            if session_id and session_dir.name != session_id:
                continue
            spawn = spawns.get(log.session_id) or {}
            rows.extend(
                extract_tool_calls(
                    log,
                    self._project_name(project_dir, log),
                    is_sidechain=is_subagent,
                    parent_tool_call_id=spawn.get("parent_tool_call_id"),
                    include_code_dispatch=include_code_dispatch,
                )
            )

        rows = self._filter_since(rows, since)
        rows.sort(key=lambda row: row.timestamp or "", reverse=True)
        return rows[:limit]

    def get_tool_call(self, tool_call_id: str, project: str) -> ToolCallSummary:
        """Get one tool call by its dsh call id."""
        for row in self.list_tool_calls(
            project, limit=1000000, include_subagents=True
        ):
            if row.id == tool_call_id:
                return row
        raise ClientError(f"Tool call not found: {tool_call_id}")

    # ==================== Todos ====================

    def list_todos(
        self,
        project: str,
        session_id: Optional[str] = None,
        limit: int = 100,
        since: Optional[str] = None,
    ) -> List[TodoSummary]:
        """List the final todo list of each session in a project."""
        rows: List[TodoSummary] = []
        for log, project_name in self._project_scope(project, session_id):
            written_at = extract_todo_write_time(log)
            for todo in extract_todos(log):
                rows.append(
                    TodoSummary(
                        id=todo.id,
                        session_id=log.session_id,
                        project=project_name,
                        content=todo.content,
                        status=todo.status.value,
                        position=todo.position,
                        written_at=written_at,
                    )
                )

        if since:
            cutoff = parse_since(since)
            rows = [row for row in rows if is_after_cutoff(row.written_at or "", cutoff)]
        return rows[:limit]

    def get_todo(self, project: str, todo_id: str) -> Optional[TodoSummary]:
        """Get one todo by its `<session id>:<position>` id."""
        for row in self.list_todos(project, limit=1000000):
            if row.id == todo_id:
                return row
        return None

    # ==================== Skills ====================

    def list_skills(
        self,
        project: str,
        session_id: Optional[str] = None,
        limit: int = 100,
        since: Optional[str] = None,
    ) -> List[SkillInvocation]:
        """List skill loads and slash-command runs in a project."""
        rows: List[SkillInvocation] = []
        for log, project_name in self._project_scope(project, session_id):
            rows.extend(extract_skill_invocations(log, project_name))

        rows = self._filter_since(rows, since)
        rows.sort(key=lambda row: row.timestamp or "", reverse=True)
        return rows[:limit]

    def get_skill(self, skill_id: str, project: str) -> SkillInvocation:
        """Get one skill or command invocation by id."""
        for row in self.list_skills(project, limit=1000000):
            if row.id == skill_id:
                return row
        raise ClientError(f"Skill invocation not found: {skill_id}")

    # ==================== Timeline ====================

    def get_timeline(
        self,
        session_id: str,
        project: Optional[str] = None,
        limit: int = 500,
        show_thinking: bool = False,
        include_subagents: bool = False,
    ) -> List[TimelineEntry]:
        """Get one session's chronological timeline.

        With include_subagents, every child session's tool calls are merged in
        as `subagent_tool` rows so one view covers the whole delegation tree.
        """
        project_dir, session_dir = self._find_session_dir(session_id)
        log = self._load(session_dir, strict=True)
        if log is None:
            raise ClientError(f"Session directory holds no log: {session_dir}")
        project_name = self._project_name(project_dir, log)

        spawns = extract_subagent_spawns(log)
        labels: Dict[str, str] = {}
        child_logs: Dict[str, SessionLog] = {}
        for child_id in spawns:
            child_dir = project_dir / child_id
            child = self._load(child_dir) if child_dir.is_dir() else None
            if child is None:
                continue
            child_logs[child_id] = child
            labels[child_id] = summarize_subagent_session(
                child, project_name, spawns[child_id]
            ).label

        entries = extract_timeline(
            log, project_name, show_thinking=show_thinking, subagent_labels=labels
        )

        if include_subagents:
            from .models import TimelineEventType

            for child_id, child in child_logs.items():
                for entry in extract_timeline(
                    child, project_name, show_thinking=show_thinking
                ):
                    entry.session_id = child_id
                    entry.agent_id = child_id
                    entry.agent_name = labels.get(child_id)
                    if entry.event_type == TimelineEventType.TOOL_CALL:
                        entry.event_type = TimelineEventType.SUBAGENT_TOOL
                    entries.append(entry)
            entries.sort(key=lambda entry: entry.timestamp or "")

        return entries[:limit]

    def list_timeline(
        self,
        project: str,
        limit: int = 200,
        since: Optional[str] = None,
        session_id: Optional[str] = None,
        show_thinking: bool = False,
    ) -> List[TimelineEntry]:
        """Get a combined timeline across a project's sessions."""
        entries: List[TimelineEntry] = []
        for log, project_name in self._project_scope(project, session_id):
            entries.extend(
                extract_timeline(log, project_name, show_thinking=show_thinking)
            )

        if since:
            cutoff = parse_since(since)
            entries = [
                entry for entry in entries if is_after_cutoff(entry.timestamp, cutoff)
            ]

        entries.sort(key=lambda entry: entry.timestamp or "", reverse=True)
        return entries[:limit]

    # ==================== Turns and steps ====================

    def list_turns(
        self,
        project: str,
        session_id: Optional[str] = None,
        limit: int = 100,
        since: Optional[str] = None,
    ) -> List[TurnSummary]:
        """List agent turns in a project, newest first."""
        rows: List[TurnSummary] = []
        for log, project_name in self._project_scope(project, session_id):
            rows.extend(extract_turns(log, project_name))

        if since:
            cutoff = parse_since(since)
            rows = [row for row in rows if is_after_cutoff(row.started_at, cutoff)]

        rows.sort(key=lambda row: row.started_at or "", reverse=True)
        return rows[:limit]

    def get_turn(self, session_id: str, turn: int) -> Tuple[TurnSummary, List[StepSummary]]:
        """Get one turn and the model round-trips inside it."""
        log, project_name = self.load_session_log(session_id)
        summary = next(
            (row for row in extract_turns(log, project_name) if row.turn == turn), None
        )
        if summary is None:
            raise ClientError(f"Turn {turn} not found in session {session_id}")
        return summary, extract_steps(log, project_name, turn=turn)

    # ==================== Retries, approvals, goals ====================

    def list_retries(
        self,
        project: str,
        session_id: Optional[str] = None,
        limit: int = 100,
        since: Optional[str] = None,
    ) -> List[RetrySummary]:
        """List retryable provider failures in a project."""
        rows: List[RetrySummary] = []
        for log, project_name in self._project_scope(project, session_id):
            rows.extend(extract_retries(log, project_name))

        rows = self._filter_since(rows, since)
        rows.sort(key=lambda row: row.timestamp or "", reverse=True)
        return rows[:limit]

    def list_approvals(
        self,
        project: str,
        session_id: Optional[str] = None,
        limit: int = 100,
        since: Optional[str] = None,
    ) -> List[ApprovalSummary]:
        """List permission escalation requests and their decisions."""
        rows: List[ApprovalSummary] = []
        for log, project_name in self._project_scope(project, session_id):
            rows.extend(extract_approvals(log, project_name))

        rows = self._filter_since(rows, since)
        rows.sort(key=lambda row: row.timestamp or "", reverse=True)
        return rows[:limit]

    def list_goals(
        self,
        project: str,
        session_id: Optional[str] = None,
        limit: int = 100,
        since: Optional[str] = None,
    ) -> List[GoalSummary]:
        """List standing-goal revisions in a project."""
        rows: List[GoalSummary] = []
        for log, project_name in self._project_scope(project, session_id):
            rows.extend(extract_goals(log, project_name))

        rows = self._filter_since(rows, since)
        rows.sort(key=lambda row: row.timestamp or "", reverse=True)
        return rows[:limit]


_client: Optional[DeepSeekSessionsClient] = None


def get_client() -> DeepSeekSessionsClient:
    """Get or create the global client instance."""
    global _client
    if _client is None:
        _client = DeepSeekSessionsClient()
    return _client
