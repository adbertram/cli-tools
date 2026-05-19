# Claude Code Sessions CLI - Implementation Plan

## Overview

**CLI Name:** `claude-code-sessions`
**Type:** Wrapper (local file reader - no external CLI or API)
**Purpose:** Query and export Claude Code session data from `~/.claude/projects/`
**Output:** JSON only

## Data Source Analysis

### File Locations

```
~/.claude/
├── history.jsonl              # Index file - metadata only
├── projects/                  # Full session transcripts
│   ├── -Users-adam/           # Project folder (path encoded)
│   │   ├── {uuid}.jsonl       # Session transcript
│   │   └── {uuid}/            # Session artifacts (optional)
│   └── -Users-adam-Dropbox-GitRepos-{project}/
├── todos/                     # Todo files per session
│   └── {sessionId}-agent-{agentId}.json
├── session-env/               # Environment per session
│   └── {sessionId}/
└── plans/                     # Plan documents
```

### Path Encoding

- `/Users/adam/project` → `-Users-adam-project`
- Forward slashes replaced with hyphens

### JSONL Session Format

Each line in `{uuid}.jsonl`:
```json
{
  "type": "user" | "assistant" | "file-history-snapshot",
  "uuid": "msg-uuid",
  "parentUuid": "parent-msg-uuid" | null,
  "sessionId": "session-uuid",
  "timestamp": "2026-01-10T08:30:00.000Z",
  "cwd": "/current/working/directory",
  "version": "2.0.76",
  "gitBranch": "main",
  "message": {
    "role": "user" | "assistant",
    "content": "text or array"
  },
  "isSidechain": false,
  "isMeta": false
}
```

### Tool Calls in Messages

Tool calls appear in assistant message content as structured blocks:
```json
{
  "type": "tool_use",
  "id": "tool-123",
  "name": "Bash",
  "input": { "command": "npm test" }
}
```

Tool results appear as:
```json
{
  "type": "tool_result",
  "tool_use_id": "tool-123",
  "content": "output text"
}
```

### Todo File Format

```json
[
  {
    "id": "1",
    "content": "Task description",
    "activeForm": "Doing the task",
    "status": "pending" | "in_progress" | "completed",
    "priority": "high" | "medium" | "low"
  }
]
```

## Command Structure

### Command Groups

```
claude-code-sessions
├── projects                    # Project-level operations
│   ├── list                    # List all projects
│   └── get <name>              # Get project details
├── sessions                    # Session-level operations
│   ├── list --project <name>   # List sessions for a project
│   ├── get <id>                # Get session details (ID is globally unique)
│   └── search <query> --project <name>
├── subagent-activity           # Subagent queries (--project REQUIRED)
│   ├── list --project <name>   # List subagent invocations
│   └── get <id> --project <name>
├── tool-calls                  # Tool call queries (--project REQUIRED)
│   ├── list --project <name>   # List tool calls
│   └── get <id> --project <name>
└── todos                       # Todo queries (--project REQUIRED)
    └── list --project <name>   # List todos
```

### --project Requirement

| Command Group | --project Required |
|---------------|-------------------|
| `projects` | No (operates on all) |
| `sessions list/search` | **Yes, always** |
| `sessions get` | No (session ID is globally unique) |
| `subagent-activity` | **Yes, always** |
| `tool-calls` | **Yes, always** |
| `todos` | **Yes, always** |

### Relative Time Support

All list commands support `--since` for relative time filtering:
- `--since 5h` - Last 5 hours
- `--since 1d` - Last 1 day
- `--since 7d` - Last 7 days
- `--since 30d` - Last 30 days

### Command Details

#### `projects list`
```bash
claude-code-sessions projects list [--filter KEY:VALUE] [--limit N]
```
- Lists all projects found in ~/.claude/projects/
- Returns: project name, path, session count, last activity

#### `projects get <name>`
```bash
claude-code-sessions projects get <project-name>
```
- Get details for a specific project
- Returns: full path, all sessions, statistics

#### `sessions list`
```bash
claude-code-sessions sessions list --project <name> [--since TIME] [--filter KEY:VALUE] [--limit N]
```
- List sessions for a project
- Filters: date range, has-errors, has-subagents, tool-used

#### `sessions get <session-id>`
```bash
claude-code-sessions sessions get <session-id>
```
- Get full session with transcript, tool calls, subagents, todos
- Returns the JSON structure we designed
- No --project needed (session IDs are globally unique)

#### `sessions search`
```bash
claude-code-sessions sessions search <query> --project <name> [--since TIME] [--filter KEY:VALUE]
```
- Full-text search across session content
- Search in: user messages, assistant messages, tool outputs

#### `subagent-activity list`
```bash
claude-code-sessions subagent-activity list --project <name> [--since TIME] [--filter KEY:VALUE]
```
- List all subagent invocations in project
- Filters: type (Explore, Bash, etc.), status, model

#### `subagent-activity get`
```bash
claude-code-sessions subagent-activity get <id> --project <name>
```
- Get full subagent details with conversation

#### `tool-calls list`
```bash
claude-code-sessions tool-calls list --project <name> [--since TIME] [--filter KEY:VALUE]
```
- List all tool calls in project
- Filters: tool name, status (success/error/timeout), session

#### `tool-calls get`
```bash
claude-code-sessions tool-calls get <id> --project <name>
```
- Get full tool call details with input/output

#### `todos list`
```bash
claude-code-sessions todos list --project <name> [--since TIME] [--filter KEY:VALUE]
```
- List todos from sessions in project
- Filters: status (pending/in_progress/completed), priority

## Models

