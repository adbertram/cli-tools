# hermes-sessions

## DESCRIPTION

Query and analyze Hermes Agent session state from the local Hermes home, reading the `state.db` session store only. Use it to audit what a Hermes run actually did — its conversations, turns, tool calls, todos, skills, subagents, and timeline — with the same command shape as `claude-code-sessions`, `codex-sessions`, and `deepseek-sessions`.

## READ-ONLY GUARANTEE

The CLI is strictly read-only. It opens the state store through a SQLite `mode=ro` URI, so no code path can write to `state.db`, and its entire recursive command tree contains no command that writes anything — no delete, prune, rename, fork, create, update, or select, and no credential or profile writes either.

`auth status` is the only `auth` command. It is a standalone status reader, not the shared credential-management app, so it cannot grow login/logout/profile writes. Configuration resolution is also non-bootstrapping: constructing the config or running a read under an empty `XDG_DATA_HOME` creates no file or directory. Boundary tests walk the whole command tree recursively — `auth` included — and compare an isolated data root before and after real reads.

## INSTALLATION

Installed with the rest of `cli-tools`:

```bash
uv tool install -e /Users/adam/Dropbox/GitRepos/cli-tools/hermes-sessions --force
```

## AUTHENTICATION

None. The CLI reads local files. `auth status` reports whether the Hermes state store is readable:

```bash
hermes-sessions auth status
hermes-sessions auth status --table
```

`auth status` reports the resolved Hermes home, the `state.db` path, and whether that store is readable, in the shared per-profile JSON shape (`profiles[].credential_types.custom`). It exits `2` when no profile reports access.

There is no `auth login`, `auth logout`, `auth test`, or `auth profiles` command: this CLI holds no credential, so there is nothing to log into and no profile state worth writing. There are no reusable credentials for this tool, so nothing belongs in the CLI-tools secret manager for it. Reusable human-supplied CLI credentials always go to `_repo/_secret-manager/secrets.sh`, never to any `.env` file.

## CONFIGURATION

An optional, pre-existing `~/.local/share/cli-tools/hermes-sessions/.env` can provide non-secret settings. This CLI only reads that file; it never creates or updates it.

| Variable | Purpose | Default |
|----------|---------|---------|
| `HERMES_HOME` | Hermes home directory holding `state.db` | `~/.hermes` |
| `HERMES_SESSIONS_HERMES_HOME` | CLI-scoped override, checked first (environment only) | unset |

