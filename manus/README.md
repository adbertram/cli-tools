# Manus CLI Guide

Complete reference for the `manus` command-line interface for interacting with Manus AI services.

## Overview

The Manus CLI provides access to:
- **Auth** - Manage API authentication
- **Tasks** - Create, manage, and retrieve AI tasks
- **Profiles** - Manage configuration profiles

## Authentication

### Login

```bash
manus auth login
manus auth login --api-key <your-key>
```

### Check Status

```bash
manus auth status
manus auth status
```

### Logout

```bash
manus auth logout
```

---

## Task Commands

Manage AI tasks.

### Create Task

Create a new AI task. You can wait for completion or run it asynchronously.

```bash
# Create and wait for result
manus task create "Write a Python function for Fibonacci sequence"

# Async creation (don't wait)
manus task create "Analyze this document" --no-wait

# Shareable link
manus task create "Research AI trends" --share

# Specific profile and mode
manus task create "Complex reasoning" --profile manus-1.5 --mode agent
```

**Options:**
| Option | Description |
|--------|-------------|
| `-p, --profile` | Agent profile (default: `manus-1.5`, options: `manus-1.5`, `manus-1.5-lite`) |
| `-m, --mode` | Task mode (default: `agent`, options: `chat`, `adaptive`, `agent`) |
| `-w, --wait/--no-wait` | Wait for task completion (default: True) |
| `--timeout` | Max seconds to wait (default: 900.0) |
| `-s, --share` | Create shareable link |
| `--hide` | Hide from webapp task list |
| `-l, --locale` | Locale setting (e.g., en-US) |
| `-q, --quiet` | Suppress status messages |

### Continue Task

Continue an existing task conversation.

```bash
# Continue with a follow-up message
manus task continue <task-id> "What about error handling?"

# Read follow-up from file
manus task continue <task-id> --prompt-file /path/to/followup.txt

# Async continuation
manus task continue <task-id> "Add more details" --no-wait
```

**Options:**
| Option | Description |
|--------|-------------|
| `-f, --prompt-file` | Read prompt from file instead of argument |
| `-w, --wait/--no-wait` | Wait for task completion (default: True) |
| `--timeout` | Max seconds to wait (default: 900.0) |
| `--poll` | Seconds between status checks |
| `-a, --attachment` | Attachment as JSON object |
| `--connector` | Connector ID to enable |
| `-q, --quiet` | Suppress status messages |

### Get Task

Get task status and results.

```bash
manus task get <task-id>
manus task get <task-id> --download-files
```

**Options:**
| Option | Description |
|--------|-------------|
| `-d, --download-files` | Download output files from the task |
| `-o, --output-dir` | Directory for downloaded files (default: current dir) |

### Wait for Task

Wait for an existing task to complete.

```bash
manus task wait <task-id>
```

**Options:**
| Option | Description |
|--------|-------------|
| `--timeout` | Max seconds to wait (default: 900.0) |
| `--poll` | Seconds between status checks |
| `-q, --quiet` | Suppress status messages |

### List Tasks

List recent tasks.

```bash
manus task list
manus task list
manus task list --limit 20
```

**Options:**
| Option | Description |
|--------|-------------|
| `-l, --limit` | Maximum number of tasks to return (default: 10) |
| `-t, --table` | Display as formatted table |
| `-f, --filter` | Filter results (field:op:value syntax, e.g., status:eq:completed) |
| `-p, --properties` | Comma-separated list of properties to include |

---

## Profile Commands

Manage configuration profiles for multiple accounts.

### List Profiles

```bash
manus auth profiles list
```

### Create Profile

```bash
manus auth profiles create staging
```

### Set Default Profile

```bash
manus auth profiles set-default staging
```

### Delete Profile

```bash
manus auth profiles delete staging
```

## Additional Commands

### Cache

```bash
manus cache --help
```
