# ntfy-cli

## DESCRIPTION

`ntfy-cli` is a structured wrapper around the official `ntfy` executable. It covers publishing, polling, streaming subscriptions, local server administration, and exact upstream passthrough without taking ownership of ntfy credentials.

Use it when automation needs JSON or table output while retaining access to the complete upstream CLI.

## Requirements

- Python 3.11+
- Official `ntfy` executable
- Homebrew on macOS for automatic upstream provisioning
- Server-capable Linux ntfy build for `server serve`, users, access, and token administration

The macOS Homebrew ntfy package supports publish and subscribe operations, but omits server commands. `ntfy-cli` reports a capability error when a dedicated server administration command is used with that build.

## Installation

From the cli-tools repository:

```bash
_repo/skills/cli-tool/scripts/install-cli-tool.sh --force-refresh ntfy-cli
```

The project scaffold provisions the official macOS executable through Homebrew. To install or repair it manually:

```bash
brew install ntfy
```

Verify both layers:

```bash
ntfy-cli --version
ntfy-cli auth status
```

## Credentials

Credentials remain entirely upstream-owned. `ntfy-cli` does not store usernames, passwords, or access tokens in its `.env` file and has no login or logout command.

Configure reusable credentials in ntfy's standard client configuration, or pass `--user` or `--token` to a message command. `--user` and `--token` are mutually exclusive. `auth status` only checks local executable readiness and upstream version; it does not test a remote account.

## Quick Start

```bash
ntfy-cli messages publish my-topic "Backup complete" --title Backup
ntfy-cli messages poll my-topic --since 1h --limit 10
ntfy-cli messages subscribe my-topic
```

## Commands

### `auth status`

Reports local readiness as JSON using the standard profile envelope:

```bash
ntfy-cli auth status
```

The result includes the default profile, upstream credential ownership, executable availability, and upstream version. `authenticated` reports local readiness only; this command does not test remote credentials.

### `messages publish`

Publishes one message and returns the upstream message object as JSON. Add `--table` for a human-readable row. Message text is sent to upstream stdin, not included in subprocess arguments or wrapper activity logs.

```bash
ntfy-cli messages publish TOPIC [BODY]
ntfy-cli messages publish alerts "Deploy complete" --title Production --priority high --tags white_check_mark
ntfy-cli messages publish alerts --message "Deploy complete"
ntfy-cli messages publish alerts --file report.pdf --filename report.pdf
ntfy-cli messages publish alerts "Read later" --delay 30m
ntfy-cli messages publish alerts "Hello" --table
```

Options:

| Option | Purpose |
|---|---|
| `--config`, `-c` | Use an upstream client configuration file |
| `--message`, `-m` | Supply message body instead of `BODY`; cannot be combined with `BODY` |
| `--title`, `-t` | Set notification title |
| `--priority`, `-p` | Set notification priority |
| `--tags`, `-T` | Set comma-separated tags |
| `--delay`, `--at`, `--in`, `-D` | Schedule delivery |
| `--click`, `-U` | Set click URL |
| `--icon`, `-i` | Set icon URL |
| `--actions`, `-A` | Set notification actions |
| `--attach`, `-a` | Attach a remote URL |
| `--markdown`, `--md` | Render body as Markdown |
| `--template`, `--tpl` | Use an upstream message template |
| `--filename`, `-n` | Set attachment filename |
| `--sequence-id`, `-S` | Set sequence ID |
| `--file`, `-f` | Publish a local file |
| `--email`, `-e` | Forward notification by email |
| `--user`, `-u` | Pass upstream username/password credentials |
| `--token`, `-k` | Pass upstream access token |
| `--wait-pid`, `--pid` | Publish after a process exits |
| `--wait-cmd`, `--cmd`, `--done` | Run a command, then publish its result |
| `--no-cache`, `-C` | Disable server-side message caching |
| `--no-firebase`, `-F` | Disable Firebase forwarding |
| `--quiet`, `-q` | Request quiet upstream behavior |
| `--table` | Render returned message as a table instead of JSON |

`--wait-cmd` treats the supplied body and remaining arguments as the command to run:

```bash
ntfy-cli messages publish alerts "make test" --wait-cmd
```

### `messages trigger`

Sends ntfy's topic-only default message and returns its message object as JSON:

```bash
ntfy-cli messages trigger alerts
```

### `messages poll`

Runs one upstream poll and returns cached events as a JSON array. `--table` renders selected rows as a table.

```bash
ntfy-cli messages poll TOPIC
ntfy-cli messages poll alerts --since 1h --scheduled --limit 25
ntfy-cli messages poll alerts --token tk_example --table
```

Options: `--config/-c`, `--since/-s`, `--scheduled/-S`, `--user/-u`, `--token/-k`, `--limit/-l`, and `--table/-t`.

### `messages subscribe`

Streams upstream NDJSON to stdout without buffering or normalization. Each line is one JSON event. The command runs until interrupted or until upstream exits.

```bash
ntfy-cli messages subscribe TOPIC
ntfy-cli messages subscribe alerts --since 10m --scheduled
```