### Project Model
```python
class Project(CLIModel):
    name: str                    # e.g., "Agent-ATABlogger"
    full_path: str               # e.g., "/Users/adam/.../Agent-ATABlogger"
    encoded_path: str            # e.g., "-Users-adam-...-Agent-ATABlogger"
    session_count: int
    last_activity: Optional[str] = None
```

### Session Model (list view)
```python
class SessionSummary(CLIModel):
    id: str                      # UUID
    project: str                 # Project name
    created_at: str
    last_activity: str
    message_count: int
    tool_call_count: int
    has_errors: bool
    has_subagents: bool
```

### Session Model (detail view)
```python
class Session(CLIModel):
    id: str
    project: str
    created_at: str
    last_activity: str
    claude_code_version: Optional[str] = None
    model: Optional[str] = None
    git_branch: Optional[str] = None
    cwd: Optional[str] = None
    messages: List[Message]
    subagents: Dict[str, Subagent]
    todos: List[Todo]
    errors: List[Error]
```

### Message Model
```python
class ToolCallStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

class ToolCall(CLIModel):
    id: str
    tool: str
    status: ToolCallStatus
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    input: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

class Message(CLIModel):
    uuid: str
    parent_uuid: Optional[str] = None
    type: str                    # "user" | "assistant"
    timestamp: str
    content: str
    tool_calls: List[ToolCall] = []
```

### Todo Model
```python
class TodoStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"

class Todo(CLIModel):
    id: Optional[str] = None
    content: str
    active_form: Optional[str] = None
    status: TodoStatus
    priority: Optional[str] = None
```

### Subagent Model
```python
class Subagent(CLIModel):
    id: str
    type: str                    # "Explore", "Bash", etc.
    parent_tool_call_id: str
    model: Optional[str] = None
    prompt: str
    status: str
    created_at: str
    completed_at: Optional[str] = None
    messages: List[Message]
```

## Filter Support

### Project Filters
- `name:contains:value` - Project name contains
- `sessions:gte:N` - Minimum session count

### Session Filters
- `project:eq:name` - Filter by project
- `date:gte:YYYY-MM-DD` - Sessions after date
- `date:lte:YYYY-MM-DD` - Sessions before date
- `has-errors:eq:true` - Sessions with errors
- `has-subagents:eq:true` - Sessions with subagents
- `tool:eq:Bash` - Sessions using specific tool
- `model:eq:sonnet` - Sessions using specific model

## Implementation Notes

### Parser Module (parsers.py)

Key functions:
- `parse_session_jsonl(path: Path) -> Session` - Parse session file
- `parse_message_line(line: dict) -> Message` - Parse single message
- `extract_tool_calls(content) -> List[ToolCall]` - Extract tool calls from content
- `determine_tool_status(tool_use, tool_result) -> ToolCallStatus` - Match results to calls
- `load_todos(session_id: str) -> List[Todo]` - Load todos for session

### Client Module (client.py)

Key methods:
- `list_projects() -> List[Project]`
- `get_project(name: str) -> Project`
- `list_sessions(project: Optional[str]) -> List[SessionSummary]`
- `get_session(session_id: str) -> Session`
- `search_sessions(query: str, project: Optional[str]) -> List[SessionSummary]`

### Edge Cases

1. **Multiple projects with same name** - Use full encoded path as disambiguator
2. **Large session files** - Stream parse, don't load entire file
3. **Sidechain messages** - Track parent relationships for subagent extraction
4. **Orphaned tool results** - Handle tool results without matching tool_use
5. **Session without todos** - Return empty list, not error

## Authentication

**None required** - This CLI reads local files owned by the user.

For auth commands (required by standards):
- `auth status` - Always returns `{"authenticated": true}` (local files)
- `auth login` - No-op with success message

## File Structure

```
claude-code-sessions/
├── claude_code_sessions_cli/
│   ├── __init__.py
│   ├── main.py
│   ├── client.py          # Core logic
│   ├── parsers.py         # JSONL parsing
│   ├── config.py          # Path configuration
│   ├── output.py          # JSON output
│   ├── filters.py         # Filter validation
│   ├── filter_map.py      # Filter translation
│   ├── time_utils.py      # --since parsing (5h, 1d, etc.)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── project.py
│   │   ├── session.py
│   │   ├── message.py
│   │   ├── tool_call.py
│   │   ├── subagent.py
│   │   └── todo.py
│   └── commands/
│       ├── __init__.py
│       ├── auth.py
│       ├── projects.py
│       ├── sessions.py
│       ├── subagent_activity.py
│       ├── tool_calls.py
│       └── todos.py
├── .env
├── .env.example
├── pyproject.toml
└── README.md
```

## Success Criteria

- [ ] `claude-code-sessions --version` works
- [ ] `claude-code-sessions projects list` returns all projects
- [ ] `claude-code-sessions projects get <name>` returns project details
- [ ] `claude-code-sessions sessions list --project X` returns sessions
- [ ] `claude-code-sessions sessions get <id>` returns full session with:
  - Messages with tool calls
  - Subagents with their conversations
  - Todos
  - Errors
- [ ] `claude-code-sessions sessions search "query" --project X` finds matches
- [ ] `claude-code-sessions subagent-activity list --project X` returns subagents
- [ ] `claude-code-sessions subagent-activity list --project X --since 5h` filters by time
- [ ] `claude-code-sessions tool-calls list --project X` returns tool calls
- [ ] `claude-code-sessions tool-calls list --project X --filter "status:eq:error"` filters errors
- [ ] `claude-code-sessions todos list --project X` returns todos
- [ ] `--since` relative time works: 5h, 1d, 7d, 30d
- [ ] All filters work correctly
- [ ] Output is valid JSON
- [ ] test-cli-tool.sh passes with zero failures
