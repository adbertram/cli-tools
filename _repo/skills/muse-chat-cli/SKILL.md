---
name: muse-chat-cli
description: >-
  Use this skill for Muse personal-agent service operations only. Do not use it
  for CLI implementation lifecycle work; delegate that work to cli-tool-expert.
  MANDATORY: Execute Muse personal-agent chat operations with the `muse-chat`
  CLI. Triggers: Muse chat, Muse personal agent, muse-chat, muse-chat cli.
---

<objective>
Send messages to the Muse main chat, create side chats, and monitor replies with
the `muse-chat` CLI.
</objective>

<project_overrides>
Before acting on this skill, run:

```bash
~/.agents/skills/skill-expert/scripts/load-skill-overrides.sh muse-chat-cli
```

Apply any printed instructions alongside this skill's own workflow: they extend it and
never repeal its limits. No output means no project override is in effect. A non-zero
exit means the project's override file is broken -- report it and stop rather than
silently running unmodified.
</project_overrides>

<quick_start>
The CLI follows this pattern:

```bash
muse-chat <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Sign in with the persistent browser profile | `muse-chat auth login` |
| Check live authentication | `muse-chat auth status` |
| Send to the main chat and return immediately | `muse-chat chat send <MESSAGE>` |
| Send to a specific side chat | `muse-chat chat send <MESSAGE> --chat-id <UUID>` |
| Send and wait for the final reply | `muse-chat chat send <MESSAGE> --monitor --timeout <SECONDS>` |
| Resume monitoring the latest turn | `muse-chat chat monitor <CHAT_ID> --timeout <SECONDS>` |
| Create a side chat and return immediately | `muse-chat side create <MESSAGE>` |
| Create a side chat and wait for the reply | `muse-chat side create <MESSAGE> --monitor --timeout <SECONDS>` |
| List durable chat IDs | `muse-chat chat list` |
| Read chat history | `muse-chat chat get <CHAT_ID>` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` before executing any
`muse-chat` command.** It is the canonical command map for arguments, options,
defaults, and nested command paths. Never guess command syntax.
</principle>

<principle name="Command Groups">
- **auth** manages browser-session login, logout, status, and profiles.
- **cache** clears shared command cache state.
- **chat** sends, monitors, lists, and reads chats.
- **side** creates a new side chat from its first message.
</principle>

<principle name="Monitoring">
Use `--monitor` only when the caller needs the final response in the same
command. Timeouts are positive finite seconds and default to 120. A timeout
returns JSON with `status: "timeout"`, the durable chat ID, and
`remote_task_cancelled: false`, then exits nonzero. Resume with `chat monitor`;
do not resend the prompt.
</principle>

<principle name="Output">
JSON is the default stdout format. Logs go to stderr. A send-only command
returns after Muse confirms the user turn in history; it does not wait for the
assistant. An `approval_required` result means human input is needed in Muse.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete generated command tree, arguments, options, and defaults.
**`muse-chat --help` and subcommand `--help`** -- Live installed command surface.
**`README.md`** -- Authentication, response contracts, and examples.
</reference_index>

<success_criteria>
- The exact requested main or side chat is used.
- Send-only commands return a confirmed submission record.
- Monitored commands return the final reply, a structured timeout, or an approval gate.
- Durable chat IDs are preserved so monitoring can resume without resending.
</success_criteria>

<response_correlation>
Completed monitor output combines ordered assistant components with the same
durable turn ID, including prose and cards. Different turn IDs remain an error.
Completion requires one second of unchanged idle content within the overall
timeout; new text/components or activity reset settling. `chat get` is a
snapshot, with bounded idle hydration settling (up to five seconds), and may
show an active partial response. Use monitor for final replies.

Only newly created side chats can reconcile a temporary submitted-message ID:
a bounded empty-history gap is tolerated, then the unique saved user turn must
exactly match normalized submitted text. Existing chats never reanchor by text,
and reconciliation never resends the message.
</response_correlation>
