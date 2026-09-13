# Grok Bot Sessions CLI

## DESCRIPTION

Read Grok Bot (also called Grokbot) session transcripts straight from the live
Cursor-hosted Connect RPC API the desktop app uses. Use it to list agents, page
their transcripts, group entries into turns, and inspect approvals, tool cards,
and automations from an agent, script, or terminal. Every command prints plain
JSON records and mirrors the codex-sessions, claude-code-sessions, and
deepseek-sessions command contract.

## Docs

- Base URL: https://api2.cursor.sh
- Service: `aiserver.v1.GrokBotService` (Connect, unary, JSON)

## How it reads Grokbot

Grok Bot is an Electron desktop app (bundle id `com.anysphere.sand`) built on
Anysphere/Cursor's `sand` agent stack. Agents run in Cursor-hosted cloud boxes;
the local machine only holds the signed-in session. There is **no local
transcript replica**: this CLI is live-API only.

- Credential source: `~/Library/Application Support/Grok Bot/sand-secrets.json`
  (`cursor-accounts` is a plaintext JSON string; its token and machine-id
  values are Electron safeStorage `v10` blobs whose key lives in the macOS
  Keychain under `Grok Bot Safe Storage` / `Grok Bot Key`).
- `auth login` therefore **adopts** the session the desktop app already holds.
  It cannot mint a token, and it never writes credential material anywhere.
  Open Grok Bot and sign in before using this CLI.
- Transcript calls require the agent's UUID `legacyAgentId`; the numeric `id`
  returns HTTP 200 with an empty body, so the CLI always resolves the UUID
  first.

## Installation

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/install-cli-tool.sh --force-refresh grokbot-sessions
```

## Quick Start

```bash
# Confirm the adopted desktop session and a live API round trip
grokbot-sessions auth status
grokbot-sessions auth test

# Find real agent ids
grokbot-sessions sessions list --table

