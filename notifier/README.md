# Notifier CLI

A command-line wrapper for [terminal-notifier](https://github.com/julienXX/terminal-notifier) to send macOS desktop notifications.

## Prerequisites

Install terminal-notifier:

```bash
brew install terminal-notifier
```

**Important:** After installing, you must enable notifications for terminal-notifier in System Settings > Notifications > terminal-notifier.

## Installation

```bash
cd notifier
pip install -e .
```

## Commands

### send

Send a desktop notification.

```bash
# Basic notification
notifier send --message "Hello World"

# With title and sound
notifier send --message "Build complete" --title "CI/CD" --sound default

# Short form
notifier send -m "Task done" -T "My App"

# With subtitle
notifier send -m "Download finished" -T "Downloader" -s "100% complete"

# Ignore Do Not Disturb
notifier send -m "Urgent alert" --ignore-dnd

# Pipe message from stdin
echo "Process finished" | notifier send -T "Background Job"
```

**Options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--message` | `-m` | Notification message (or pipe via stdin) |
| `--title` | `-T` | Notification title |
| `--subtitle` | `-s` | Notification subtitle |
| `--sound` | | Sound to play (e.g., 'default', 'Basso', 'Blow') |
| `--ignore-dnd` | | Send even if Do Not Disturb is enabled |

### auth status

Check if terminal-notifier is installed.

```bash
notifier auth status
notifier auth status --table
```

### auth login

Verify terminal-notifier is ready (no actual authentication needed).

```bash
notifier auth login
notifier auth login --force
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | terminal-notifier not installed |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Notify when a long-running command finishes

```bash
make build && notifier send -m "Build succeeded" -T "Make" --sound default || notifier send -m "Build failed" -T "Make"
```

### Notify from a script

```bash
#!/bin/bash
# backup.sh
rsync -av /source /dest
notifier send -m "Backup complete" -T "Backup Script" --sound Blow
```

## Requirements

- macOS
- Python 3.9+
- terminal-notifier (`brew install terminal-notifier`)

## License

MIT
