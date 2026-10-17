---
name: grokbot-sessions-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute GrokbotSessions operations using the `grokbot-sessions` CLI tool.
  CLI interface for GrokbotSessions.
  Triggers: grokbot-sessions, grokbot-sessions cli
---

<objective>
Execute GrokbotSessions operations using the `grokbot-sessions` CLI. All GrokbotSessions interactions should use this CLI.
</objective>

<quick_start>
The `grokbot-sessions` CLI follows this pattern:
```bash
grokbot-sessions <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Get one approval request | `grokbot-sessions approvals get <APPROVAL_ID>` |
| List permission requests and automatic review approvals | `grokbot-sessions approvals list` |
| Configure authentication credentials | `grokbot-sessions auth login` |
| Clear stored credentials | `grokbot-sessions auth logout` |
| Create a new profile from .env.example template | `grokbot-sessions auth profiles create <NAME>` |
| Delete a profile and its data | `grokbot-sessions auth profiles delete <NAME>` |
| Get details for a specific profile | `grokbot-sessions auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `grokbot-sessions auth profiles list` |
| Delete a profile and its data | `grokbot-sessions auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `grokbot-sessions auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `grokbot-sessions auth profiles select <NAME>` |
| Check authentication status across profiles | `grokbot-sessions auth status` |
| Test authentication by verifying credentials work across profiles | `grokbot-sessions auth test` |
| Get one automation with its full record | `grokbot-sessions automations get <AUTOMATION_ID>` |
| List the automations attached to Grok Bot agents | `grokbot-sessions automations list` |
| Remove all cached responses | `grokbot-sessions cache clear` |
| Get one conversation with its decoded transcript entries | `grokbot-sessions conversations get <CONVERSATION_ID>` |
| List one conversation per agent generation, with entry and turn counts | `grokbot-sessions conversations list` |
| Get one implicit project | `grokbot-sessions projects get <PROJECT_ID>` |
| List Grokbot's implicit projects | `grokbot-sessions projects list` |
| Search every selected agent's transcript for a keyword | `grokbot-sessions search run <QUERY>` |
| Get one Grok Bot agent | `grokbot-sessions sessions get <SESSION_ID>` |
| List Grok Bot agents, one per session | `grokbot-sessions sessions list` |
| Search Grok Bot agents by name, title, description, or id | `grokbot-sessions sessions search <QUERY>` |
| Get one skill (never found: the API exposes no agent store) | `grokbot-sessions skills get <SKILL_ID>` |
| List agent-store skills (always empty: the API exposes no store) | `grokbot-sessions skills list` |
| Get one subagent surface, with the member's conversation summary | `grokbot-sessions subagent-activity get <SUBAGENT_ID>` |
| List room memberships and cursor-agent runs | `grokbot-sessions subagent-activity list` |
| Interleave every agent's transcript entries by timestamp, newest first | `grokbot-sessions timeline consolidated` |
| Get one decoded transcript entry | `grokbot-sessions timeline get <ENTRY_ID>` |
| List transcript entries, newest first within each agent | `grokbot-sessions timeline list` |
| Get one todo item (never found: Grokbot records none) | `grokbot-sessions todos get <TODO_ID>` |
| List todo items (always empty: Grokbot records none) | `grokbot-sessions todos list` |
| Get one derived tool call | `grokbot-sessions tool-calls get <TOOL_CALL_ID>` |
| List interactive card entries that stand in for Grokbot tool calls | `grokbot-sessions tool-calls list` |
| Get one turn with its entries in chronological order | `grokbot-sessions turns get <TURN_ID>` |
| List turns grouped from each agent's transcript, newest turn first | `grokbot-sessions turns list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `grokbot-sessions` command.**
Consult the adjacent `usage.json` at
`<cli-tools-root>/_repo/skills/grokbot-sessions-cli/usage.json`, the live
`grokbot-sessions --help` / subcommand `--help` output, and `README.md`. Never
guess at command syntax.
</principle>

<principle name="Live Session, No Local Replica">
Grok Bot is an Electron desktop app whose agents run in Cursor-hosted cloud
boxes. `grokbot-sessions` is live-API only: it reads
`~/Library/Application Support/Grok Bot/sand-secrets.json` plus the macOS
Keychain item `Grok Bot Safe Storage` / `Grok Bot Key`, and it never reads a
local transcript replica.

- Open Grok Bot and sign in first. `grokbot-sessions auth login` **adopts** the
  session the desktop app already holds and cannot mint a token.
- Never print, log, copy, or store the token, machine id, account scope, or any
  decrypted value. Use `auth status` / `auth test` for evidence instead.
- Transcript calls require the agent's UUID `legacyAgentId`. The numeric `id`
  returns HTTP 200 with an empty body, so pass the UUID or the numeric id and
  let the CLI resolve it (it always resolves first). Get real ids from
  `grokbot-sessions sessions list`.
</principle>

<principle name="Degraded Groups">
- `skills list` and `todos list` are deliberately degraded: Grok Bot 0.47.0
  exposes no agent-store read method and records no todo items. Both return an
  empty JSON array plus an explanatory note on stderr rather than invented
  records. Do not treat the empty result as a CLI failure.
- `tool-calls` rows are derived from interactive card entries
  (`local-tool-permission`, `cursor-agent`, `user-form`, `widget`) and are
  marked `source: card`; they are not a native tool-call stream.
- `subagent-activity` reports ROOM `memberAgentIds` peers and `cursor-agent`
  runs, not spawned child sessions.
</principle>

<principle name="Command Groups">
- **approvals** -- Query permission and review approvals (subcommands: get, list)
- **auth** -- Adopt and check the Grok Bot desktop session (subcommands: login, logout, profiles, status, test)
- **automations** -- Query Grok Bot automations (subcommands: get, list)
- **cache** -- Manage response cache (subcommands: clear)
- **conversations** -- List conversations within agents (subcommands: get, list)
- **projects** -- List implicit Grokbot projects (subcommands: get, list)
- **search** -- Search keywords across transcript entries (subcommands: run)
- **sessions** -- List, get, and search Grok Bot agents (subcommands: get, list, search)
- **skills** -- Query agent-store skills (unsupported) (subcommands: get, list)
- **subagent-activity** -- Query room members and cursor-agent runs (subcommands: get, list)
- **timeline** -- View transcript timelines (subcommands: consolidated, get, list)
- **todos** -- Query todo items (unsupported) (subcommands: get, list)
- **tool-calls** -- Query tool call cards (subcommands: get, list)
- **turns** -- Query agent turns and their entries (subcommands: get, list)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`grokbot-sessions --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
