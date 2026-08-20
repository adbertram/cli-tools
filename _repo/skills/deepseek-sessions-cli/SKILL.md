---
name: deepseek-sessions-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Use the `deepseek-sessions` CLI for ALL queries against DeepSeek Harness (dsh) session data in `~/.dsh` — sessions, projects, conversations, subagents, tool calls, todos, skills, timelines, turns, retries, approvals, and goals. DO NOT read, decompress, or parse `~/.dsh/sessions/**/session.jsonl*` by hand; the logs are concatenated Zstandard frames with a harness-specific event vocabulary.
  Triggers: deepseek-sessions, dsh sessions, DeepSeek Harness sessions, what did dsh do, dsh token usage, dsh subagents, dsh transcript, resume a dsh session, ~/.dsh
---

<objective>
Answer any question about a DeepSeek Harness (`dsh`) run using the `deepseek-sessions` CLI, which reads the local session logs in `~/.dsh`.
</objective>

<quick_start>
The `deepseek-sessions` CLI follows this pattern:
```bash
deepseek-sessions <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Get details for one approval request | `deepseek-sessions approvals get <APPROVAL_ID>` |
| List permission escalation requests and their decisions | `deepseek-sessions approvals list` |
| Configure authentication credentials | `deepseek-sessions auth login` |
| Clear stored credentials | `deepseek-sessions auth logout` |
| Create a new profile from .env.example template | `deepseek-sessions auth profiles create <NAME>` |
| Delete a profile and its data | `deepseek-sessions auth profiles delete <NAME>` |
| Get details for a specific profile | `deepseek-sessions auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `deepseek-sessions auth profiles list` |
| Delete a profile and its data | `deepseek-sessions auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `deepseek-sessions auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `deepseek-sessions auth profiles select <NAME>` |
| Check authentication status across profiles | `deepseek-sessions auth status` |
| Test authentication by verifying credentials work across profiles | `deepseek-sessions auth test` |
| Get one conversation, including its user and assistant messages | `deepseek-sessions conversations get [CONVERSATION_ID]` |
| List conversations within a project's sessions | `deepseek-sessions conversations list` |
| Get every recorded revision of one goal | `deepseek-sessions goals get <GOAL_ID>` |
| List standing-goal revisions in a project | `deepseek-sessions goals list` |
| Get details for a specific project | `deepseek-sessions projects get <NAME>` |
| List all projects that have dsh sessions | `deepseek-sessions projects list` |
| Get details for one retry | `deepseek-sessions retries get <RETRY_ID>` |
| List retryable provider failures in a project | `deepseek-sessions retries list` |
| Search keywords across every dsh session transcript | `deepseek-sessions search run <QUERY>` |
| Get full session details including messages, tool calls, and subagents | `deepseek-sessions sessions get [SESSION_ID]` |
| List sessions | `deepseek-sessions sessions list` |
| Search for sessions whose transcript contains a query string | `deepseek-sessions sessions search <QUERY>` |
| Get details for a specific skill load or slash command | `deepseek-sessions skills get <SKILL_ID>` |
| List skill loads (`skill` tool calls) and slash commands in a project | `deepseek-sessions skills list` |
| Get full details for a subagent, including its child session messages | `deepseek-sessions subagent-activity get <SUBAGENT_ID>` |
| List every subagent session spawned inside a project | `deepseek-sessions subagent-activity list` |
| Show one session plus every subagent it spawned in a single timeline | `deepseek-sessions timeline consolidated` |
| Get the timeline for one session | `deepseek-sessions timeline get [SESSION_ID]` |
| Show a unified timeline across a project's sessions | `deepseek-sessions timeline list` |
| Get a specific todo by ID | `deepseek-sessions todos get <TODO_ID>` |
| List the final todo list of each session in a project | `deepseek-sessions todos list` |
| Get details for a specific tool call | `deepseek-sessions tool-calls get <TOOL_CALL_ID>` |
| List tool calls in a project | `deepseek-sessions tool-calls list` |
| Get one turn plus the model round-trips (steps) inside it | `deepseek-sessions turns get <TURN>` |
| List agent turns with their finish reason, duration, and token cost | `deepseek-sessions turns list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `deepseek-sessions` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `deepseek-sessions --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **approvals** -- Query permission escalation requests (subcommands: get, list)
- **auth** -- Check local dsh access (subcommands: login, logout, profiles, status, test)
- **conversations** -- List conversations within sessions (subcommands: get, list)
- **goals** -- Query standing goals and their revisions (subcommands: get, list)
- **projects** -- List and query projects (subcommands: get, list)
- **retries** -- Query LLM retries and failure codes (subcommands: get, list)
- **search** -- Search keywords across all session transcripts (subcommands: run)
- **sessions** -- List, get, and search sessions (subcommands: get, list, search)
- **skills** -- Query skill loads and slash commands (subcommands: get, list)
- **subagent-activity** -- Query subagent invocations (subcommands: get, list)
- **timeline** -- View unified activity timeline (subcommands: consolidated, get, list)
- **todos** -- Query todo items from sessions (subcommands: get, list)
- **tool-calls** -- Query tool call history (subcommands: get, list)
- **turns** -- Query agent turns and their steps (subcommands: get, list)
</principle>

