# deepseek-sessions

## DESCRIPTION

Query and analyze DeepSeek Harness (`dsh`) session transcripts from `~/.dsh`, reading local session logs only. Use it to audit what a `dsh` run actually did — its turns, tool calls, subagents, retries, and token cost — with the same command shape as `claude-code-sessions` and `codex-sessions`.

## INSTALLATION

Installed with the rest of `cli-tools`:

```bash
uv tool install -e /Users/adam/Dropbox/GitRepos/cli-tools/deepseek-sessions --force
```

Requires Python 3.14 or newer. `dsh` stores session logs as concatenated Zstandard frames, and the stdlib `compression.zstd` module (added in 3.14) decodes them with no third-party dependency.

## AUTHENTICATION

None. The CLI reads local files. `auth status` reports whether the `dsh` session store is readable:

```bash
deepseek-sessions auth status
```

There are no reusable credentials for this tool, so nothing belongs in the CLI-tools secret manager for it.

## CONFIGURATION

Non-secret settings live in `~/.local/share/cli-tools/deepseek-sessions/.env`.

| Variable | Purpose | Default |
|----------|---------|---------|
| `DEEPSEEK_SESSIONS_DSH_HOME` | Override the harness home | unset |
| `DSH_HOME` | The harness's own home override, honored second | unset |
| `DEEPSEEK_SESSIONS_CLI_COMMAND` | Name of the `dsh` executable | `dsh` |
| `DEEPSEEK_SESSIONS_CLI_PATH` | Full path to the `dsh` executable | unset |

Home resolution follows the harness: `DEEPSEEK_SESSIONS_DSH_HOME`, then `DSH_HOME`, then `~/.dsh`. A blank `DSH_HOME` is treated as unset.

## HOW dsh STORES SESSIONS

Understanding the layout explains most of the command surface.

```
~/.dsh/sessions/
  --Users-adam-Dropbox-GitRepos-Agents-LegoScout--/   <- projectKey(cwd)
    session-<uuid>/session.jsonl.zstd                 <- a session you drove
    <uuid>/session.jsonl.zstd                         <- a spawned subagent
  _no-cwd/                                            <- sessions with no cwd
```

