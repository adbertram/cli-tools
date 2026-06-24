# Manus CLI Guide

## DESCRIPTION

The `manus` CLI provides a command-line interface for Manus AI API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Overview

The Manus CLI provides:
- `auth` for API-key authentication
- `task` for Manus task lifecycle operations
- `usage` for credit-balance checks
- `cache` for cache management

The CLI now targets the current v2 API surface:
- Base URL: `https://api.manus.ai`
- API key header: `x-manus-api-key`
- Task endpoints: `task.create`, `task.detail`, `task.list`, `task.sendMessage`, `task.listMessages`, `task.update`, `task.stop`, `task.delete`, `task.confirmAction`
- Usage endpoint: `usage.availableCredits`

## Authentication

```bash
manus auth login
manus auth status
manus auth logout
```

## Task Commands

### Create

Create a new task. By default the CLI polls `task.listMessages` until the task stops, errors, or pauses for a confirmable user action, then returns the task plus recent messages. A `waiting` status without a confirmation event (for example a queued task that has not started running) is non-terminal and polling continues until `--timeout` expires.

Before creating a task, the CLI checks `usage.availableCredits` and fails before task creation when `total_credits <= 0`.

```bash
manus task create "Write a Python function for Fibonacci sequence"
manus task create "Analyze this document" --no-wait
manus task create "Research AI trends" --agent-profile manus-1.6-max --share-visibility team
manus task create --prompt-file /path/to/prompt.txt --connector slack --enable-skill skill-123
manus task create "Summarize this file" \
  --content-part '{"type":"file","file_url":"https://example.com/report.txt"}'
```

Key options:
- `-a, --agent-profile` chooses `manus-1.6`, `manus-1.6-lite`, or `manus-1.6-max`
- `--project-id` associates the task with a Manus project
- `--interactive/--no-interactive` controls whether the agent may pause for follow-up questions
- `--share-visibility` sets `private`, `team`, or `public`
- `--content-part` appends raw content-part JSON objects to the message body
- `--connector`, `--enable-skill`, and `--force-skill` map directly to v2 message fields
- `--structured-output-schema` or `--structured-output-schema-file` passes a JSON Schema object for structured output extraction

### Send

Send a follow-up message to an existing task.

```bash
manus task send <task-id> "What about error handling?"
manus task send <task-id> --prompt-file /path/to/followup.txt
manus task send <task-id> "Add more details" --no-wait
```

The legacy `manus task continue` command remains available as a compatibility alias, but `manus task send` is the current command.

### Get

Get the current task metadata and status from `task.detail`.

```bash
manus task get <task-id>
manus task get <task-id> --table
```

### Wait

Poll `task.listMessages` until the task reaches `stopped`, `error`, or a `waiting` status with a confirmable event (`status_update.status_detail.waiting_for_event_id` / `waiting_for_event_type`, for example `messageAskUser`). A `waiting` status without a confirmation event (for example a queued task that has not started running) is non-terminal and polling continues. On timeout the command exits non-zero.

```bash
manus task wait <task-id>
manus task wait <task-id> --verbose-messages
```

### List

List tasks from `task.list`.

```bash
manus task list
manus task list --limit 20 --table
manus task list --scope project --project-id proj_123
manus task list --filter status:eq:running --properties id,title,status
```

### Messages

List task event messages from `task.listMessages`.

```bash
manus task messages <task-id>
manus task messages <task-id> --verbose --limit 100
manus task messages <task-id> --download-files --output-dir ./downloads
```

### Update

Update task metadata with `task.update`.

```bash
manus task update <task-id> --title "Weekly Research"
manus task update <task-id> --share-visibility public
manus task update <task-id> --hidden-in-task-list
```

### Stop

Stop a running task with `task.stop`.

```bash
manus task stop <task-id>
```

### Delete

Delete a task with `task.delete`.

```bash
manus task delete <task-id>
```

### Confirm

Confirm a waiting action with `task.confirmAction`.

```bash
manus task confirm <task-id> <event-id>
manus task confirm <task-id> <event-id> --input '{"approved":true}'
manus task confirm <task-id> <event-id> --input-file /path/to/input.json
```

## Profiles

The shared auth app provides multi-profile support:

```bash
manus auth profiles list
manus auth profiles create staging
manus auth profiles select staging
manus auth profiles delete staging
```

## Cache

```bash
manus cache --help
```

## Usage

```bash
manus usage available-credits
```
