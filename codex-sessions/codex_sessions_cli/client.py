"""Client for local OpenAI Codex session transcript files."""
import heapq
import itertools
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
    RolloutIndex,
    ROLLOUT_PREFIX,
    ROLLOUT_SUFFIX,
    SESSION_SUBDIRS,
    conversation_count,
    conversation_id_for_record,
    encode_project_path,
    event_messages,
    extract_skill_mentions,
    has_errors,
    iter_rollout_paths,
    load_rollout_index,
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

    CONVERSATION_SUMMARY_MAX_CHARS = 160

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
        for index in self._load_rollout_indexes():
            cwd = index.cwd
            entry = grouped.get(cwd)
            if entry is None:
                entry = {
                    "name": project_name(cwd),
                    "full_path": cwd,
                    "encoded_path": encode_project_path(cwd),
                    "session_count": 0,
                    "last_activity": index.last_activity,
                }
                grouped[cwd] = entry
            entry["session_count"] += 1
            entry["last_activity"] = max(
                [entry["last_activity"], index.last_activity],
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
        sessions: List[SessionSummary] = []
        for index in self._matching_rollout_indexes(project, project_path, since, date_window):
            parsed = load_rollout(index.path)
            summary = self._session_summary(parsed)
            if min_tool_calls is not None and summary.tool_call_count < min_tool_calls:
                continue
            sessions.append(summary)
            if len(sessions) >= limit:
                break
        return sessions[:limit]

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
        for rollout_index in self._matching_rollout_indexes(project, project_path, since):
            if session_id and rollout_index.session_id != session_id:
                continue
            parsed = load_rollout(rollout_index.path)
            turn_records = [record for record in parsed.records if record.record_type == "turn_context"]
            if not turn_records:
                conversations.append(self._conversation_summary(parsed, 1))
                if len(conversations) >= limit:
                    return conversations[:limit]
            for conversation_index, _record in enumerate(turn_records, start=1):
                conversations.append(self._conversation_summary(parsed, conversation_index))
                if len(conversations) >= limit:
                    return conversations[:limit]
        return conversations[:limit]

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
                if len(calls) >= limit:
                    return calls[:limit]
        return self._apply_limit(calls, limit)

    def get_tool_call(self, tool_call_id: str) -> ToolCall:
        for parsed in self._load_rollouts():
            outputs = output_records_by_call_id(parsed)
            for record in tool_call_records(parsed):
                payload = record.payload
                if payload["call_id"] != tool_call_id:
                    continue
                output_record = outputs.get(tool_call_id)
                args = parse_arguments(payload["arguments"])
                return create_tool_call(
                    {
                        "id": tool_call_id,
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
        for parsed in self._matching_rollouts(project, project_path, session_id, since):
            outputs = output_records_by_call_id(parsed)
            for record in tool_call_records(parsed):
                payload = record.payload
                if payload["name"] not in {"spawn_agent", "Task"}:
                    continue
                arguments = parse_arguments(payload["arguments"])
                output_record = outputs.get(payload["call_id"])
                output = output_for_record(output_record)
                output_data = output if isinstance(output, dict) else {}
                activities.append(
                    create_subagent_activity(
                        {
                            "id": payload["call_id"],
                            "session_id": parsed.meta["id"],
                            "conversation_id": conversation_id_for_record(parsed.records, record),
                            "time": record.timestamp,
                            "agent_type": arguments.get("agent_type"),
                            "name": output_data.get("nickname") or arguments.get("description"),
                            "message": arguments.get("message") or arguments.get("prompt"),
                            "status": status_for_output(output_record),
                            "agent_id": output_data.get("agent_id"),
                            "output": output,
                        }
                    )
                )
                if len(activities) >= limit:
                    return activities[:limit]
        return self._apply_limit(activities, limit)

    def get_subagent_activity(self, activity_id: str) -> SubagentActivity:
        for parsed in self._load_rollouts():
            outputs = output_records_by_call_id(parsed)
            for record in tool_call_records(parsed):
                payload = record.payload
                if payload["call_id"] != activity_id or payload["name"] not in {"spawn_agent", "Task"}:
                    continue
                arguments = parse_arguments(payload["arguments"])
                output_record = outputs.get(payload["call_id"])
                output = output_for_record(output_record)
                output_data = output if isinstance(output, dict) else {}
                return create_subagent_activity(
                    {
                        "id": payload["call_id"],
                        "session_id": parsed.meta["id"],
                        "conversation_id": conversation_id_for_record(parsed.records, record),
                        "time": record.timestamp,
                        "agent_type": arguments.get("agent_type"),
                        "name": output_data.get("nickname") or arguments.get("description"),
                        "message": arguments.get("message") or arguments.get("prompt"),
                        "status": status_for_output(output_record),
                        "agent_id": output_data.get("agent_id"),
                        "output": output,
                    }
                )
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
                    if len(todos) >= limit:
                        return todos[:limit]
        return self._apply_limit(todos, limit)

    def get_todo(self, todo_id: str) -> TodoItem:
        for parsed in self._load_rollouts():
            for record in tool_call_records(parsed):
                payload = record.payload
                if payload["name"] != "update_plan":
                    continue
                args = parse_arguments(payload["arguments"])
                for index, item in enumerate(args["plan"], start=1):
                    current_id = f"{parsed.meta['id']}:{payload['call_id']}:{index}"
                    if current_id != todo_id:
                        continue
                    return create_todo_item(
                        {
                            "id": current_id,
                            "session_id": parsed.meta["id"],
                            "conversation_id": conversation_id_for_record(parsed.records, record),
                            "time": record.timestamp,
                            "content": item["step"],
                            "status": item["status"],
                            "source_call_id": payload["call_id"],
                        }
                    )
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
                    if len(skills) >= limit:
                        return skills[:limit]
        return self._apply_limit(skills, limit)

    def get_skill(self, skill_id: str) -> SkillInvocation:
        for parsed in self._load_rollouts():
            for record in event_messages(parsed, "user_message"):
                text = str(record.payload["message"])
                for name in extract_skill_mentions(text):
                    current_id = f"{parsed.meta['id']}:{record.line_number}:{name}"
                    if current_id != skill_id:
                        continue
                    return create_skill_invocation(
                        {
                            "id": current_id,
                            "session_id": parsed.meta["id"],
                            "conversation_id": conversation_id_for_record(parsed.records, record),
                            "time": record.timestamp,
                            "name": name,
                            "source": "user_message",
                            "text": text,
                        }
                    )
        raise ClientError(f"Skill invocation not found: {skill_id}")

    def list_timeline(
        self,
        project: Optional[str] = None,
        project_path: Optional[str] = None,
        session_id: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
    ) -> List[TimelineEvent]:
        if project is None and project_path is None and session_id is None and since is None:
            self.load_errors = []
            events: List[TimelineEvent] = []
            for path in sorted(iter_rollout_paths(self.codex_home), reverse=True):
                try:
                    parsed = load_rollout(path)
                except FileNotFoundError:
                    self.load_errors.append(f"{path}: file not found")
                    continue
                except ValueError as error:
                    self.load_errors.append(str(error))
                    continue
                for event in self._iter_timeline_events_desc(parsed):
                    events.append(event)
                    if len(events) >= limit:
                        return events[:limit]
            return events

        heap: List[tuple[float, int, TimelineEvent, Any]] = []
        counter = 0
        for parsed in self._matching_rollouts(project, project_path, session_id, since):
            iterator = self._iter_timeline_events_desc(parsed)
            try:
                event = next(iterator)
            except StopIteration:
                continue
            heapq.heappush(heap, (-self._timestamp_sort_key(event.time), counter, event, iterator))
            counter += 1

        events: List[TimelineEvent] = []
        while heap and len(events) < limit:
            _neg_time, _counter, event, iterator = heapq.heappop(heap)
            events.append(event)
            try:
                next_event = next(iterator)
            except StopIteration:
                continue
            heapq.heappush(heap, (-self._timestamp_sort_key(next_event.time), counter, next_event, iterator))
            counter += 1

        return events

    def get_timeline(self, session_id: str, limit: int = 500) -> List[TimelineEvent]:
        events = list(itertools.islice(self._iter_timeline_events_desc(self._get_rollout(session_id)), limit))
        events.sort(key=lambda event: (self._timestamp_sort_key(event.time), event.id))
        return events

    def get_timeline_event(self, event_id: str) -> TimelineEvent:
        session_id, has_separator, _rest = event_id.partition(":")
        if has_separator:
            try:
                parsed = self._get_rollout(session_id)
            except ClientError:
                parsed = None
            if parsed is not None:
                for event in self._iter_timeline_events_desc(parsed):
                    if event.id == event_id:
                        return event
                raise ClientError(f"Timeline event not found: {event_id}")

        for parsed in self._load_rollouts():
            for event in self._iter_timeline_events_desc(parsed):
                if event.id == event_id:
                    return event
        raise ClientError(f"Timeline event not found: {event_id}")

    def _timeline_for_rollout(self, parsed: ParsedRollout) -> List[TimelineEvent]:
        events: List[TimelineEvent] = []
        outputs = output_records_by_call_id(parsed)
        for record in parsed.records:
            event = self._record_to_timeline_event(parsed, record, outputs)
            if event is not None:
                events.append(event)
        events.sort(key=lambda event: (self._timestamp_sort_key(event.time), event.id))
        return events

    def _iter_timeline_events_desc(self, parsed: ParsedRollout):
        outputs = output_records_by_call_id(parsed)
        for record in reversed(parsed.records):
            event = self._record_to_timeline_event(parsed, record, outputs)
            if event is None:
                continue
            yield event

    def _record_to_timeline_event(self, parsed: ParsedRollout, record, outputs) -> Optional[TimelineEvent]:
        payload = record.payload
        session_id = parsed.meta["id"]
        base = {
            "time": record.timestamp,
            "session_id": session_id,
            "conversation_id": conversation_id_for_record(parsed.records, record),
            "raw_type": record.record_type,
        }
        if record.record_type == "session_meta":
            return create_timeline_event(
                {
                    **base,
                    "id": f"{session_id}:session",
                    "event_type": TimelineEventType.SESSION,
                    "name": project_name(parsed.meta["cwd"]),
                    "text": parsed.meta["cwd"],
                }
            )
        if record.record_type == "turn_context":
            return create_timeline_event(
                {
                    **base,
                    "id": f"{session_id}:turn:{record.line_number}",
                    "event_type": TimelineEventType.TURN,
                    "name": payload["turn_id"],
                    "text": payload.get("cwd"),
                }
            )
        if record.record_type == "event_msg":
            return self._event_msg_timeline_event(record, base)
        if record.record_type == "response_item" and payload["type"] == "message":
            return create_timeline_event(
                {
                    **base,
                    "id": f"{session_id}:message:{record.line_number}",
                    "event_type": TimelineEventType.MESSAGE,
                    "role": payload["role"],
                    "name": payload.get("phase"),
                    "text": text_from_content(payload.get("content")),
                }
            )
        if record.record_type == "response_item" and payload["type"] == "function_call":
            output_record = outputs.get(payload["call_id"])
            return create_timeline_event(
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
        if record.record_type == "response_item" and payload["type"] == "function_call_output":
            return create_timeline_event(
                {
                    **base,
                    "id": f"{payload['call_id']}:output",
                    "event_type": TimelineEventType.TOOL_RESULT,
                    "name": payload["call_id"],
                    "status": "completed",
                    "output": output_for_record(record),
                }
            )
        return None

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
        summary = self._conversation_text_summary(text_from_content(messages[0].payload.get("content")) if messages else None)
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

    def _load_rollout_indexes(self) -> List[RolloutIndex]:
        self.load_errors = []
        if not self.codex_home.exists():
            return []
        indexes = []
        for path in iter_rollout_paths(self.codex_home):
            try:
                indexes.append(load_rollout_index(path))
            except FileNotFoundError:
                self.load_errors.append(f"{path}: file not found")
            except ValueError as error:
                self.load_errors.append(str(error))
        indexes.sort(key=lambda index: self._timestamp_sort_key(index.last_activity), reverse=True)
        return indexes

    def _get_rollout(self, session_id: str) -> ParsedRollout:
        path = self._get_rollout_path(session_id)
        return load_rollout(path)

    def _matching_rollouts(
        self,
        project: Optional[str],
        project_path: Optional[str],
        session_id: Optional[str],
        since: Optional[str],
    ):
        if session_id is not None:
            parsed = self._get_rollout(session_id)
            if not self._matches_project(parsed, project, project_path):
                return
            if not self._matches_since(max_timestamp(parsed.records), since):
                return
            yield parsed
            return
        for index in self._matching_rollout_indexes(project, project_path, since):
            yield load_rollout(index.path)

    def _matching_rollout_indexes(
        self,
        project: Optional[str],
        project_path: Optional[str],
        since: Optional[str],
        date_window: Optional[Tuple[datetime, datetime]] = None,
    ):
        for index in self._load_rollout_indexes():
            if project_path is not None and index.cwd != project_path:
                continue
            if project is not None and project_name(index.cwd) != project:
                continue
            if not self._matches_since(index.last_activity, since):
                continue
            if not self._matches_date_window(index.last_activity, date_window):
                continue
            yield index

    def _get_rollout_path(self, session_id: str) -> Path:
        pattern = f"{ROLLOUT_PREFIX}*{session_id}{ROLLOUT_SUFFIX}"
        for subdir in SESSION_SUBDIRS:
            root = self.codex_home / subdir
            if not root.exists():
                continue
            matches = list(root.rglob(pattern))
            if not matches:
                continue
            if len(matches) != 1:
                rendered = ", ".join(str(path) for path in matches)
                raise ClientError(
                    f"Multiple rollouts found for session {session_id}: {rendered}"
                )
            return matches[0]
        raise ClientError(f"Session not found: {session_id}")

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

    def _conversation_text_summary(self, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        compact = " ".join(text.split())
        if len(compact) <= self.CONVERSATION_SUMMARY_MAX_CHARS:
            return compact
        return compact[: self.CONVERSATION_SUMMARY_MAX_CHARS - 3] + "..."

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