<principle name="Never Hand-Parse The Logs">
`dsh` stores each session as `~/.dsh/sessions/<projectKey>/<sessionId>/session.jsonl.zstd`
— a container of independently appended Zstandard frames, not a plain file.
A killed process leaves a partial trailing frame. Use this CLI, which performs
the same truncation repair the harness does and reports it as
`truncated: true`. Do not `zstd -dc` and grep the JSONL by hand.
</principle>

<principle name="Session IDs Reveal Their Origin">
`session-<uuid>` is a session a human drove. A bare `<uuid>` is a subagent
session spawned by another one; its header carries `origin: subagent`,
`parentSession`, and `delegationDepth`. `sessions list --no-subagents` hides
them; `--filter "origin:eq:subagent"` shows only them. Both forms are accepted
anywhere a session ID is taken, and a session title works too.
</principle>

<principle name="Subagents Are Separate Sessions">
A `dsh` subagent is not a tool result inside the parent — it is a whole session
with its own turns, tool calls, and token cost. `subagent-activity list` joins
the child's cost and outcome to the parent's `subagent` tool call, and
`timeline consolidated` merges parent and children into one chronological view.
To total the cost of a delegated run, sum the parent AND its children.
</principle>

<principle name="Token Fields Are Not Claude's">
`total_input_tokens` is UNCACHED input; cache reads are counted separately in
`total_cache_read_tokens` and are NOT inside it. `total_reasoning_tokens` is a
subset of `total_output_tokens`. `effective_tokens` is
`input + output + (cache_read x 0.1)`. Claude Code's input count already
includes cache reads, so never compare `effective_tokens` across the two tools
as though the formula matched. These values are verified against the harness's
own rollup in `~/.dsh/storages/session_projcache.json`.
</principle>

<principle name="A Conversation Is A Compaction Segment">
`dsh` has no `/clear`. A conversation here is the run of turns between context
compactions, numbered from 1; a session never compacted has exactly one.
`conversations list --filter "started_by:eq:compaction"` finds the segments
that began with a compaction.
</principle>

<principle name="Project Names Come From The Log, Not The Directory">
The project directory name is a lossy encoding of the working directory
(`/`, `\`, and `:` all collapse to `-`), so it cannot be reversed. A project
may be named by its basename, its absolute path, or its directory key. Trust
`full_path` in the output, not the directory name.
</principle>

<principle name="Turn And Step Counts Have Exact Meanings">
`step_count` counts COMPLETED model round-trips, matching the harness's own
number. `open_step_count` counts steps that began but never closed because the
session was killed mid-request. A turn's `finish_reason` is `completed`,
`error`, or `aborted`, and is absent when the turn never closed.
</principle>

<principle name="Filters Run Before The Limit">
Every `list` accepts `--filter field:op:value` (repeatable, AND) and applies it
to the whole result set before `--limit` caps the output, so
`--limit 5 --filter X` returns up to 5 MATCHING rows. Default output is JSON;
`--table` renders a lean table and `--wide` adds the remaining columns.
</principle>

<principle name="No Authentication Exists">
This CLI reads local files. `auth status` reports whether `~/.dsh` is readable.
Do not look for credentials in the CLI-tools secret manager for this tool, and
do not run `auth login` expecting a service handshake.
</principle>
</essential_principles>


<common_questions>
| Question | Command |
|----------|---------|
| What did dsh work on recently? | `deepseek-sessions sessions list --no-subagents --table` |
| What ran yesterday? | `deepseek-sessions sessions list --date-alias yesterday --table` |
| What did one session actually do? | `deepseek-sessions timeline get <SESSION_ID> --table` |
| Everything including its subagents | `deepseek-sessions timeline consolidated -S <SESSION_ID> --table` |
| Where did a run fail? | `deepseek-sessions timeline list -p <PROJECT> --errors-only --table` |
| Which turns errored? | `deepseek-sessions turns list -p <PROJECT> --filter "finish_reason:eq:error" --table` |
| Were there provider timeouts? | `deepseek-sessions retries list -p <PROJECT> --filter "error_code:eq:TIMEOUT" --table` |
| What did the subagents cost? | `deepseek-sessions subagent-activity list -p <PROJECT> --wide --table` |
| Which subagents failed? | `deepseek-sessions subagent-activity list -p <PROJECT> --filter "status:eq:error"` |
| Find a session by content | `deepseek-sessions search run "<KEYWORD>" --snippets --table` |
| What was the agent told to do? | `deepseek-sessions goals list -p <PROJECT> --table` |
| What did it ask permission for? | `deepseek-sessions approvals list -p <PROJECT> --table` |
| Which skills were loaded? | `deepseek-sessions skills list -p <PROJECT> --table` |
| Which bash commands ran? | `deepseek-sessions tool-calls list -p <PROJECT> --filter "tool:eq:bash" --wide --table` |
| Unfinished todos | `deepseek-sessions todos list -p <PROJECT> --filter "status:ne:completed" --table` |

Totals compose through `jq` because JSON is the default output:

```bash
deepseek-sessions sessions list --limit 1000 \
  | jq 'map(.effective_tokens) | add'

deepseek-sessions turns list -p <PROJECT> --limit 1000 \
  | jq 'group_by(.finish_reason) | map({reason: .[0].finish_reason, turns: length})'
```
</common_questions>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`deepseek-sessions --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
