"""Client for local OpenAI Codex session transcript files."""
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import get_config
from .models import (
    ConversationSummary,
    Project,
    SessionDetail,
    SessionSummary,
    SkillInvocation,
    SubagentActivity,
    TimelineEvent,
    TimelineEventType,
    TodoItem,
    ToolCall,
    create_conversation_summary,
    create_project,
    create_session_detail,
    create_session_summary,
    create_skill_invocation,
    create_subagent_activity,
    create_timeline_event,
    create_todo_item,
    create_tool_call,
)
from .parsers import (
    ParsedRollout,
    conversation_count,
    conversation_id_for_record,
    encode_project_path,
    event_messages,
    extract_skill_mentions,
    has_errors,
    iter_rollout_paths,
    load_rollout,
    max_timestamp,
    message_records,
    output_for_record,
    output_records_by_call_id,
    parse_arguments,
    project_name,
    response_items,
    session_text,
    status_for_output,
    text_from_content,
    token_totals,
    tool_call_records,
)


class ClientError(Exception):
    """Custom exception for CodexSessions errors."""


class CodexSessionsClient:
    """Read and query Codex rollout JSONL files."""

    def __init__(self, codex_home: Optional[Path] = None):
        self.config = get_config()
        self.codex_home = Path(codex_home).expanduser() if codex_home else self.config.codex_home
        self.load_errors: List[str] = []

    def auth_status(self) -> Dict[str, Any]:
        exists = self.codex_home.exists()
        return {
            "authenticated": exists,
            "codex_home": str(self.codex_home),
            "sessions_dir": str(self.codex_home / "sessions"),
            "cli_command": self.config.cli_command,
            "cli_available": self.config.is_cli_available(),
            "cli_version": self.config.get_cli_version(),
        }

    def list_projects(self, limit: int = 100, filters: Optional[List[str]] = None) -> List[Project]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for parsed in self._load_rollouts():
            cwd = parsed.meta["cwd"]
            entry = grouped.get(cwd)
            if entry is None:
                entry = {
                    "name": project_name(cwd),
                    "full_path": cwd,
                    "encoded_path": encode_project_path(cwd),
                    "session_count": 0,
                    "last_activity": parsed.meta["timestamp"],
                }
                grouped[cwd] = entry
            entry["session_count"] += 1
            entry["last_activity"] = max(
                [entry["last_activity"], max_timestamp(parsed.records)],
                key=self._timestamp_sort_key,
            )
        projects = [create_project(item) for item in grouped.values()]
        return self._apply_limit(self._sort_by_last_activity(projects), limit)

    def get_project(self, name: str) -> Project:
        for project in self.list_projects(limit=10_000):
            if project.name == name or project.full_path == name:
                return project
        raise ClientError(f"Project not found: {name}")

    def list_sessions(
        self,
        project: Optional[str] = None,
        project_path: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
        filters: Optional[List[str]] = None,
        date_window: Optional[Tuple[datetime, datetime]] = None,
        min_tool_calls: Optional[int] = None,
    ) -> List[SessionSummary]:
        sessions = [
            self._session_summary(parsed)
            for parsed in self._load_rollouts()
            if self._matches_project(parsed, project, project_path)
            and self._matches_since(max_timestamp(parsed.records), since)
            and self._matches_date_window(max_timestamp(parsed.records), date_window)
        ]
        if min_tool_calls is not None:
            sessions = [s for s in sessions if s.tool_call_count >= min_tool_calls]
        return self._apply_limit(self._sort_by_last_activity(sessions), limit)

    def get_session(self, session_id: str) -> SessionDetail:
        parsed = self._get_rollout(session_id)
        summary = self._session_summary(parsed).model_dump()
        summary["records"] = [record.raw for record in parsed.records]
        summary["messages"] = [
            event
            for event in self.get_timeline(session_id)
            if event.event_type == TimelineEventType.MESSAGE
        ]
        summary["tool_calls"] = self.list_tool_calls(session_id=session_id)
        return create_session_detail(summary)

    def search_sessions(
        self,
        query: str,
        project: Optional[str] = None,
        project_path: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
    ) -> List[SessionSummary]:
        normalized = query.casefold()
        sessions = [
            self._session_summary(parsed)
            for parsed in self._load_rollouts()
            if normalized in session_text(parsed).casefold()
            and self._matches_project(parsed, project, project_path)
            and self._matches_since(max_timestamp(parsed.records), since)
        ]
        return self._apply_limit(self._sort_by_last_activity(sessions), limit)

    def list_conversations(
        self,
        project: Optional[str] = None,
        project_path: Optional[str] = None,
        session_id: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
    ) -> List[ConversationSummary]:
        conversations: List[ConversationSummary] = []
        for parsed in self._load_rollouts():
            if session_id and parsed.meta["id"] != session_id:
                continue
            if not self._matches_project(parsed, project, project_path):
                continue
            if not self._matches_since(max_timestamp(parsed.records), since):
                continue
            turn_records = [record for record in parsed.records if record.record_type == "turn_context"]
            if not turn_records:
                conversations.append(self._conversation_summary(parsed, 1))
            for index, _record in enumerate(turn_records, start=1):
                conversations.append(self._conversation_summary(parsed, index))
        return self._apply_limit(self._sort_by_last_activity(conversations), limit)

    def get_conversation(self, conversation_id: str) -> ConversationSummary:
        session_id, _, index_text = conversation_id.partition(":")
        if not session_id or not index_text:
            raise ClientError("Conversation ID must use session_id:conversation_number")
        index = int(index_text)
        parsed = self._get_rollout(session_id)
        return self._conversation_summary(parsed, index)

    def list_tool_calls(
        self,
        project: Optional[str] = None,
        project_path: Optional[str] = None,
        session_id: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
        include_subagents: bool = False,
    ) -> List[ToolCall]:
        calls: List[ToolCall] = []
        for parsed in self._matching_rollouts(project, project_path, session_id, since):
            outputs = output_records_by_call_id(parsed)
            for record in tool_call_records(parsed):
                payload = record.payload
                call_id = payload["call_id"]
                output_record = outputs.get(call_id)
                args = parse_arguments(payload["arguments"])
                calls.append(
                    create_tool_call(
                        {
                            "id": call_id,
                            "session_id": parsed.meta["id"],
                            "conversation_id": conversation_id_for_record(parsed.records, record),
                            "time": record.timestamp,
                            "tool": payload["name"],
                            "name": payload["name"],
                            "status": status_for_output(output_record),
                            "arguments": args,
                            "output": output_for_record(output_record),
                            "cwd": self._tool_cwd(args, output_record),
                            "exit_code": self._tool_exit_code(output_record),
                        }
                    )
                )
        return self._apply_limit(calls, limit)

    def get_tool_call(self, tool_call_id: str) -> ToolCall:
        for call in self.list_tool_calls(limit=10_000):
            if call.id == tool_call_id:
                return call
        raise ClientError(f"Tool call not found: {tool_call_id}")

    def list_subagent_activity(
        self,
        project: Optional[str] = None,
        project_path: Optional[str] = None,
        session_id: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
    ) -> List[SubagentActivity]:
        activities: List[SubagentActivity] = []
        for call in self.list_tool_calls(project, project_path, session_id, since, limit=10_000):
            if call.name in {"spawn_agent", "Task"}:
                output = call.output if isinstance(call.output, dict) else {}
                activities.append(
                    create_subagent_activity(
                        {
                            "id": call.id,
                            "session_id": call.session_id,
                            "conversation_id": call.conversation_id,
                            "time": call.time,
                            "agent_type": call.arguments.get("agent_type"),
                            "name": output.get("nickname") or call.arguments.get("description"),
                            "message": call.arguments.get("message") or call.arguments.get("prompt"),
                            "status": call.status,
                            "agent_id": output.get("agent_id"),
                            "output": call.output,
                        }
                    )
                )
        return self._apply_limit(activities, limit)

    def get_subagent_activity(self, activity_id: str) -> SubagentActivity:
        for activity in self.list_subagent_activity(limit=10_000):
            if activity.id == activity_id:
                return activity
        raise ClientError(f"Subagent activity not found: {activity_id}")

    def list_todos(
        self,
        project: Optional[str] = None,
        project_path: Optional[str] = None,
        session_id: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
    ) -> List[TodoItem]:
        todos: List[TodoItem] = []
        for parsed in self._matching_rollouts(project, project_path, session_id, since):
            for record in tool_call_records(parsed):
                payload = record.payload
                if payload["name"] != "update_plan":
                    continue
                args = parse_arguments(payload["arguments"])
                plan = args["plan"]
                for index, item in enumerate(plan, start=1):
                    todos.append(
                        create_todo_item(
                            {
                                "id": f"{parsed.meta['id']}:{payload['call_id']}:{index}",
                                "session_id": parsed.meta["id"],
                                "conversation_id": conversation_id_for_record(parsed.records, record),
                                "time": record.timestamp,
                                "content": item["step"],
                                "status": item["status"],
                                "source_call_id": payload["call_id"],
                            }
                        )
                    )
        return self._apply_limit(todos, limit)

    def get_todo(self, todo_id: str) -> TodoItem:
        for todo in self.list_todos(limit=10_000):
            if todo.id == todo_id:
                return todo
        raise ClientError(f"Todo not found: {todo_id}")

    def list_skills(
        self,
        project: Optional[str] = None,
        project_path: Optional[str] = None,
        session_id: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
    ) -> List[SkillInvocation]:
        skills: List[SkillInvocation] = []
        for parsed in self._matching_rollouts(project, project_path, session_id, since):
            for record in event_messages(parsed, "user_message"):
                text = str(record.payload["message"])
                for name in extract_skill_mentions(text):
                    skills.append(
                        create_skill_invocation(
                            {
                                "id": f"{parsed.meta['id']}:{record.line_number}:{name}",
                                "session_id": parsed.meta["id"],
                                "conversation_id": conversation_id_for_record(parsed.records, record),
                                "time": record.timestamp,
                                "name": name,
                                "source": "user_message",
                                "text": text,
                            }
                        )
                    )
        return self._apply_limit(skills, limit)

    def get_skill(self, skill_id: str) -> SkillInvocation:
        for skill in self.list_skills(limit=10_000):
            if skill.id == skill_id:
                return skill
        raise ClientError(f"Skill invocation not found: {skill_id}")

    def list_timeline(
        self,
        project: Optional[str] = None,
        project_path: Optional[str] = None,
        session_id: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
    ) -> List[TimelineEvent]:
        events: List[TimelineEvent] = []
        for parsed in self._matching_rollouts(project, project_path, session_id, since):
            events.extend(self._timeline_for_rollout(parsed))
        events.sort(key=lambda event: self._timestamp_sort_key(event.time))
        return self._apply_limit(events, limit)

    def get_timeline(self, session_id: str, limit: int = 500) -> List[TimelineEvent]:
        return self._apply_limit(self._timeline_for_rollout(self._get_rollout(session_id)), limit)

    def _timeline_for_rollout(self, parsed: ParsedRollout) -> List[TimelineEvent]:
        events: List[TimelineEvent] = []
        session_id = parsed.meta["id"]
        outputs = output_records_by_call_id(parsed)
        for record in parsed.records:
            payload = record.payload
            base = {
                "time": record.timestamp,
                "session_id": session_id,
                "conversation_id": conversation_id_for_record(parsed.records, record),
                "raw_type": record.record_type,
            }
            if record.record_type == "session_meta":
                events.append(
                    create_timeline_event(
                        {
                            **base,
                            "id": f"{session_id}:session",
                            "event_type": TimelineEventType.SESSION,
                            "name": project_name(parsed.meta["cwd"]),
                            "text": parsed.meta["cwd"],
                        }
                    )
                )
            elif record.record_type == "turn_context":
                events.append(
                    create_timeline_event(
                        {
                            **base,
                            "id": f"{session_id}:turn:{record.line_number}",
                            "event_type": TimelineEventType.TURN,
                            "name": payload["turn_id"],
                            "text": payload.get("cwd"),
                        }
                    )
                )
            elif record.record_type == "event_msg":
                events.append(self._event_msg_timeline_event(record, base))
            elif record.record_type == "response_item" and payload["type"] == "message":
                events.append(
                    create_timeline_event(
                        {
                            **base,
                            "id": f"{session_id}:message:{record.line_number}",
                            "event_type": TimelineEventType.MESSAGE,
                            "role": payload["role"],
                            "name": payload.get("phase"),
                            "text": text_from_content(payload.get("content")),
                        }
                    )
                )
            elif record.record_type == "response_item" and payload["type"] == "function_call":
                output_record = outputs.get(payload["call_id"])
                events.append(
                    create_timeline_event(
                        {
                            **base,
                            "id": payload["call_id"],
                            "event_type": TimelineEventType.TOOL_CALL,
                            "name": payload["name"],
                            "status": status_for_output(output_record),
                            "input": parse_arguments(payload["arguments"]),
                            "output": output_for_record(output_record),
                        }
                    )
                )
            elif record.record_type == "response_item" and payload["type"] == "function_call_output":
                events.append(
                    create_timeline_event(
                        {
                            **base,
                            "id": f"{payload['call_id']}:output",
                            "event_type": TimelineEventType.TOOL_RESULT,
                            "name": payload["call_id"],
                            "status": "completed",
                            "output": output_for_record(record),
                        }
                    )
                )
        events.sort(key=lambda event: (self._timestamp_sort_key(event.time), event.id))
        return events

    def _event_msg_timeline_event(self, record, base: Dict[str, Any]) -> TimelineEvent:
        payload = record.payload
        event_type = payload["type"]
        if event_type == "user_message":
            category = TimelineEventType.MESSAGE
            text = payload["message"]
        elif event_type == "agent_message":
            category = TimelineEventType.MESSAGE
            text = payload["message"]
        elif event_type == "exec_command_end":
            category = TimelineEventType.TOOL_RESULT
            text = payload.get("aggregated_output") or payload.get("stdout") or payload.get("stderr")
        else:
            category = TimelineEventType.EVENT
            text = payload.get("message")
        return create_timeline_event(
            {
                **base,
                "id": f"{base['session_id']}:event:{record.line_number}",
                "event_type": category,
                "name": event_type,
                "status": payload.get("status"),
                "text": text,
                "output": payload if event_type == "exec_command_end" else None,
            }
        )

    def _session_summary(self, parsed: ParsedRollout) -> SessionSummary:
        meta = parsed.meta
        tokens = token_totals(parsed)
        data = {
            "id": meta["id"],
            "project": project_name(meta["cwd"]),
            "project_path": meta["cwd"],
            "created_at": meta["timestamp"],
            "last_activity": max_timestamp(parsed.records),
            "message_count": len(message_records(parsed)),
            "tool_call_count": len(tool_call_records(parsed)),
            "has_errors": has_errors(parsed),
            "has_subagents": any(record.payload["name"] in {"spawn_agent", "Task"} for record in tool_call_records(parsed)),
            "conversation_count": conversation_count(parsed.records),
            "current_conversation_id": conversation_count(parsed.records),
            "path": str(parsed.path),
            "source": meta.get("source"),
            "cli_version": meta.get("cli_version"),
            "model_provider": meta.get("model_provider"),
            "git_branch": self._git_value(meta, "branch"),
            "git_sha": self._git_value(meta, "commit_hash"),
            "git_origin_url": self._git_value(meta, "repository_url"),
            **tokens,
        }
        return create_session_summary(data)

    def _conversation_summary(self, parsed: ParsedRollout, index: int) -> ConversationSummary:
        events = self._records_for_conversation(parsed.records, index)
        messages = [
            record
            for record in events
            if record.record_type == "response_item"
            and record.payload.get("type") == "message"
            and record.payload.get("role") in {"user", "assistant"}
        ]
        calls = [
            record
            for record in events
            if record.record_type == "response_item" and record.payload.get("type") == "function_call"
        ]
        summary = text_from_content(messages[0].payload.get("content")) if messages else None
        return create_conversation_summary(
            {
                "id": f"{parsed.meta['id']}:{index}",
                "session_id": parsed.meta["id"],
                "conversation_id": index,
                "project": project_name(parsed.meta["cwd"]),
                "project_path": parsed.meta["cwd"],
                "created_at": events[0].timestamp,
                "last_activity": max((record.timestamp for record in events), key=self._timestamp_sort_key),
                "message_count": len(messages),
                "tool_call_count": len(calls),
                "summary": summary,
            }
        )

    def _records_for_conversation(self, records, index: int):
        events = []
        current = 1
        turn_index = 0
        for record in records:
            if record.record_type == "turn_context":
                turn_index += 1
                current = turn_index
            if current == index:
                events.append(record)
        return events

    def _load_rollouts(self) -> List[ParsedRollout]:
        self.load_errors = []
        if not self.codex_home.exists():
            return []
        rollouts = []
        for path in iter_rollout_paths(self.codex_home):
            try:
                rollouts.append(load_rollout(path))
            except FileNotFoundError:
                self.load_errors.append(f"{path}: file not found")
            except ValueError as error:
                self.load_errors.append(str(error))
        rollouts.sort(key=lambda parsed: self._timestamp_sort_key(max_timestamp(parsed.records)), reverse=True)
        return rollouts

    def _get_rollout(self, session_id: str) -> ParsedRollout:
        for parsed in self._load_rollouts():
            if parsed.meta["id"] == session_id:
                return parsed
        raise ClientError(f"Session not found: {session_id}")

    def _matching_rollouts(
        self,
        project: Optional[str],
        project_path: Optional[str],
        session_id: Optional[str],
        since: Optional[str],
    ) -> List[ParsedRollout]:
        return [
            parsed
            for parsed in self._load_rollouts()
            if (session_id is None or parsed.meta["id"] == session_id)
            and self._matches_project(parsed, project, project_path)
            and self._matches_since(max_timestamp(parsed.records), since)
        ]

    def _matches_project(
        self,
        parsed: ParsedRollout,
        project: Optional[str],
        project_path: Optional[str],
    ) -> bool:
        if project_path is not None and parsed.meta["cwd"] != project_path:
            return False
        if project is not None and project_name(parsed.meta["cwd"]) != project:
            return False
        return True

    def _matches_date_window(
        self,
        timestamp: str,
        date_window: Optional[Tuple[datetime, datetime]],
    ) -> bool:
        if date_window is None:
            return True
        from .parsers import iso_to_epoch

        start_dt, end_dt = date_window
        epoch = iso_to_epoch(timestamp)
        return start_dt.timestamp() <= epoch <= end_dt.timestamp()

    def _matches_since(self, timestamp: str, since: Optional[str]) -> bool:
        if since is None:
            return True
        threshold = self._since_threshold(since)
        return self._timestamp_sort_key(timestamp) >= threshold

    def _since_threshold(self, since: str) -> float:
        unit = since[-1]
        amount = int(since[:-1])
        seconds_by_unit = {"h": 3600, "d": 86400, "w": 604800}
        if unit not in seconds_by_unit:
            raise ClientError("Use --since with h, d, or w suffix, such as 5h, 1d, or 2w")
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).timestamp() - amount * seconds_by_unit[unit]

    def _sort_by_last_activity(self, items):
        return sorted(items, key=lambda item: self._timestamp_sort_key(item.last_activity), reverse=True)

    def _timestamp_sort_key(self, timestamp: str) -> float:
        from .parsers import iso_to_epoch

        return iso_to_epoch(timestamp)

    def _apply_limit(self, items: List[Any], limit: int) -> List[Any]:
        return items[:limit]

    def _git_value(self, meta: Dict[str, Any], key: str) -> Optional[str]:
        git = meta.get("git")
        if isinstance(git, dict):
            value = git.get(key)
            return str(value) if value is not None else None
        return None

    def _tool_cwd(self, args: Dict[str, Any], output_record) -> Optional[str]:
        if output_record and output_record.record_type == "event_msg":
            return output_record.payload.get("cwd")
        cwd = args.get("cwd")
        return str(cwd) if cwd is not None else None

    def _tool_exit_code(self, output_record) -> Optional[int]:
        if output_record and output_record.record_type == "event_msg":
            exit_code = output_record.payload.get("exit_code")
            if isinstance(exit_code, int):
                return exit_code
        return None


def get_client() -> CodexSessionsClient:
    return CodexSessionsClient()
