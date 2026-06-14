# Harmony CLI

## DESCRIPTION

The `harmony` CLI lets you manage Logitech Harmony hubs, activities, devices, and commands.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
cd <cli-tools-root>/harmony
uv tool install -e . --force --refresh
```

## Quick Start

```bash
# Discover hubs
harmony hubs list --table

# Low-level TCP probe when Bonjour/mDNS discovery misses a hub
harmony hubs probe --cidr 192.168.86.0/24 --table

# List activities on one hub
harmony activities list --hub 192.168.1.50 --table

# Start an activity
harmony activities start "Watch TV" --hub 192.168.1.50

# List device commands
harmony commands list "Living Room TV" --hub 192.168.1.50 --filter "group:Power"

# Send a device command
harmony commands send "Living Room TV" VolumeUp --hub 192.168.1.50
```

## Commands

### Hubs

```bash
# Discover hubs
harmony hubs list --timeout 3

# Filter discovered hubs
harmony hubs list --filter "name:ilike:%living%" --properties "id,name,ip"

# Get hub status
harmony hubs get 192.168.1.50 --table

# Search discovered hubs
harmony hubs search living --table

# Probe a subnet for Harmony-compatible TCP ports
harmony hubs probe --cidr 192.168.86.0/24 --table

# Probe with no Harmony API verification
harmony hubs probe --cidr 192.168.86.0/24 --no-verify

# Sync a hub
harmony hubs sync --hub 192.168.1.50
```

### Activities

```bash
# List activities
harmony activities list --hub 192.168.1.50 --limit 25

# Get one activity
harmony activities get "Watch TV" --hub 192.168.1.50

# Show current activity
harmony activities current --hub 192.168.1.50

# Start an activity
harmony activities start "Watch TV" --hub 192.168.1.50

# Power off the current activity
harmony activities power-off --hub 192.168.1.50

# Search activities
harmony activities search watch --hub 192.168.1.50 --table
```

### Devices

```bash
# List devices
harmony devices list --hub 192.168.1.50 --table

# Filter devices
harmony devices list --hub 192.168.1.50 --filter "manufacturer:ilike:%sony%"

# Get one device
harmony devices get "Living Room TV" --hub 192.168.1.50

# Search devices
harmony devices search receiver --hub 192.168.1.50
```

### Commands

```bash
# List commands for a device
harmony commands list "Living Room TV" --hub 192.168.1.50

# Get one command
harmony commands get "Living Room TV" VolumeUp --hub 192.168.1.50

# Send one command
harmony commands send "Living Room TV" VolumeUp --hub 192.168.1.50

# Send a repeated command
harmony commands send "Living Room TV" VolumeUp --hub 192.168.1.50 --repeat 3 --delay 0.2

# Change channel
harmony commands channel 802 --hub 192.168.1.50
```

### Configuration

```bash
# Get the full Harmony hub configuration
harmony config get --hub 192.168.1.50

# List hub configurations
harmony config list --hub 192.168.1.50

# Clear cached read responses
harmony cache clear
```

## Output Formats

JSON is the default output format. Add `--table` / `-t` for table output.

```bash
harmony devices list --hub 192.168.1.50 --properties "id,name,manufacturer"
```

```json
[
  {
    "id": "12345678",
    "name": "Living Room TV",
    "manufacturer": "Sony"
  }
]
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--hub` | `-H` | Hub IP, hostname, or discovered hub name |
| `--protocol` |  | Protocol: `WEBSOCKETS` or `XMPP` |
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results for list/search commands |
| `--filter` | `-f` | Filter list/search results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--cidr` |  | IPv4 CIDR for `hubs probe`; defaults to the primary local `/24` |
| `--port` |  | TCP port for `hubs probe`; repeat to scan multiple ports |
| `--version` | `-v` | Show version and exit |
| `--no-cache` |  | Bypass cached read responses for this execution |

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/harmony/.env`.
Harmony uses local network access and does not require reusable credentials.

```bash
# Optional default hub IP, hostname, or discovered name
HARMONY_HUB=192.168.1.50

# Optional protocol. Use XMPP only when enabled on the hub.
HARMONY_PROTOCOL=WEBSOCKETS

# Optional Bonjour discovery timeout in seconds
HARMONY_DISCOVERY_TIMEOUT=3
```

## Output Contract

Commands return plain JSON records. List commands return arrays. Get/action commands return one object.

Hub records include `id`, `name`, `ip`, `protocol`, and Bonjour metadata when discovered.
Activity records include all hub-provided activity fields plus `id`, `name`, `label`, and `status`.
Device records include all hub-provided device fields plus `id`, `name`, `label`, `manufacturer`, `model`, `type`, and `command_count`.
Command records include `id`, `name`, `command`, `device_id`, `device_name`, `group`, and parsed `action`.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/config error |
| 130 | User interrupted |

## Requirements

- Python 3.11+
- Local network access to a Logitech Harmony hub
- Dependencies installed automatically:
  - aioharmony
  - typer
  - python-dotenv
  - zeroconf
  - cli-tools-shared

## License

MIT
