# muse-chat

## DESCRIPTION

`muse-chat` sends messages to the Muse personal agent through a free local
browser session. It can submit to the main chat, create side chats, or hold a
session open until Muse finishes responding.

## Installation

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/install-cli-tool.sh --force-refresh muse-chat
```

The installer provides the `muse-chat` command and the shared browser engine.

## Authentication

```bash
muse-chat auth login
muse-chat auth status
muse-chat auth logout
```

Login opens the standard CLI-owned persistent Chrome profile. Complete the Muse
sign-in once in that window. Later commands use the saved session headlessly.
`auth status` performs a live check: it reports authenticated only when the Muse
message composer loads and the logged-out landing pane is absent.

When the Muse web session expires, Muse shows its logged-out landing pane with
the saved account card. Chat commands click the saved "Log in as ... using
Facebook" card headlessly in the CLI-owned profile and continue. No password is
typed. If no saved account card is shown, the command exits 2 and asks you to
run `muse-chat auth login`.

## Send messages

Send to the main chat and return as soon as the user turn appears in history:

```bash
muse-chat chat send "Summarize today's priorities."
```

Send to one exact side-chat UUID:

```bash
muse-chat chat send "Continue the analysis." \
  --chat-id eb431c8c-6348-4ba9-9aed-11908cf2d0ed
```

Wait for the final response:

```bash
muse-chat chat send "Return the final answer." --monitor --timeout 120
```

The default timeout is 120 seconds. Timeout values must be positive and finite.

## Side chats

Create a side chat and return its durable UUID after Muse accepts the first
message:

```bash
muse-chat side create "Research this in a separate chat."
```

Create and monitor it in one command:

```bash
muse-chat side create "Reply with the completed result." --monitor --timeout 120
```

Every successful side-chat submission returns `chat_id`, including a monitored
command that times out.

## Resume monitoring

```bash
muse-chat chat monitor f9247f71-38d6-4e35-8f31-e68046fcbec3 --timeout 120
```

`chat monitor` follows the latest persisted user turn. It does not submit a new
message, so use it after a timeout rather than repeating `chat send` or
`side create`.

## Inspect chats

```bash
muse-chat chat list --limit 20
muse-chat chat get eb431c8c-6348-4ba9-9aed-11908cf2d0ed
```

Use `main` as the chat ID when reading or monitoring the main chat.

## Output and exits

JSON is written to stdout by default. `--table` is available for human-readable
output. Logs go to stderr.

A send-only result has `status: "sent"`. A monitored result has one of these
statuses:

- `completed`: `response` contains the final displayed reply, with newlines and
  indentation preserved.
- `timeout`: the command exits 1 and returns `chat_id`, any partial `response`,
  `timeout_seconds`, and `remote_task_cancelled: false`.
- `approval_required`: Muse displayed a control that needs human approval.

Muse mutations are submitted once. If the browser cannot confirm the user turn,
the command reports an ambiguous send and does not retry it.

Authentication failures exit 2. Interrupting the command exits 130.

## Configuration

Non-secret configuration lives at
`~/.local/share/cli-tools/muse-chat/.env`. Authentication profiles and browser
state use the standard shared CLI-tools locations. The source repository only
contains `.env.example`.

```bash
BASE_URL=https://muse.ai
HEADLESS=true
CACHE_ENABLED=true
CACHE_TTL=3600
```

## Development

```bash
uv sync --project muse-chat
uv run --project muse-chat --with pytest python -m pytest muse-chat/tests -q
```

The CLI requires Python 3.11 or newer.

### Multipart replies and saved side-chat turns

A completed reply includes all ordered assistant message components carrying
one durable response turn ID, including prose and task cards. Distinct message
IDs are preserved even when their text is identical. Replies from different
turns remain ambiguous and are never silently combined. Monitoring waits for
one second of unchanged, idle response content; new components, text changes,
or typing/working activity restart that window within the total timeout.

`chat get` returns a history snapshot. For idle history it waits up to five
seconds for one second of unchanged messages so delayed card hydration can
finish. Active replies remain snapshots; use `chat monitor` to wait for final
content. Browser hydration can change beyond that bounded window, so the CLI
does not claim an authoritative server-side completion event.

A newly created side chat can replace its temporary user-message ID while it
saves. Monitoring tolerates a bounded empty-history gap and reanchors only to
that new chat's unique user turn with the exact normalized submitted text.
Other user turns or mismatching text still fail correlation. No prompt is
resent during reconciliation.

Regression verified 2026-10-20: a task card previously replaced the prose in
monitor output because only the last same-turn component was selected. Initial
history hydration could also return only prose before the card appeared. The
ordered aggregation and idle window fix both paths; synthetic tests cover
multiple components, repeated polls, activity, deadlines, and draft-ID gaps.