# Read a transcript and group it into turns
grokbot-sessions timeline list --agent <legacy-uuid> --limit 20 --table
grokbot-sessions turns list --agent <legacy-uuid> --table
```

## Commands

Every group below exposes `list` with `--table/-t`, `--limit/-l`,
`--filter/-f`, and `--properties/-p`, and `get <id>` with `--table/-t`.
`--agent/-a` selects agents (numeric id, legacy UUID, or exact name; repeatable)
and defaults to every agent. `--filter` uses `field:op:value` syntax, e.g.
`kind:eq:ROOM` or `turn_count:gt:5`.

### auth

```bash
grokbot-sessions auth login              # adopt + verify the desktop app session
grokbot-sessions auth login --force      # re-verify the adopted session
grokbot-sessions auth status             # per-profile JSON status
grokbot-sessions auth status --table
grokbot-sessions auth test               # live ListGrokBotAgents round trip
grokbot-sessions auth profiles list
grokbot-sessions auth logout             # clears CLI profile state only
```

`auth login` cannot mint a token: it adopts the Grok Bot desktop app's session
and fails with the remediation when the Keychain read or the account scope is
missing. `auth logout` clears this CLI's profile state; it cannot revoke the
desktop app's session.

### projects

Grokbot has no working-directory-scoped project. Each signed-in account scope
is surfaced as one implicit project (`account-1`, `account-2`, ...), so the
shared `projects` contract still answers.

```bash
grokbot-sessions projects list --table
grokbot-sessions projects get account-1 --table
```

### sessions

One session per agent, from `ListGrokBotAgents`.

```bash
grokbot-sessions sessions list --table
grokbot-sessions sessions get 1036984 --table
grokbot-sessions sessions get 5658aa56-122b-4f56-acd9-5102e4f39d1b
grokbot-sessions sessions search lego --table
grokbot-sessions sessions list --filter "kind:eq:ROOM"
```

### conversations

One conversation per agent per transcript `generation`. The service labels most
transcripts with a numeric generation but omits the field for some agents and
rooms; those rows report `generation: 1` as their identity with
`generation_reported: false` so the unlabelled case stays visible.

```bash
grokbot-sessions conversations list --table
grokbot-sessions conversations list --agent <legacy-uuid> --table
grokbot-sessions conversations get <legacy-uuid>:1 --table
```

### turns

Entries grouped by the turn encoded in their id (`t<n>u` user, `t<n>s<m>`
agent send, `t<n>a<m>` agent-authored).

```bash
grokbot-sessions turns list --table
grokbot-sessions turns list --agent <legacy-uuid> --filter "has_approval:eq:true"
grokbot-sessions turns get <legacy-uuid>:t6 --table
```

### timeline

```bash
grokbot-sessions timeline list --agent <legacy-uuid> --limit 20 --table
grokbot-sessions timeline list --filter "kind:eq:message" --table
grokbot-sessions timeline get <legacy-uuid>:t6u --table
grokbot-sessions timeline consolidated --limit 50 --table
```

`timeline list` preserves the server's newest-to-oldest order (never re-sorted
by `seq`). `timeline consolidated` interleaves all selected agents by
`timestampMs`.

### tool-calls

Grokbot has no tool-call stream; rows are derived from `local-tool-permission`,
`cursor-agent`, `user-form`, and `widget` card entries and marked
`source: card`.

```bash
grokbot-sessions tool-calls list --table
grokbot-sessions tool-calls list --filter "card_type:eq:widget"
grokbot-sessions tool-calls get <legacy-uuid>:t2s7 --table
```

### approvals

```bash
grokbot-sessions approvals list --table
grokbot-sessions approvals list --filter "kind:eq:auto-review-approval"
grokbot-sessions approvals get <request-id> --table
```

### subagent-activity

Grokbot "subagents" are peer bots in a ROOM agent (`memberAgentIds`) and
`cursor-agent` background-composer runs, not spawned child sessions.

```bash
grokbot-sessions subagent-activity list --table
grokbot-sessions subagent-activity list --filter "kind:eq:room-member"
grokbot-sessions subagent-activity get <member-uuid> --table
```

### skills

**Degraded by design.** Grok Bot 0.47.0 exposes no method that reads the cloud
agent store (`ListAgentStoreEntries` answers HTTP 404), so `skills list`
returns an empty JSON array with an explicit note on stderr rather than
inventing records.

```bash
grokbot-sessions skills list
grokbot-sessions skills list --table
```

### todos

**Degraded by design.** Grokbot records no todo items, so `todos list` returns
an empty JSON array with an explicit note on stderr.

```bash
grokbot-sessions todos list
```

### search

Client-side keyword search across decoded transcript entries.

```bash
grokbot-sessions search run "legoscout"
grokbot-sessions search run "timeout" --table --snippets
grokbot-sessions search run "context7" --agent <legacy-uuid> --max-matches 3
```

### automations

Extension group backed by `ListGrokBotAgentAutomations` (cron/trigger
definition, enabled state, provenance, and run history).

```bash
grokbot-sessions automations list --table
grokbot-sessions automations list --filter "is_enabled:eq:True"
grokbot-sessions automations get <automation-id> --table
```

### cache

```bash
grokbot-sessions cache clear
grokbot-sessions --no-cache sessions list --limit 10
```

## Output Formats

- JSON is the default output format on stdout; messages go to stderr.
- Add `--table` / `-t` for Rich table output.
- Add `--wide` / `-w` to show every table column.

## Filtering and limits

- `--limit` is pushed into the API request where the surface allows it:
  `timeline list` passes the remaining limit to
  `ListGrokBotTranscriptEntries` as the page size, so `--limit 1` asks the
  server for one entry. `ListGrokBotAgents` has no limit field, so
  `sessions`/`projects` slice the single roster response. Derived groups
  (`conversations`, `turns`, `tool-calls`, `approvals`, `subagent-activity`,
  `automations`) read the transcript/records needed to build each row and then
  apply `--limit` to the built rows.
- `--limit 0` returns no rows (it does not mean "unlimited"), and a negative
  limit is rejected.
- `--filter` is client-side. The Grok Bot Connect methods expose no filter
  parameters, so `grokbot-sessions` fetches the unfiltered set and applies
  `field:op:value`, then cuts to `--limit`. That is why a filtered list can be
  slower than an unfiltered one.
- Filter field names are validated against the fields the command actually
  emits, so a typo or wrong case is an error naming the supported fields
  instead of a silent empty result. `eq`/`ne` are exact; use
  `like`/`ilike`/`contains` for case-insensitive matching. Filters address
  top-level fields only.
- `--properties` accepts a comma-separated list and supports dot notation for
  nested values (`--properties id,raw.id`). A requested field that exists but is
  empty is emitted as an explicit `null`; a request where no name matches any
  field on the result is an error listing the available fields.

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--wide` | `-w` | Show every column in table mode |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--agent` | `-a` | Agent id, legacy UUID, or name (repeatable) |
| `--profile` | | Auth profile name |
| `--version` | `-v` | Show version and exit |
| `--no-cache` | | Bypass cached read responses for this execution |

## Configuration

Non-authentication configuration lives in
`~/.local/share/cli-tools/grokbot-sessions/.env`. CLI-managed runtime auth
state lives in the active profile at
`~/.local/share/cli-tools/grokbot-sessions/authentication_profiles/<profile>/.env`.
The source repo only carries `.env.example`.

```bash
BASE_URL=https://api2.cursor.sh
CACHE_ENABLED=true
CACHE_TTL=3600
# Optional environment overrides (not required in .env):
#   GROKBOT_SESSIONS_APP_DIR   Grok Bot user-data directory
#   GROKBOT_SESSIONS_API_BASE  Connect RPC base URL
```

The response cache is keyed per endpoint and app directory, so pointing either
override elsewhere never serves data cached from the previous source. Cache
entries are written atomically and an unreadable entry is treated as a miss, so
a concurrent or corrupt cache file cannot wedge a command.

Do not put reusable credentials in any `.env` file. Reusable CLI credentials
are governed by the user-level `cli-tool` skill's `references/secrets.md` and
stored through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. This CLI
stores no credential of its own: it reads the desktop app's session at request
time and never prints, logs, or caches token, machine-id, account-scope, or
decrypted-secret material.

## Output Contract

| Group | Record `id` | Key fields |
|-------|-------------|------------|
| `projects` | `account-<n>` | `name`, `active`, `has_token`, `kind`, `source`, `path` |
| `sessions` | numeric agent id | `legacy_id`, `name`, `kind`, `is_group`, `harness`, `member_agent_ids`, `created_at`, `updated_at` |
| `conversations` | `<legacy uuid>:<generation>` | `entry_count`, `turn_count`, `message_count`, `first_prompt`, `last_activity`, `generation_reported` |
| `turns` | `<legacy uuid>:t<n>` | `turn`, `entry_count`, `tool_call_count`, `has_approval`, `started_at`, `ended_at` |
| `timeline` | `<legacy uuid>:<entry id>` | `seq`, `entry_kind`, `kind`, `type`, `role`, `turn`, `timestamp`, `payload` |
| `tool-calls` | `<legacy uuid>:<entry id>` | `source: card`, `tool`, `card_type`, `action`, `target`, `status` |
| `approvals` | `<legacy uuid>:<entry id>` | `request_id`, `action`, `target`, `machine_id`, `machine_label`, `status`, `resolved_value` |
| `subagent-activity` | member UUID or `<legacy uuid>:<entry id>` | `kind`, `room_name`, `member_name`, `bc_id`, `title` |
| `search run` | numeric agent id | `match_count`, `matches[]` with `snippet`, `turn`, `role` |
| `automations` | `automationId` | `name`, `is_enabled`, `trigger_type`, `schedule`, `run_count`, `record` |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/config/authentication error |
| 130 | User interrupted (Ctrl+C) |

## Examples

```bash
# Every agent's newest entries as a table
grokbot-sessions timeline consolidated --limit 30 --table

# Turn count per agent
grokbot-sessions conversations list --properties agent_name,turn_count,entry_count --table

# Approvals ordered by jq
grokbot-sessions approvals list | jq '.[].status'
```

## Requirements

- Python 3.11+
- macOS with Grok Bot installed and signed in
- Dependencies (installed automatically): typer, python-dotenv, requests,
  cryptography, cli-tools-shared

## License

MIT
