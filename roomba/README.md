# Roomba CLI

## DESCRIPTION

The `roomba` CLI provides a command-line interface for Roomba API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
cd roomba
pip install -e .
```

After installation, the `roomba` command will be available in your terminal.

## Quick Start

```bash
# Discover and configure robots on your network
roomba auth login

# List configured robots
roomba robots list

# Get robot status
roomba status "Living Room"

# Start cleaning
roomba control start "Living Room"

# Send robot to dock
roomba control dock "Living Room"
```

## Commands

### Authentication

```bash
# Auto-discover robots on the network and save credentials
roomba auth login

# Discover a specific IP
roomba auth login --ip 192.168.1.50

# Manually configure a robot
roomba auth login --blid ABC123 --password XYZ789 --ip 192.168.1.50

# Overwrite existing credentials
roomba auth login --force

# Check authentication status
roomba auth status
roomba auth status

# Remove all credentials
roomba auth logout

# Remove specific robot
roomba auth logout "Living Room"
```

### Robot Management

```bash
# List configured robots (JSON output)
roomba robots list

# List robots with table format
roomba robots list

# Discover robots on network (not just configured)
roomba robots list --discover

# Select specific properties
roomba robots list --properties "name,ip"

# Get details for a specific robot
roomba robots get "Living Room"
roomba robots get "Living Room"
```

### Robot Control

```bash
# Start cleaning
roomba control start "Living Room"

# Stop cleaning
roomba control stop "Living Room"

# Pause cleaning
roomba control pause "Living Room"

# Resume after pause
roomba control resume "Living Room"

# Send to dock
roomba control dock "Living Room"

# Play sound to locate robot
roomba control find "Living Room"

# Empty bin (Clean Base models only)
roomba control evac "Living Room"

# Get live status
roomba control status "Living Room"
roomba control status "Living Room"
roomba control status "Living Room" --timeout 15
```

### Profiles

```bash
# List all profiles
roomba auth profiles list

# Create a new profile
roomba auth profiles create work

# Select active profile
roomba auth profiles select work

# Delete a profile
roomba auth profiles delete work
```

### Status (Top-Level Shortcut)

```bash
# Quick status check (shortcut for 'control status')
roomba status "Living Room"
roomba status "Living Room"
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

### JSON Output Example

```bash
roomba robots list
```
```json
[
  {
    "ip": "192.168.1.50",
    "blid": "ABC123...",
    "name": "Living Room",
    "mac": "AA:BB:CC:DD:EE:FF",
    "password": "***"
  }
]
```

### Table Output Example

```bash
roomba robots list
```
```
Name          IP              BLID
-----------------------------------------
Living Room   192.168.1.50    ABC123...
```

## Options Reference

### Global Options

| Option | Short | Description |
|--------|-------|-------------|
| `--version` | `-v` | Show version and exit |
| `--help` | | Show help message |

### List Command Options

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results (default: 100) |
| `--filter` | `-f` | Filter results (field:op:value) |
| `--properties` | `-p` | Comma-separated fields to display |
| `--discover` | `-d` | Discover robots on network |

### Control Command Options

| Option | Short | Description |
|--------|-------|-------------|
| `--timeout` | | Connection timeout in seconds (default: 10) |

### Auth Login Options

| Option | Short | Description |
|--------|-------|-------------|
| `--ip` | `-i` | Specific IP address to discover |
| `--name` | `-n` | Custom name for the robot |
| `--blid` | `-b` | Robot BLID (login) |
| `--password` | `-p` | Robot password |
| `--force` | `-F` | Overwrite existing credentials |

## Configuration

Robot credentials are stored in `~/.config/roomba/robots.json`:

```json
{
  "robots": {
    "Living Room": {
      "ip": "192.168.1.50",
      "blid": "ABC123...",
      "password": "secret..."
    }
  }
}
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Get Robot Status as JSON

```bash
roomba status "Living Room" | jq '.battery_percent'
```

### Start All Configured Robots

```bash
roomba robots list | jq -r '.[].name' | while read name; do
  roomba control start "$name"
done
```

### Export Robot List

```bash
roomba robots list > my_robots.json
```

## Troubleshooting

### Robot Not Discovered

1. Ensure your Roomba is powered on and connected to WiFi
2. Make sure you're on the same network as the Roomba
3. Try specifying the IP directly: `roomba auth login --ip 192.168.1.50`
4. For password retrieval, press and hold the HOME button for 2 seconds

### Connection Timeout

Increase the timeout: `roomba status "Living Room" --timeout 20`

### Only One Connection Allowed

Roomba only allows one connection at a time. Close the iRobot app or other clients before using this CLI.

## Models

This CLI uses Pydantic models for type-safe data handling.

### Available Models

| Model | Description |
|-------|-------------|
| `RobotInfo` | Basic robot info (ip, blid, name) |
| `RobotStatus` | Live status (battery, phase, bin) |
| `RobotDetail` | Full robot details |
| `CommandResult` | Command execution result |
| `AuthStatus` | Authentication status |

### Cleaning Phases

| Phase | Description |
|-------|-------------|
| `charge` | Charging on dock |
| `run` | Cleaning |
| `stop` | Stopped |
| `pause` | Paused |
| `stuck` | Stuck |
| `hmPostMsn` | Returning to dock after mission |
| `hmMidMsn` | Returning to dock mid-mission (recharge) |
| `hmUsrDock` | Returning to dock (user requested) |
| `evac` | Emptying bin |

## Requirements

- Python 3.10+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - pydantic
  - roombapy

## License

MIT

## Cache

```bash
roomba cache status
roomba cache clear
```
