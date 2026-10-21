# CodexSessions CLI

## DESCRIPTION

The `codex-sessions` CLI lets you query and analyze OpenAI Codex session transcripts across the primary Codex home and every named Codex profile.

Use it when you need scriptable reads, exports, or evidence collection without opening the service UI.

## Installation

```bash
cd <cli-tools-root>/codex-sessions
uv tool install -e . --force --refresh
```

After installation, the `codex-sessions` command is available in your terminal.

## Quick Start

```bash
# Check local transcript access
codex-sessions auth status

# List recent projects with Codex sessions
codex-sessions projects list --limit 10

# List recent sessions
codex-sessions sessions list --limit 10 --table

# Show a full session timeline
codex-sessions timeline consolidated --session-id <session-id> --table
```

## Commands

### Authentication

Codex session transcripts are local files, so no login is required. The auth
commands exist to report local access status.

```bash
codex-sessions auth status
codex-sessions auth status --table
codex-sessions auth login --force
codex-sessions auth logout
```

### Projects

```bash
codex-sessions projects list
codex-sessions projects list --limit 25 --table
codex-sessions projects list --filter "session_count:gt:5"
codex-sessions projects list --properties name,full_path,session_count
codex-sessions projects get <project-name-or-path>
```

### Sessions

```bash
codex-sessions sessions list
codex-sessions sessions list --project codex-sessions --since 1d
codex-sessions sessions list --project-path <cli-tools-root>/codex-sessions
codex-sessions sessions list --filter "has_errors:eq:false"
codex-sessions sessions get <session-id>
codex-sessions sessions search "rollout schema" --limit 10
```

### Conversations

```bash
codex-sessions conversations list
codex-sessions conversations list --session-id <session-id> --table
codex-sessions conversations list --project codex-sessions --since 1w
codex-sessions conversations get <session-id>:1
```

### Tool Calls

```bash
codex-sessions tool-calls list
codex-sessions tool-calls list --session-id <session-id>
codex-sessions tool-calls list --filter "name:eq:exec_command"
codex-sessions tool-calls list --properties time,session_id,name,status,exit_code
codex-sessions tool-calls get <tool-call-id>
```

### Subagent Activity

```bash
codex-sessions subagent-activity list
codex-sessions subagent-activity list --session-id <session-id>
codex-sessions subagent-activity list --filter "agent_type:eq:explorer"
codex-sessions subagent-activity get <subagent-tool-call-id>
```

### Todos

```bash
codex-sessions todos list
codex-sessions todos list --session-id <session-id>
codex-sessions todos list --filter "status:eq:completed"
codex-sessions todos get <todo-id>
```

### Skills

```bash
codex-sessions skills list
codex-sessions skills list --session-id <session-id>
codex-sessions skills list --filter "name:eq:cli-tool"
codex-sessions skills get <skill-invocation-id>
```

### Timeline

```bash
# All activity for one session
codex-sessions timeline consolidated --session-id <session-id>
codex-sessions timeline consolidated --session-id <session-id> --table

# Timeline by positional session ID
codex-sessions timeline get <session-id>

# Timeline across sessions
codex-sessions timeline list --since 1d --limit 50
codex-sessions timeline list --errors-only
codex-sessions timeline list --properties time,event_type,name,status,text
```

## Common Options

List commands support standard CLI-tool options:

| Option | Description |
|--------|-------------|
| `--table`, `-t` | Render table output instead of JSON |
| `--limit`, `-l` | Limit returned rows |
| `--filter`, `-f` | Filter with `field:op:value` syntax |
| `--properties` | Return only selected comma-separated fields |

Many commands also support:

| Option | Description |
|--------|-------------|
| `--project` | Filter by project directory name |
| `--project-path` | Filter by exact working directory path |
| `--session-id`, `-S` | Filter to a single Codex session |
| `--since`, `-s` | Filter by age, such as `5h`, `1d`, or `2w` |

## Configuration

Configuration is optional. By default, the CLI checks for the `codex` executable
on `PATH` and reads:

1. The primary Codex home, such as `~/.codex`
2. Every immediate profile home under `<primary>/profiles/<name>` that contains
   `sessions` or `archived_sessions`

Profile roots are searched in directory-name order after the primary home.
Duplicate roots and rollout paths are removed, and `auth status` reports the
resolved roots in its `codex_roots` field.

```bash
ACTIVE=true
CLI_COMMAND=codex
CODEX_HOME=~/.codex
# Optional: search only one named Codex profile
CODEX_SESSIONS_CODEX_PROFILE=deepseek
# Optional: search one explicit root, with higher precedence than the profile
CODEX_SESSIONS_CODEX_HOME=~/.codex/profiles/work
```

`CODEX_HOME` sets the primary Codex home. If it points at
`<primary>/profiles/<name>`, the CLI derives `<primary>` and still performs the
default all-profile search.

`CODEX_SESSIONS_CODEX_PROFILE` scopes reads to
`<primary>/profiles/<name>`. `CODEX_SESSIONS_CODEX_HOME` scopes reads to one
explicit root and takes precedence over the profile selector. These variables
are Codex root selectors; the command-group `--profile` option is the separate
CLI-tools authentication profile and does not change Codex session scope.

Callers that construct `CodexSessionsClient(codex_home=...)` keep the explicit
single-root behavior.

## Transcript Handling

Broad scan commands skip invalid rollout files and store their exact load errors
on the client as `load_errors`. Valid transcript files continue to be returned.
Direct parser errors include the file path and line number.

Tool calls are normalized across
`function_call`/`function_call_output`,
`custom_tool_call`/`custom_tool_call_output`, and
`tool_search_call`/`tool_search_output`. Custom string inputs are returned as
`{"input": "<raw text>"}`; object inputs pass through unchanged. Tool-search
calls without an explicit name use `tool_search`; their parsed `arguments` are
preserved and the execution surface is added as an `execution` key when
present. Outputs without a `call_id` remain visible as standalone
`tool_result` timeline events and are not paired with a call. A call's own
`status` takes precedence over its output status, and failed calls set the
session error flag.

Messages are normalized across response items, legacy `user_message` and
`agent_message` events, and `item_completed` `UserMessage`/`AgentMessage`
items. Equivalent copies are deduplicated, chronological order is preserved,
and injected context such as `AGENTS.md` or environment instructions is
ignored in conversation summaries, prompt extraction, and skill mentions.
Non-message `item_completed` items do not become blank generic timeline events;
their tool records come from the normalized response-item calls. A
conversation uses its first meaningful user prompt, falling back to the first
assistant update when no user prompt was recorded.

## Output

JSON is the default output for scripting. Use `--table` for human-readable tables.

```bash
codex-sessions sessions list --limit 5 | jq '.[].id'
codex-sessions tool-calls list --filter "status:eq:completed" --table
```

## Models

Client methods return Pydantic models:

| Model | Description |
|-------|-------------|
| `Project` | A working directory with Codex sessions |
| `SessionSummary` | Session metadata, counts, tokens, and git context |
| `SessionDetail` | Full session records, messages, and tool calls |
| `ConversationSummary` | A turn-level summary inside a session |
| `ToolCall` | A Codex tool invocation and output |
| `SubagentActivity` | A subagent launch captured from `spawn_agent` or `Task` |
| `TodoItem` | An `update_plan` item from a session |
| `SkillInvocation` | A `$skill` or `@agent` mention in a user prompt |
| `TimelineEvent` | Chronological activity across session records |

## Requirements

- Python 3.11+
- Local Codex transcripts in the primary home or profile homes, under
  `sessions` or `archived_sessions`
- Optional: `codex` CLI installed and available on `PATH`