Home resolution mirrors Hermes itself, with one CLI-scoped override in front: `HERMES_SESSIONS_HERMES_HOME`, then `HERMES_HOME` (environment or this tool's config `.env`), then `~/.hermes`. A blank value is treated as unset. Each Hermes profile is its own home directory, so point `HERMES_HOME` at a profile's home to read that profile's sessions.

The `hermes` binary is **not** required and is never executed. This CLI only reads `state.db`.

## HOW HERMES STORES SESSIONS

Understanding the layout explains most of the command surface.

```
$HERMES_HOME/state.db        SQLite, WAL mode
├── sessions                 one row per session: source, model, cwd, title, tokens, lineage
├── messages                 full message history: role, content, tool_calls, tool_name
├── messages_fts             FTS5 index over message content, tool name, and tool calls
├── session_model_usage      per-model token and cost rollups
└── async_delegations        asynchronous subagent delegations
```

- **A project is a working directory.** Hermes records `cwd` per session. Gateway and cron sessions have no working directory at all, so they collect in one explicit `(no-workspace)` bucket instead of disappearing.
- **`source` is the runtime origin**: `cli`, `cron`, `slack`, `telegram`, `email`, `webui`, `subagent`, and named gateway sources.
- **A subagent is its own session** with `source = subagent` and a `parent_session_id` pointing at the delegating session.
- **A conversation is a context segment.** Hermes has no `/clear`; the equivalent boundary is context compaction. A compaction writes a summary message, which starts the next conversation. A session that was never compacted has exactly one.
- **A turn opens at each user message** and holds the assistant messages and tool calls that answered it.
- **Todos are `todo` tool calls.** Hermes rewrites the whole list on every call, so this CLI reports the final list per session.
- **Skills are `skill_view` / `skill_manage` / `skills_list` tool calls** (`kind: skill`) plus slash commands in user messages (`kind: command`).

### Token accounting

| Field | Meaning |
|-------|---------|
| `input_tokens` | **Uncached** input tokens. Cache reads are NOT included. |
| `output_tokens` | Generated tokens. |
| `cache_read_tokens` | Tokens served from the prompt cache. |
| `reasoning_tokens` | The reasoning portion **inside** `output_tokens`. |
| `effective_tokens` | `input + output + (cache_read × 0.1)` — a cost-weighted total. |

## BOUNDED OUTPUT AND SECRET SAFETY

Every text field this CLI prints is a bounded preview, never a raw transcript:

- `--max-chars` (default 200) caps each preview; text past the bound is truncated with `...`.
- Previews are collapsed to one line and passed through a redactor that masks Bearer/Basic authorization, AWS access-key IDs, credentials in URLs or `curl -u`, `sk-`/`ghp_`/`xoxb-` style keys, and quoted or unquoted `*key`/`*secret`/`*token`/`password` assignments.
- `sessions get` returns metadata and counts plus bounded/redacted first-user and latest-assistant previews. For sessions above the bounded 5,000-message analysis window, `message_window_truncated` and `message_window_size` explicitly report that older derived context was omitted; edge previews and aggregate counts are queried independently so they remain correct.
- Todo content uses the same redaction and `--max-chars` bound as every other transcript-derived preview.
- `timeline consolidated` is bounded twice: `--limit` caps the merged event count and `--max-chars` caps every event summary.
- Every list query carries a SQL `LIMIT`, and a message-derived list stops opening sessions as soon as `--limit` rows exist.

## COMMANDS

Every `list` command accepts `--table/-t`, `--wide/-w`, `--limit/-l`, `--filter/-f`, and `--properties`. Every `get` command accepts `--table/-t`. Without `--table`, output is JSON on stdout; `--wide` adds the remaining columns in table mode.

Message-derived groups also accept `--session-id/-S` (an id **or** a title), `--session-name/-N` (always a title), `--project/-p`, `--source`, and exactly one of `--since/-s`, `--date`, `--date-range`, `--date-alias`.

### auth

```bash
hermes-sessions auth status
```

### projects

```bash
hermes-sessions projects list
hermes-sessions projects list --table
hermes-sessions projects list --filter "session_count:gt:5" --table
hermes-sessions projects get CryptoTrader --table
hermes-sessions projects get /Users/adam/Dropbox/GitRepos/Agents/CryptoTrader
hermes-sessions projects get "(no-workspace)" --table
```

A project can be named by its basename or its absolute path. When two workspaces share a basename, the CLI reports the ambiguity with every candidate path instead of picking one.

### sessions

```bash
hermes-sessions sessions list --table
hermes-sessions sessions list --source cron --limit 5 --table
hermes-sessions sessions list --project CryptoTrader --no-subagents
hermes-sessions sessions list --date-alias yesterday --table
hermes-sessions sessions list --date-range 2026-09-01..2026-09-19 --wide --table
hermes-sessions sessions list --filter "tool_call_count:gt:10" --table
hermes-sessions sessions get cron_f2913088764d_20260919_130521 --table
hermes-sessions sessions get --session-name "ATA Blog daily comment management"
hermes-sessions sessions search "comment management" --table
```

`sessions get` resolves an id first, then a title case-insensitively. Hermes enforces unique titles, but titles differing only by case can both exist; that case is reported as an ambiguity with every candidate id.

### conversations

```bash
hermes-sessions conversations list --source cron --table
hermes-sessions conversations list -S cron_f2913088764d_20260919_130521
hermes-sessions conversations list --filter "started_by:eq:compaction" --table
hermes-sessions conversations get cron_f2913088764d_20260919_130521:1 --table
```

The reference form is `<session-id>:<number>`, split from the right so a session id containing a colon still works.

### turns

```bash
hermes-sessions turns list -S cron_f2913088764d_20260919_130521 --table
hermes-sessions turns list --project CryptoTrader --filter "tool_call_count:gt:3"
hermes-sessions turns list --source cron --wide --table
hermes-sessions turns get cron_f2913088764d_20260919_130521:2 --table
```

### tool-calls

```bash
hermes-sessions tool-calls list -S cron_f2913088764d_20260919_130521 --table
hermes-sessions tool-calls list --source cron --tool terminal --table
hermes-sessions tool-calls list --project CryptoTrader --filter "status:eq:error" --wide --table
hermes-sessions tool-calls get call_Ss71SJT8IxHnorchZLfLMffY -S cron_f2913088764d_20260919_130521 --table
```

### todos

```bash
hermes-sessions todos list --source cron --table
hermes-sessions todos list -S cron_f2913088764d_20260919_130521
hermes-sessions todos list -S cron_f2913088764d_20260919_130521 --max-chars 80
hermes-sessions todos list --filter "status:eq:in_progress" --table
hermes-sessions todos get cron_f2913088764d_20260919_130521:0 --max-chars 80 --table
```

Todo ids are `<session-id>:<position>`.

### skills

```bash
hermes-sessions skills list --source cron --table
hermes-sessions skills list -S cron_f2913088764d_20260919_130521
hermes-sessions skills list --filter "kind:eq:command" --table
hermes-sessions skills get cron_f2913088764d_20260919_130521:304951:0 --table
```

Skill record ids are `<session-id>:<message-id>:<position>`.

### subagent-activity

```bash
hermes-sessions subagent-activity list --table
hermes-sessions subagent-activity list -S cron_b03d38d15003_20260918_090207 --table
hermes-sessions subagent-activity list --filter "tool_call_count:gt:5" --wide --table
hermes-sessions subagent-activity get 20260918_090230_c0952c --table
```

With `-S`, only the subagents delegated by that parent session. Each row carries the child session's own cost and, when it produced one, a bounded preview of its final message.

### timeline

```bash
hermes-sessions timeline list --source cron --limit 20 --table
hermes-sessions timeline list -S cron_f2913088764d_20260919_130521 --table
hermes-sessions timeline list --project CryptoTrader --errors-only --table
hermes-sessions timeline list --filter "event_type:eq:tool_call" --table
hermes-sessions timeline get cron_f2913088764d_20260919_130521 --table
hermes-sessions timeline get --session-name "ATA Blog daily comment management" --errors-only
hermes-sessions timeline consolidated cron_b03d38d15003_20260918_090207 --table
hermes-sessions timeline consolidated cron_b03d38d15003_20260918_090207 --limit 40 --max-chars 80
```

`consolidated` merges a session with every subagent it spawned into one chronological view, bounded by `--limit` and `--max-chars`. Event types: `user_message`, `assistant_message`, `command`, `skill_load`, `tool_call`, `todo_write`, `subagent_start`, `compaction`, `notice`, `error`.

### search

```bash
hermes-sessions search run "timeout" --limit 10 --table
hermes-sessions search run "legoscout" --since 7d
hermes-sessions search run "rate limit" --project CryptoTrader --table
hermes-sessions search run "deploy" -S cron_f2913088764d_20260919_130521
```

`search run` queries the Hermes FTS5 index over message content, tool names, and tool calls. `sessions search` matches session titles only.

## FILTERING

`--filter` is `field:op:value` and repeatable (AND semantics). Filters apply to the fields in the JSON output.

```bash
hermes-sessions sessions list --filter "source:eq:cron" --filter "tool_call_count:gt:5"
hermes-sessions tool-calls list --source cron --filter "tool:contains:browser"
```

Operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `contains`, `startswith`, `endswith`, `in`, `like`.

## OUTPUT

stdout carries data only; messages and errors go to stderr. Default output is JSON, so it composes with `jq`:

```bash
hermes-sessions sessions list --limit 500 \
  | jq 'group_by(.source) | map({source: .[0].source, sessions: length})'

hermes-sessions tool-calls list --source cron --limit 500 \
  | jq '[.[] | select(.status == "error")] | length'
```

## TESTING

```bash
cd /Users/adam/Dropbox/GitRepos/cli-tools/hermes-sessions
uv run --with pytest python -m pytest tests
```

Tests build a synthetic Hermes `state.db` with the real schema, so they never read the developer's Hermes home.

## DOCUMENTATION

Hermes Agent session and state storage: https://hermes.is/docs
