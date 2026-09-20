---
name: hermes-sessions-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Read and analyze Hermes Agent session state using the `hermes-sessions` CLI tool.
  Read-only analysis of the local Hermes `state.db`: projects, sessions, conversations, turns, tool calls, todos, skills, subagent activity, timeline, and full-text search. It has no mutating commands.
  Triggers: hermes-sessions, hermes sessions, hermes session history, hermes transcript, what did hermes do, hermes tool calls, hermes subagents, hermes timeline, hermes todos, hermes cron session, analyze a hermes run.
---

<objective>
Answer questions about what a Hermes Agent run actually did by querying the local Hermes state store with the `hermes-sessions` CLI.
</objective>

<quick_start>
The `hermes-sessions` CLI follows this pattern:
```bash
hermes-sessions <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check authentication status across profiles | `hermes-sessions auth status` |
| Get one context segment, addressed as <session-id>:<number> | `hermes-sessions conversations get <REFERENCE>` |
| List context segments | `hermes-sessions conversations list` |
| Get details for one workspace | `hermes-sessions projects get <NAME>` |
| List every workspace that has Hermes sessions | `hermes-sessions projects list` |
| Search message content through the Hermes FTS5 index | `hermes-sessions search run <QUERY>` |
| Get one session's metadata and counts | `hermes-sessions sessions get [SESSION_ID]` |
| List sessions newest-first | `hermes-sessions sessions list` |
| Search session titles | `hermes-sessions sessions search <QUERY>` |
| Get one skill load or slash command by its record ID | `hermes-sessions skills get <REFERENCE>` |
| List skill loads (kind=skill) and slash commands (kind=command) | `hermes-sessions skills list` |
| Get one subagent run by its child session ID | `hermes-sessions subagent-activity get <CHILD_SESSION_ID>` |
| List delegated subagent runs | `hermes-sessions subagent-activity list` |
| Merge a session and its subagent runs into one bounded chronological view | `hermes-sessions timeline consolidated [SESSION_ID]` |
| Get the full event timeline of one session | `hermes-sessions timeline get [SESSION_ID]` |
| List activity events across the scoped sessions | `hermes-sessions timeline list` |
| Get one todo item, addressed as <session-id>:<position> | `hermes-sessions todos get <REFERENCE>` |
| List todo items | `hermes-sessions todos list` |
| Get one tool call by its call ID | `hermes-sessions tool-calls get <CALL_ID>` |
| List tool calls across the scoped sessions | `hermes-sessions tool-calls list` |
| Get one turn, addressed as <session-id>:<number> | `hermes-sessions turns get <REFERENCE>` |
| List turns across the scoped sessions | `hermes-sessions turns list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `hermes-sessions` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `hermes-sessions --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Read-Only By Design">
`hermes-sessions` never writes anything. It opens `state.db` through a SQLite
`mode=ro` URI, and its entire recursive command tree contains no mutation
command — no delete, prune, rename, fork, create, update, or select.

`auth status` is the ONLY `auth` command. There is no `auth login`, `auth
logout`, `auth test`, or `auth profiles` here, unlike most cli-tools CLIs: this
tool holds no credential, so there is nothing to log into and no profile state
to write. Do not suggest or run those commands against `hermes-sessions`.

For any Hermes change, use the `hermes-agent` skill and Hermes' own surfaces
instead; do not reach for this CLI.
</principle>

<principle name="Bounded, Redacted Output">
Every text field is a bounded preview, not a transcript. `--max-chars` (default
200) caps each preview, including todo content. A redactor masks Bearer/Basic
authorization, AWS access-key IDs, credentials embedded in URLs or `curl -u`,
`sk-`/`ghp_`/`xoxb-` style keys, and quoted or unquoted
`*key`/`*secret`/`*token`/`password` assignments. Keep `--limit` small when
exploring; `timeline consolidated` is bounded by both `--limit` and
`--max-chars`. Do not try to reconstruct a raw transcript from these previews.
</principle>

<principle name="Hermes Home Resolution">
The CLI reads `$HERMES_HOME/state.db`. Resolution order is
`HERMES_SESSIONS_HERMES_HOME`, then `HERMES_HOME` (environment or this tool's
config `.env`), then `~/.hermes`. Each Hermes profile is its own home
directory. Run `hermes-sessions auth status` first: it reports the resolved
home and whether the store is readable.
</principle>

<principle name="Scoping A Query">
Message-derived groups (`conversations`, `turns`, `tool-calls`, `todos`,
`skills`, `timeline`) scan sessions newest-first until `--limit` rows exist.
Narrow them with `--session-id/-S` (an id or a title), `--session-name/-N`,
`--project/-p`, `--source` (`cli`, `cron`, `slack`, `subagent`, `webui`,
`email`, `telegram`), and exactly one of `--since/-s`, `--date`,
`--date-range`, `--date-alias`.
</principle>

<principle name="Command Groups">
- **auth** -- Check local Hermes state access (subcommands: status)
- **conversations** -- List conversations within sessions (subcommands: get, list)
- **projects** -- List and query projects (subcommands: get, list)
- **search** -- Search keywords across session transcripts (subcommands: run)
- **sessions** -- List, get, and search sessions (subcommands: get, list, search)
- **skills** -- Query skill loads and slash commands (subcommands: get, list)
- **subagent-activity** -- Query subagent invocations (subcommands: get, list)
- **timeline** -- View unified activity timeline (subcommands: consolidated, get, list)
- **todos** -- Query todo items from sessions (subcommands: get, list)
- **tool-calls** -- Query tool call history (subcommands: get, list)
- **turns** -- Query agent turns (subcommands: get, list)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`hermes-sessions --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