Options: `--config/-c`, `--since/-s`, `--scheduled/-S`, `--user/-u`, and `--token/-k`.

### `messages subscribe-config`

Streams NDJSON for subscriptions defined in upstream client configuration:

```bash
ntfy-cli messages subscribe-config
ntfy-cli messages subscribe-config --config /path/to/client.yml
```

Option: `--config/-c`.

### `server serve`

Runs upstream server in foreground and forwards extra arguments unchanged:

```bash
ntfy-cli server serve --listen-http :8081
```

Requires a server-capable Linux ntfy binary.

### `server users`

```bash
ntfy-cli server users list --filter user:eq:alice --limit 25 --properties user,role --table
ntfy-cli server users get alice --table
ntfy-cli server users create alice --role admin
ntfy-cli server users delete alice --force
ntfy-cli server users password update alice --password-stdin < password.txt
ntfy-cli server users role update alice admin
```

| Command | Behavior |
|---|---|
| `users list` | Return users as JSON; supports `--filter/-f`, `--limit/-l`, `--properties/-p`, and `--table/-t` |
| `users get USERNAME` | Return every matching user row; supports `--table/-t` |
| `users create USERNAME` | Create user; optional `--role` |
| `users delete USERNAME` | Delete user; requires `--force/-F` |
| `users password update USERNAME` | Change password; `--password-stdin` reads it without placing it in arguments |
| `users role update USERNAME VALUE` | Change user role |

### `server access`

```bash
ntfy-cli server access list --filter user:eq:alice --limit 25 --properties user,topic,access --table
ntfy-cli server access get alice --table
ntfy-cli server access set alice alerts rw --force
ntfy-cli server access reset --username alice --topic alerts --force
```

| Command | Behavior |
|---|---|
| `access list` | Return access rules as JSON; supports `--filter/-f`, `--limit/-l`, `--properties/-p`, and `--table/-t` |
| `access get USERNAME` | Return access rows for a user; supports `--table/-t` |
| `access set USERNAME TOPIC PERMISSION` | Set rule; requires `--force/-F` |
| `access reset [USERNAME] [TOPIC]` | Reset matching rules; accepts `--username` and `--topic`, and requires `--force/-F` |

### `server tokens`

```bash
ntfy-cli server tokens list --username alice --filter user:eq:alice --limit 25 --properties token,user,expires,label --table
ntfy-cli server tokens get alice --table
ntfy-cli server tokens create alice --expires 24h --label phone --force
ntfy-cli server tokens delete alice tk_example --force
ntfy-cli server tokens generate
```

| Command | Behavior |
|---|---|
| `tokens list` | Return tokens as JSON; optional `--username`; supports `--filter/-f`, `--limit/-l`, `--properties/-p`, and `--table/-t` |
| `tokens get USERNAME` | Return every token row for user; supports `--table/-t` |
| `tokens create USERNAME` | Create token; optional `--expires` and `--label`; requires `--force/-F` |
| `tokens delete USERNAME TOKEN` | Delete token; requires `--force/-F` |
| `tokens generate` | Generate token using upstream ntfy |

Server list/get commands parse upstream tables into records. Mutating server commands and `tokens generate` forward finite upstream text. New token values may appear once on stdout, but are never written to wrapper activity logs.

### `upstream ARGS...`

Passes every argument directly to official executable and preserves upstream stdout, stderr, signals, and exit code. Use it for version-specific or newly added ntfy features without a dedicated wrapper command.

```bash
ntfy-cli upstream --help
ntfy-cli upstream publish alerts "upstream syntax"
ntfy-cli upstream subscribe alerts --poll
```

## Output Behavior

| Command type | stdout behavior |
|---|---|
| `auth status` | JSON object |
| `messages publish`, `messages trigger` | One JSON message object |
| `messages poll` | JSON array |
| `messages subscribe`, `messages subscribe-config` | Unbuffered NDJSON stream |
| Server list/get commands | JSON array by default; table with `--table/-t` |
| Server mutations and token generation | Finite upstream text |
| `upstream` and `server serve` | Exact upstream stream behavior |

Messages and errors use stderr. Structured data uses stdout. `--properties` accepts comma-separated field names. `--filter` uses `field:operator:value` expressions, such as `user:eq:alice`.

## Configuration

Wrapper settings live at `~/.local/share/cli-tools/ntfy-cli/.env`:

```dotenv
ACTIVE=true
CLI_COMMAND=ntfy
# CLI_PATH=/opt/homebrew/bin/ntfy
```

`CLI_COMMAND` selects upstream executable name and defaults to `ntfy`. `CLI_PATH` overrides it with a specific executable path. Do not store reusable credentials here; use upstream ntfy configuration.

Message commands accept `--config/-c` to select an upstream client configuration file. Server configuration and auth-database discovery follow upstream ntfy rules; pass version-specific server flags through `server serve` or `upstream`.

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Handled wrapper, upstream command, capability, or mutation-confirmation error |
| `2` | Command usage, startup, or configuration error |
| `130` | Interrupted with Ctrl+C |
| Other | `upstream`, streaming subscriptions, and foreground server execution preserve applicable upstream exit codes |

## License

MIT
