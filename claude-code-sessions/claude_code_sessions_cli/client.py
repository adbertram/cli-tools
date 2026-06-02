"""Claude Code Sessions client for reading local session data."""
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from .config import get_config
from .parsers import (
    parse_since,
    decode_project_path,
    encode_project_path,
    extract_project_name,
    parse_session_summary,
    parse_full_session,
    extract_tool_calls_from_session,
    extract_tool_calls_with_subagents,
    extract_subagents_from_session,
    extract_skill_invocations_from_session,
    extract_timeline_from_session,
    load_session_todos,
    search_session_file,
    in_date_window,
    extract_user_prompts,
)
from .models import (
    Project,
    Session,
    SessionSummary,
    ToolCallSummary,
    SubagentSummary,
    TodoSummary,
    SkillInvocation,
    TimelineEntry,
    SearchResult,
)


class ClientError(Exception):
    """Custom exception for Claude Code Sessions errors."""
    pass


class ClaudeCodeSessionsClient:
    """Client for reading Claude Code session data from ~/.claude."""

    def __init__(self):
        """Initialize the client."""
        self.config = get_config()
        self.claude_dir = Path.home() / '.claude'
        self.projects_dir = self.claude_dir / 'projects'
        self.todos_dir = self.claude_dir / 'todos'

        if not self.claude_dir.exists():
            raise ClientError(
                f"Claude Code data directory not found: {self.claude_dir}. "
                "Have you used Claude Code before?"
            )

    # ==================== Auth Methods ====================
    # Local file access - always authenticated

    def auth_login(self, force: bool = False) -> Dict[str, Any]:
        """No-op for local file access."""
        return {
            "success": True,
            "message": "Claude Code Sessions reads local files - no authentication required.",
        }

    def auth_logout(self) -> Dict[str, Any]:
        """No-op for local file access."""
        return {
            "success": True,
            "message": "No session to clear - local file access only.",
        }

    def auth_status(self) -> Dict[str, Any]:
        """Check if Claude Code data is accessible."""
        return {
            "authenticated": True,
            "claude_dir": str(self.claude_dir),
            "projects_dir_exists": self.projects_dir.exists(),
            "project_count": len(list(self.projects_dir.iterdir())) if self.projects_dir.exists() else 0,
        }

    # ==================== Project Methods ====================

    def list_projects(
        self,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Project]:
        """
        List all projects with session data.

        Args:
            limit: Maximum number of projects to return
            filters: Optional filter strings

        Returns:
            List of Project models
        """
        if not self.projects_dir.exists():
            return []

        projects = []

        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue

            encoded_path = project_dir.name
            full_path = decode_project_path(encoded_path)
            name = extract_project_name(encoded_path)

            # Count sessions
            session_files = list(project_dir.glob('*.jsonl'))
            session_count = len(session_files)

            if session_count == 0:
                continue

            # Find last activity
            last_activity = None
            latest_mtime = 0
            for sf in session_files:
                mtime = sf.stat().st_mtime
                if mtime > latest_mtime:
                    latest_mtime = mtime
                    last_activity = datetime.fromtimestamp(mtime).isoformat()

            projects.append(Project(
                name=name,
                full_path=full_path,
                encoded_path=encoded_path,
                session_count=session_count,
                last_activity=last_activity,
            ))

        # Sort by last activity (most recent first)
        projects.sort(key=lambda p: p.last_activity or '', reverse=True)

        return projects[:limit]

    def get_project(self, name: str) -> Project:
        """
        Get a project by name.

        Args:
            name: Project name to find

        Returns:
            Project model

        Raises:
            ClientError: If project not found
        """
        projects = self.list_projects(limit=1000)

        for project in projects:
            if project.name == name or project.encoded_path == name:
                return project

        raise ClientError(f"Project not found: {name}")

    def _get_project_dir(self, project_name: str) -> Path:
        """Get the project directory path by name or filesystem path."""
        # If it looks like a filesystem path, encode and check directly
        if project_name.startswith('/'):
            encoded = encode_project_path(project_name)
            project_dir = self.projects_dir / encoded
            if project_dir.exists():
                return project_dir
            raise ClientError(f"No sessions found for path: {project_name}")

        projects = self.list_projects(limit=1000)

        for project in projects:
            if project.name == project_name or project.encoded_path == project_name:
                return self.projects_dir / project.encoded_path

        raise ClientError(f"Project not found: {project_name}")

    # ==================== Session Methods ====================

    def list_sessions(
        self,
        project: Optional[str] = None,
        limit: int = 100,
        since: Optional[str] = None,
        filters: Optional[List[str]] = None,
        date_bounds: Optional[tuple] = None,
        min_tool_calls: Optional[int] = None,
    ) -> List[SessionSummary]:
        """
        List sessions for a project, or across all projects when project is None.

        Args:
            project: Project name. When None, returns sessions from all projects.
            limit: Maximum number of sessions
            since: Relative time filter (e.g., "5h", "1d")
            filters: Optional filter strings (currently unused in client)
            date_bounds: Optional (start_dt, end_dt) tuple. Sessions whose
                last_activity falls outside this local-tz window are dropped.
            min_tool_calls: Optional minimum tool_call_count. Sessions with
                fewer (or None/missing) are dropped.

        Returns:
            List of SessionSummary models sorted by last_activity desc.
        """
        if project is None:
            return self.list_all_sessions(
                limit=limit,
                since=since,
                date_bounds=date_bounds,
                min_tool_calls=min_tool_calls,
            )

        project_dir = self._get_project_dir(project)
        project_name = extract_project_name(project_dir.name)

        sessions = self._collect_sessions_from_dir(
            project_dir,
            project_name,
            since=since,
            date_bounds=date_bounds,
            min_tool_calls=min_tool_calls,
        )

        # Sort by last activity (most recent first)
        sessions.sort(key=lambda s: s.last_activity or '', reverse=True)

        return sessions[:limit]

    def list_all_sessions(
        self,
        limit: int = 100,
        since: Optional[str] = None,
        date_bounds: Optional[tuple] = None,
        min_tool_calls: Optional[int] = None,
    ) -> List[SessionSummary]:
        """
        List sessions across every project under projects_dir.

        Merges per-project results, sorts by last_activity desc, applies limit.
        """
        if not self.projects_dir.exists():
            return []

        merged: List[SessionSummary] = []
        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            project_name = extract_project_name(project_dir.name)
            merged.extend(
                self._collect_sessions_from_dir(
                    project_dir,
                    project_name,
                    since=since,
                    date_bounds=date_bounds,
                    min_tool_calls=min_tool_calls,
                )
            )

        merged.sort(key=lambda s: s.last_activity or '', reverse=True)
        return merged[:limit]

    def _collect_sessions_from_dir(
        self,
        project_dir: Path,
        project_name: str,
        since: Optional[str] = None,
        date_bounds: Optional[tuple] = None,
        min_tool_calls: Optional[int] = None,
    ) -> List[SessionSummary]:
        """Collect SessionSummary entries from one project dir, applying filters."""
        cutoff_time = parse_since(since) if since else None

        sessions: List[SessionSummary] = []

        for session_file in project_dir.glob('*.jsonl'):
            # Skip if file is too old based on mtime
            if cutoff_time:
                mtime = datetime.fromtimestamp(session_file.stat().st_mtime)
                if mtime < cutoff_time:
                    continue

            summary = parse_session_summary(session_file, project_name)
            if not summary:
                continue

            # Additional time filtering based on session content
            if cutoff_time and summary.last_activity:
                try:
                    session_time = datetime.fromisoformat(
                        summary.last_activity.replace('Z', '+00:00')
                    )
                    if session_time.replace(tzinfo=None) < cutoff_time:
                        continue
                except (ValueError, AttributeError):
                    pass

            # Date-window filter (local tz, against last_activity)
            if date_bounds is not None:
                if not summary.last_activity:
                    continue
                if not in_date_window(summary.last_activity, date_bounds):
                    continue

            # Min tool calls filter (None treated as 0)
            if min_tool_calls is not None and min_tool_calls > 0:
                count = summary.tool_call_count or 0
                if count < min_tool_calls:
                    continue

            sessions.append(summary)

        return sessions

    def list_conversations(
        self,
        project: str,
        session_id: Optional[str] = None,
        limit: int = 100,
        since: Optional[str] = None,
    ) -> List['ConversationSummary']:
        """
        List conversations across sessions or within a specific session.

        Args:
            project: Project name
            session_id: Optional session ID to filter conversations
            limit: Maximum number of conversations to return
            since: Relative time filter (e.g., "5h", "1d")

        Returns:
            List of conversation summaries
        """
        from .parsers import parse_conversation_summaries
        from .models.conversation import ConversationSummary

        project_dir = self._get_project_dir(project)
        project_name = extract_project_name(project_dir.name)

        # Parse since filter
        cutoff_time = None
        if since:
            cutoff_time = parse_since(since)

        conversations: List[ConversationSummary] = []

        # Get session files sorted by modification time (most recent first)
        session_files = sorted(
            project_dir.glob("*.jsonl"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )

        # Filter by session_id if provided
        if session_id:
            session_files = [f for f in session_files if f.stem == session_id]

        for session_file in session_files:
            # Skip if file is too old based on mtime
            if cutoff_time:
                mtime = datetime.fromtimestamp(session_file.stat().st_mtime)
                if mtime < cutoff_time:
                    continue

            conv_summaries = parse_conversation_summaries(session_file, project_name)

            # Filter by time if needed
            if cutoff_time:
                conv_summaries = [
                    c for c in conv_summaries
                    if c.ended_at and self._is_after_cutoff(c.ended_at, cutoff_time)
                ]

            conversations.extend(conv_summaries)

            if len(conversations) >= limit:
                break

        # Sort by created_at (most recent first)
        conversations.sort(key=lambda c: c.created_at or '', reverse=True)

        return conversations[:limit]

    def _is_after_cutoff(self, timestamp: str, cutoff: datetime) -> bool:
        """Check if a timestamp is after the cutoff time."""
        try:
            ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            return ts.replace(tzinfo=None) >= cutoff
        except (ValueError, AttributeError):
            return True  # Include if we can't parse

    def get_session(self, session_id: str) -> Session:
        """
        Get a full session by ID.

        Args:
            session_id: Session UUID

        Returns:
            Full Session model with messages, tool calls, etc.

        Raises:
            ClientError: If session not found
        """
        # Search all projects for the session
        if not self.projects_dir.exists():
            raise ClientError(f"Session not found: {session_id}")

        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue

            session_file = project_dir / f"{session_id}.jsonl"
            if session_file.exists():
                project_name = extract_project_name(project_dir.name)
                session = parse_full_session(session_file, project_name)
                if session:
                    return session

        raise ClientError(f"Session not found: {session_id}")

    def search_sessions(
        self,
        query: str,
        project: str,
        limit: int = 100,
        since: Optional[str] = None,
    ) -> List[SessionSummary]:
        """
        Search for sessions containing a query string.

        Args:
            query: Search query
            project: Project name (required)
            limit: Maximum results
            since: Relative time filter

        Returns:
            List of matching SessionSummary models
        """
        # Get all sessions first
        all_sessions = self.list_sessions(project, limit=1000, since=since)

        matching = []
        query_lower = query.lower()

        for summary in all_sessions:
            # Get full session to search content
            try:
                session = self.get_session(summary.id)

                # Search in messages
                for message in session.messages:
                    if query_lower in message.content.lower():
                        matching.append(summary)
                        break

            except ClientError:
                continue

        return matching[:limit]

    # ==================== Cross-Project Search ====================

    def search_all(
        self,
        query: str,
        project: Optional[str] = None,
        limit: int = 20,
        since: Optional[str] = None,
        max_matches_per_session: int = 5,
    ) -> List[SearchResult]:
        """
        Search for keywords across all session transcripts.

        Uses fast raw-text matching on JSONL files, then parses only
        matching lines for context snippets.

        Args:
            query: Search keyword(s) — case-insensitive
            project: Optional project name to restrict search
            limit: Maximum number of sessions to return
            since: Relative time filter (e.g., "7d", "30d")
            max_matches_per_session: Max snippets per session

        Returns:
            List of SearchResult models sorted by last_activity (newest first)
        """
        cutoff_time = None
        if since:
            cutoff_time = parse_since(since)

        results: List[SearchResult] = []

        # Determine which project dirs to search
        if project:
            project_dir = self._get_project_dir(project)
            project_dirs = [project_dir]
        else:
            project_dirs = [
                d for d in self.projects_dir.iterdir()
                if d.is_dir()
            ]

        for project_dir in project_dirs:
            project_name = extract_project_name(project_dir.name)

            for session_file in project_dir.glob('*.jsonl'):
                # Skip old files based on mtime
                if cutoff_time:
                    mtime = datetime.fromtimestamp(session_file.stat().st_mtime)
                    if mtime < cutoff_time:
                        continue

                result = search_session_file(
                    session_file, query, project_name, max_matches_per_session,
                )
                if result:
                    results.append(result)

        # Sort by last_activity (newest first)
        results.sort(key=lambda r: r.last_activity, reverse=True)

        return results[:limit]

    # ==================== Subagent Activity Methods ====================

    def list_subagent_activity(
        self,
        project: str,
        limit: int = 100,
        since: Optional[str] = None,
        filters: Optional[List[str]] = None,
    ) -> List[SubagentSummary]:
        """
        List all subagent invocations for a project.

        Args:
            project: Project name (required)
            limit: Maximum results
            since: Relative time filter
            filters: Optional filter strings

        Returns:
            List of SubagentSummary models
        """
        project_dir = self._get_project_dir(project)
        project_name = extract_project_name(project_dir.name)

        # Parse since filter
        cutoff_time = None
        if since:
            cutoff_time = parse_since(since)

        subagents = []

        for session_file in project_dir.glob('*.jsonl'):
            # Skip if file is too old
            if cutoff_time:
                mtime = datetime.fromtimestamp(session_file.stat().st_mtime)
                if mtime < cutoff_time:
                    continue

            session_subagents = extract_subagents_from_session(session_file, project_name)

            for sa in session_subagents:
                # Time filtering
                if cutoff_time and sa.get('timestamp'):
                    try:
                        sa_time = datetime.fromisoformat(
                            sa['timestamp'].replace('Z', '+00:00')
                        )
                        if sa_time.replace(tzinfo=None) < cutoff_time:
                            continue
                    except (ValueError, AttributeError):
                        pass

                subagents.append(SubagentSummary(
                    id=sa['id'],
                    session_id=sa['session_id'],
                    project=sa['project'],
                    timestamp=sa['timestamp'],
                    type=sa['type'],
                    prompt=sa['prompt'],
                    description=sa.get('description'),
                    model=sa.get('model'),
                    status=sa['status'],
                    message_count=sa['message_count'],
                    agent_id=sa.get('agent_id'),
                    tool_calls=sa.get('tool_calls', []),
                    errors=sa.get('errors', []),
                    total_input_tokens=sa.get('total_input_tokens', 0),
                    total_output_tokens=sa.get('total_output_tokens', 0),
                    total_cache_read_tokens=sa.get('total_cache_read_tokens', 0),
                    total_cache_creation_tokens=sa.get('total_cache_creation_tokens', 0),
                ))

        # Sort by timestamp (most recent first)
        subagents.sort(key=lambda s: s.timestamp or '', reverse=True)

        return subagents[:limit]

    def get_subagent(self, subagent_id: str, project: str) -> Dict[str, Any]:
        """
        Get full details for a subagent invocation.

        Args:
            subagent_id: Subagent/tool call ID
            project: Project name

        Returns:
            Full subagent data with messages
        """
        # Find the subagent in sessions
        all_subagents = self.list_subagent_activity(project, limit=10000)

        for sa in all_subagents:
            if sa.id == subagent_id:
                # Get the full session to extract subagent messages
                session = self.get_session(sa.session_id)
                subagent_data = session.subagents.get(subagent_id)

                if subagent_data:
                    return subagent_data.model_dump()

                # Return summary if full data not available
                return sa.model_dump()

        raise ClientError(f"Subagent not found: {subagent_id}")

    # ==================== Tool Calls Methods ====================

    def list_tool_calls(
        self,
        project: str,
        limit: int = 100,
        since: Optional[str] = None,
        filters: Optional[List[str]] = None,
        include_subagents: bool = False,
    ) -> List[ToolCallSummary]:
        """
        List all tool calls for a project.

        Args:
            project: Project name (required)
            limit: Maximum results
            since: Relative time filter
            filters: Optional filter strings
            include_subagents: Include tool calls from subagent sessions

        Returns:
            List of ToolCallSummary models
        """
        project_dir = self._get_project_dir(project)
        project_name = extract_project_name(project_dir.name)

        # Parse since filter
        cutoff_time = None
        if since:
            cutoff_time = parse_since(since)

        tool_calls = []

        for session_file in project_dir.glob('*.jsonl'):
            # Skip if file is too old
            if cutoff_time:
                mtime = datetime.fromtimestamp(session_file.stat().st_mtime)
                if mtime < cutoff_time:
                    continue

            # Use appropriate extraction function
            if include_subagents:
                session_tool_calls = extract_tool_calls_with_subagents(session_file, project_name)
            else:
                session_tool_calls = extract_tool_calls_from_session(session_file, project_name)

            for tc in session_tool_calls:
                # Time filtering
                if cutoff_time and tc.get('timestamp'):
                    try:
                        tc_time = datetime.fromisoformat(
                            tc['timestamp'].replace('Z', '+00:00')
                        )
                        if tc_time.replace(tzinfo=None) < cutoff_time:
                            continue
                    except (ValueError, AttributeError):
                        pass

                tool_calls.append(ToolCallSummary(
                    id=tc['id'],
                    session_id=tc['session_id'],
                    project=tc['project'],
                    timestamp=tc['timestamp'],
                    tool=tc['tool'],
                    status=tc['status'],
                    is_sidechain=tc['is_sidechain'],
                    parent_tool_call_id=tc.get('parent_tool_call_id'),
                    input=tc.get('input'),
                    result=tc.get('result'),
                    error=tc.get('error'),
                ))

        # Sort by timestamp (most recent first)
        tool_calls.sort(key=lambda t: t.timestamp or '', reverse=True)

        return tool_calls[:limit]

    def get_tool_call(self, tool_call_id: str, project: str) -> ToolCallSummary:
        """
        Get details for a specific tool call.

        Args:
            tool_call_id: Tool call ID
            project: Project name

        Returns:
            ToolCallSummary with full details
        """
        all_tool_calls = self.list_tool_calls(project, limit=10000)

        for tc in all_tool_calls:
            if tc.id == tool_call_id:
                return tc

        raise ClientError(f"Tool call not found: {tool_call_id}")

    # ==================== Skills Methods ====================

    def list_skills(
        self,
        project: str,
        limit: int = 100,
        since: Optional[str] = None,
        filters: Optional[List[str]] = None,
    ) -> List[SkillInvocation]:
        """
        List all skill/command invocations for a project.

        Args:
            project: Project name (required)
            limit: Maximum results
            since: Relative time filter
            filters: Optional filter strings

        Returns:
            List of SkillInvocation models
        """
        project_dir = self._get_project_dir(project)
        project_name = extract_project_name(project_dir.name)

        # Parse since filter
        cutoff_time = None
        if since:
            cutoff_time = parse_since(since)

        skills = []

        for session_file in project_dir.glob('*.jsonl'):
            # Skip if file is too old
            if cutoff_time:
                mtime = datetime.fromtimestamp(session_file.stat().st_mtime)
                if mtime < cutoff_time:
                    continue

            session_skills = extract_skill_invocations_from_session(session_file, project_name)

            for sk in session_skills:
                # Time filtering
                if cutoff_time and sk.get('timestamp'):
                    try:
                        sk_time = datetime.fromisoformat(
                            sk['timestamp'].replace('Z', '+00:00')
                        )
                        if sk_time.replace(tzinfo=None) < cutoff_time:
                            continue
                    except (ValueError, AttributeError):
                        pass

                skills.append(SkillInvocation(
                    id=sk['id'],
                    session_id=sk['session_id'],
                    project=sk['project'],
                    timestamp=sk['timestamp'],
                    name=sk['name'],
                    args=sk.get('args'),
                    message=sk.get('message'),
                ))

        # Sort by timestamp (most recent first)
        skills.sort(key=lambda s: s.timestamp or '', reverse=True)

        return skills[:limit]

    def get_skill(self, skill_id: str, project: str) -> SkillInvocation:
        """
        Get details for a specific skill invocation.

        Args:
            skill_id: Skill invocation ID
            project: Project name

        Returns:
            SkillInvocation with full details

        Raises:
            ClientError: If skill not found
        """
        all_skills = self.list_skills(project, limit=10000)

        for skill in all_skills:
            if skill.id == skill_id:
                return skill

        raise ClientError(f"Skill invocation not found: {skill_id}")

    # ==================== Timeline Methods ====================

    def get_timeline(
        self,
        session_id: str,
        project: str,
        limit: int = 500,
        show_thinking: bool = False,
    ) -> List[TimelineEntry]:
        """
        Get a unified timeline of all activities for a session.

        Args:
            session_id: Session UUID
            project: Project name
            limit: Maximum entries
            show_thinking: Include Claude's thinking/reasoning blocks (default: False)

        Returns:
            List of TimelineEntry models sorted chronologically
        """
        project_dir = self._get_project_dir(project)
        project_name = extract_project_name(project_dir.name)

        session_file = project_dir / f"{session_id}.jsonl"
        if not session_file.exists():
            raise ClientError(f"Session not found: {session_id}")

        timeline = extract_timeline_from_session(session_file, project_name, show_thinking=show_thinking)

        return timeline[:limit]

    def list_timeline(
        self,
        project: str,
        limit: int = 200,
        since: Optional[str] = None,
    ) -> List[TimelineEntry]:
        """
        Get a combined timeline across recent sessions.

        Args:
            project: Project name (required)
            limit: Maximum entries
            since: Relative time filter

        Returns:
            List of TimelineEntry models sorted chronologically
        """
        project_dir = self._get_project_dir(project)
        project_name = extract_project_name(project_dir.name)

        # Parse since filter
        cutoff_time = None
        if since:
            cutoff_time = parse_since(since)

        all_entries = []

        for session_file in project_dir.glob('*.jsonl'):
            # Skip if file is too old
            if cutoff_time:
                mtime = datetime.fromtimestamp(session_file.stat().st_mtime)
                if mtime < cutoff_time:
                    continue

            timeline = extract_timeline_from_session(session_file, project_name)

            for entry in timeline:
                # Time filtering
                if cutoff_time and entry.timestamp:
                    try:
                        entry_time = datetime.fromisoformat(
                            entry.timestamp.replace('Z', '+00:00')
                        )
                        if entry_time.replace(tzinfo=None) < cutoff_time:
                            continue
                    except (ValueError, AttributeError):
                        pass

                all_entries.append(entry)

        # Sort by timestamp (most recent first)
        all_entries.sort(key=lambda e: e.timestamp or '', reverse=True)

        return all_entries[:limit]  # Return most recent N entries

    # ==================== Todos Methods ====================

    def list_todos(
        self,
        project: str,
        limit: int = 100,
        since: Optional[str] = None,
        filters: Optional[List[str]] = None,
    ) -> List[TodoSummary]:
        """
        List all todos for a project.

        Args:
            project: Project name (required)
            limit: Maximum results
            since: Relative time filter
            filters: Optional filter strings

        Returns:
            List of TodoSummary models
        """
        # Get sessions to find their todos
        sessions = self.list_sessions(project, limit=1000, since=since)

        todos = []

        for session in sessions:
            session_todos = load_session_todos(session.id)

            for todo in session_todos:
                todos.append(TodoSummary(
                    id=todo.id,
                    session_id=session.id,
                    project=project,
                    content=todo.content,
                    active_form=todo.active_form,
                    status=todo.status.value,
                    priority=todo.priority,
                ))

        return todos[:limit]

    def get_todo(self, project: str, todo_id: str) -> Optional[TodoSummary]:
        """
        Get a specific todo by ID.

        Args:
            project: Project name (required)
            todo_id: Todo ID

        Returns:
            TodoSummary or None if not found
        """
        # Search through all sessions to find the todo
        sessions = self.list_sessions(project, limit=1000)

        for session in sessions:
            session_todos = load_session_todos(session.id)

            for todo in session_todos:
                if todo.id == todo_id:
                    return TodoSummary(
                        id=todo.id,
                        session_id=session.id,
                        project=project,
                        content=todo.content,
                        active_form=todo.active_form,
                        status=todo.status.value,
                        priority=todo.priority,
                    )

        return None


# Module-level client instance - singleton pattern
_client: Optional[ClaudeCodeSessionsClient] = None


def get_client() -> ClaudeCodeSessionsClient:
    """Get or create the global client instance."""
    global _client
    if _client is None:
        _client = ClaudeCodeSessionsClient()
    return _client