- **Project directory name is lossy.** `projectKey(cwd)` collapses `/`, `\`, and `:` to `-`, so it cannot be reversed. Every real path in this CLI's output comes from the `cwd` field in the log header instead.
- **Session id is the directory name.** `session-<uuid>` is a session you started; a bare `<uuid>` is a subagent session spawned by another one.
- **A log is an append-only JSONL event stream.** The first line is the session header; every later line is one event. Both `session.jsonl.zstd` (concatenated Zstandard frames) and plaintext `session.jsonl` are read.
- **A truncated log is expected, not corrupt.** `dsh` appends whole frames, so a process killed mid-append leaves a partial one. This CLI drops the unfinished frame, keeps everything before it, and sets `truncated: true` on the session so a clipped log is never mistaken for a complete one.
- **Subagents are separate sessions.** The parent logs a `subagent` tool call whose result reads `started subagent <child id>`; the child's header carries `origin: subagent`, `parentSession`, and `delegationDepth`.
- **There is no `/clear`.** The equivalent boundary is context compaction, so a "conversation" here is the run of turns between compactions. A session that was never compacted has exactly one.

### Token accounting

`dsh` records four counters per assistant message:

| Field | Meaning |
|-------|---------|
| `total_input_tokens` | **Uncached** input tokens. Cache reads are NOT included. |
| `total_output_tokens` | Generated tokens. |
| `total_cache_read_tokens` | Tokens served from the prompt cache. |
| `total_reasoning_tokens` | The reasoning portion **inside** `total_output_tokens`. |
| `effective_tokens` | `input + output + (cache_read × 0.1)` — a cost-weighted total. |

This differs from Claude Code, whose input count already includes cache reads. Do not compare `effective_tokens` across the two tools as if the formula were the same.

Every counter is verified equal to `dsh`'s own rollup in `~/.dsh/storages/session_projcache.json`.

## COMMANDS

Groups 1-9 match `claude-code-sessions` and `codex-sessions`. Groups 10-13 are `dsh`-native.

Every `list` command accepts `--table/-t`, `--wide/-w`, `--limit/-l`, `--filter/-f`, and `--properties`. Every `get` command accepts `--table/-t`. Without `--table`, output is JSON. `--wide` adds the remaining columns in table mode.

Most groups also accept `--session-id/-S` (an id **or** a title) or `--session-name/-N` (always a title), plus `--since/-s`.

### auth

```bash
deepseek-sessions auth status
```

### projects

```bash
deepseek-sessions projects list
deepseek-sessions projects list --table
deepseek-sessions projects list --filter "session_count:gt:5"
deepseek-sessions projects get LegoScout --table
deepseek-sessions projects get /Users/adam/Dropbox/GitRepos/Agents/LegoScout
```

A project can be named by its basename, its absolute path, or its directory key.

### sessions

```bash
deepseek-sessions sessions list --table
deepseek-sessions sessions list --project LegoScout --no-subagents
deepseek-sessions sessions list --date-alias yesterday --limit 5
deepseek-sessions sessions list --date 2026-08-19 --min-tool-calls 1
deepseek-sessions sessions list --date-range 2026-08-01..2026-08-19 --wide --table
deepseek-sessions sessions list --filter "origin:eq:subagent" --table
deepseek-sessions sessions list --date-alias today --include-prompts first:2,last:1 --prompts-clean
deepseek-sessions sessions get session-53a213f2-c5ac-4950-a2c7-8011f2281e55 --table
deepseek-sessions sessions get "Fix Lego deal run issues"
deepseek-sessions sessions search "timeout" --since 7d --table
```

`--date`, `--date-range`, `--date-alias`, and `--since` are mutually exclusive. `--date-alias` accepts `today`, `yesterday`, `this_week`, `last_week` (ISO weeks, Monday-Sunday).

### conversations

```bash
deepseek-sessions conversations list --project LegoScout --table
deepseek-sessions conversations list -p CourseCraft --filter "started_by:eq:compaction"
deepseek-sessions conversations get session-d0bb242a-5c9b-4afd-ae7f-57c3bb1f11c1:1 --table
deepseek-sessions conversations get --session-name "Fix Lego deal run issues" -C 1
```

The positional form is `session:number`, split from the right so titles containing a colon still work.

### subagent-activity

```bash
deepseek-sessions subagent-activity list --project LegoScout --table
deepseek-sessions subagent-activity list -p LegoScout --filter "status:eq:error"
deepseek-sessions subagent-activity list -p CourseCraft -S session-0d8e00ea-2658-432c-89ed-7800d5b965bd
deepseek-sessions subagent-activity get 72a1b775-435d-4a28-bd38-3f693adac2eb --table
```

`-S` scopes to the subagents spawned by one parent session. Each row carries the child session's own token cost and, when it produced one, its `report` output.

### tool-calls

```bash
deepseek-sessions tool-calls list --project LegoScout --table
deepseek-sessions tool-calls list -p LegoScout --filter "tool:eq:bash"
deepseek-sessions tool-calls list -p LegoScout --filter "status:eq:error" --wide --table
deepseek-sessions tool-calls list -p LegoScout --include-subagents
deepseek-sessions tool-calls list -p LegoScout --subagent-id 72a1b775-435d-4a28-bd38-3f693adac2eb
deepseek-sessions tool-calls list -p LegoScout --no-code-dispatch
deepseek-sessions tool-calls get call_00_3eobTHgeR5qdfDWKVuYA6448 -p LegoScout --table
```

`run_code` dispatches nested sub-calls, which appear as rows carrying `parent_call_id`. Use `--no-code-dispatch` to hide them.

### todos

```bash
deepseek-sessions todos list --project BricklinkBook --table
deepseek-sessions todos list -p BricklinkBook --filter "status:eq:in_progress"
deepseek-sessions todos get session-a0846bbd-95f4-489f-9ac2-92d9546eb8f4:0 -p BricklinkBook
```

`dsh` rewrites the whole list on every write, so this reports the final list per session. Todo ids are `<session id>:<position>`.

### skills

```bash
deepseek-sessions skills list --project CourseCraft --table
deepseek-sessions skills list -p CourseCraft --filter "kind:eq:command"
deepseek-sessions skills list -p CourseCraft --filter "name:eq:caveman"
deepseek-sessions skills get cmd-a9d512b7-1 -p BricklinkBook --table
```

Covers both `skill` tool loads (`kind: skill`) and slash commands (`kind: command`).

### timeline

```bash
deepseek-sessions timeline list --project LegoScout --since 1d --table
deepseek-sessions timeline list -p LegoScout --errors-only --table
deepseek-sessions timeline list -p LegoScout --filter "event_type:eq:retry"
deepseek-sessions timeline get session-53a213f2-c5ac-4950-a2c7-8011f2281e55 --table
deepseek-sessions timeline get --session-name "Fix Lego deal run issues" --show-thinking --table
deepseek-sessions timeline consolidated -S session-53a213f2-c5ac-4950-a2c7-8011f2281e55 --table
deepseek-sessions timeline consolidated -S session-53a213f2-c5ac-4950-a2c7-8011f2281e55 --hide-agent-tools
```

`consolidated` merges a session with every subagent it spawned into one chronological view. Event types: `user_message`, `assistant_message`, `thinking`, `notice`, `skill_load`, `command`, `tool_call`, `code_dispatch`, `subagent_start`, `subagent_tool`, `todo_write`, `goal_change`, `approval`, `retry`, `compaction`, `turn_end`, `error`.

### search

```bash
deepseek-sessions search run "legoscout"
deepseek-sessions search run "timeout" --since 30d --table
deepseek-sessions search run "auctionzip" --snippets --table
deepseek-sessions search run "docker" --project CourseCraft --max-matches 10
```

Searches user messages, assistant messages, and tool results across every project by default.

### turns (dsh-native)

```bash
deepseek-sessions turns list --project LegoScout --table
deepseek-sessions turns list -p LegoScout --filter "finish_reason:eq:error"
deepseek-sessions turns list -p CourseCraft -S session-0d8e00ea-2658-432c-89ed-7800d5b965bd --wide --table
deepseek-sessions turns get 3 -S session-0d8e00ea-2658-432c-89ed-7800d5b965bd --table
```

`dsh` brackets its agent loop explicitly. `turns get` also lists the steps (model round-trips) inside the turn. `step_count` counts **completed** steps, matching `dsh`'s own number; `open_step_count` counts steps that began but never closed because the session was killed mid-request.

### retries (dsh-native)

```bash
deepseek-sessions retries list --project LegoScout --table
deepseek-sessions retries list -p LegoScout --filter "error_code:eq:TIMEOUT"
deepseek-sessions retries list -p LegoScout --filter "started:eq:false"
deepseek-sessions retries get 79da67c3-9ac4-463e-b2af-7f20b4f2b416 -p LegoScout --table
```

Error codes come from the harness: `TIMEOUT`, `RATE_LIMIT`, `SERVER`, `TRANSPORT`, `EMPTY_RESPONSE`. `started: false` means a retry was scheduled but the session ended before it ran.

### approvals (dsh-native)

```bash
deepseek-sessions approvals list --project BricklinkBook --table
deepseek-sessions approvals list -p BricklinkBook --filter "outcome:eq:allowed-once"
deepseek-sessions approvals get 49ff56e3-4b0a-4b1a-99d6-8aae2a288de7 -p BricklinkBook --table
```

Each row pairs a permission escalation request with its decision and the latency between them. A row with no outcome was never answered.

### goals (dsh-native)

```bash
deepseek-sessions goals list --project CourseCraft --table
deepseek-sessions goals list -p CourseCraft --filter "phase:eq:active"
deepseek-sessions goals get goal-c6c1f5cf-b816-4ab4-90aa-59c6ef7987bb -p CourseCraft --table
```

`goals get` shows every recorded revision of one goal.

## FILTERING

`--filter` is `field:op:value` and repeatable (AND semantics). Filters apply to the fields in the JSON output.

```bash
deepseek-sessions sessions list --filter "origin:eq:subagent" --filter "turn_count:gt:3"
deepseek-sessions tool-calls list -p LegoScout --filter "tool:contains:bash"
```

Operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `contains`, `startswith`, `endswith`, `in`, `like`.

## OUTPUT

stdout carries data only; messages and errors go to stderr. Default output is JSON, so it composes with `jq`:

```bash
deepseek-sessions sessions list --limit 1000 \
  | jq '[.[] | select(.origin == "subagent")] | map(.effective_tokens) | add'

deepseek-sessions turns list -p LegoScout --limit 1000 \
  | jq 'group_by(.finish_reason) | map({reason: .[0].finish_reason, count: length})'
```

## TESTING

```bash
cd /Users/adam/Dropbox/GitRepos/cli-tools/deepseek-sessions
uv run --with pytest python -m pytest tests
```

Tests build synthetic session logs in both physical encodings, so they never read the developer's real `dsh` home.

## DOCUMENTATION

DeepSeek Harness: https://github.com/deepseek-ai/deepseek-harness
