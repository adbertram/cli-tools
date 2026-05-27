# Cliclick CLI

A Python wrapper for [cliclick](https://github.com/BlueM/cliclick), the macOS command-line tool for emulating mouse and keyboard events.

## Prerequisites

1. Install cliclick:
```bash
brew install cliclick
```

2. Grant Accessibility permissions:
   - Open System Settings > Privacy & Security > Accessibility
   - Add your terminal application (Terminal, iTerm2, etc.)

## Installation

```bash
cd cliclick
pip install -e .
```

## Quick Start

```bash
# Get current mouse position
cliclick mouse position

# Click at coordinates
cliclick mouse click 100 200

# Type text
cliclick keyboard type "Hello World"
```

## Commands

### Mouse Commands

Control mouse position and clicks.

```bash
# Get current position
cliclick mouse position
cliclick mouse position --table

# Click at coordinates
cliclick mouse click 100 200
cliclick mouse click 100 200 --test    # Test mode (no actual click)
cliclick mouse click 100 200 --verbose  # Verbose output

# Other click types
cliclick mouse double-click 100 200
cliclick mouse right-click 100 200
cliclick mouse triple-click 100 200

# Move mouse
cliclick mouse move 500 300
cliclick mouse move 500 300 --no-restore  # Don't restore original position

# Drag operations
cliclick mouse drag-start 100 100
cliclick mouse drag-move 200 200
cliclick mouse drag-end 300 300

# Get screen color at position
cliclick mouse color-at 100 200
```

### Keyboard Commands

Control keyboard input.

```bash
# Type text
cliclick keyboard type "Hello World"
cliclick keyboard type "Test" --test

# Press keys
cliclick keyboard press return
cliclick keyboard press tab
cliclick keyboard press f1

# Modifier keys (for key combinations)
cliclick keyboard key-down cmd,shift
cliclick keyboard key-up cmd,shift
```

### Script Management

Create and manage automation scripts.

```bash
# List scripts
cliclick scripts list
cliclick scripts list --table
cliclick scripts list --filter "name:test"
cliclick scripts list --limit 10

# Get script details
cliclick scripts get my-script
cliclick scripts get my-script --content

# Create script (from stdin or --content)
echo "c:100,200
w:500
t:hello" | cliclick scripts create my-script --description "Click and type"

cliclick scripts create quick-click --content "c:100,200"

# Run script
cliclick scripts run my-script
cliclick scripts run my-script --test
cliclick scripts run my-script --verbose

# Run with template variables
# Script: c:{{x}},{{y}}\nw:{{delay}}\nt:{{message}}
cliclick scripts run click-template --var x=100 --var y=200 --var delay=500 --var message="Hi"

# Run commands from stdin
echo "c:100,200
w:500" | cliclick scripts run-stdin

# Delete script
cliclick scripts delete my-script
cliclick scripts delete my-script --yes  # Skip confirmation
```

### Raw Command Execution

Execute native cliclick command syntax.

```bash
# Execute raw commands
cliclick exec run "c:100,200 w:500 t:hello"
cliclick exec run "m:500,300 c:. w:1000" --test

# Wait
cliclick exec wait 1000
```

## Command Options

### Global Options

| Option | Short | Description |
|--------|-------|-------------|
| `--verbose` | `-V` | Enable verbose output from cliclick |
| `--test` | `-T` | Test mode (don't execute actions) |
| `--no-restore` | | Don't restore mouse position after action |
| `--table` | `-t` | Display output as table |

### Script List Options

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display as table |
| `--limit` | `-l` | Maximum number of scripts |
| `--filter` | `-f` | Filter scripts (e.g., `name:test`) |
| `--properties` | `-p` | Comma-separated fields to include |

## Output Formats

All commands output JSON by default for easy piping:

```bash
# Get position and extract x coordinate
cliclick mouse position | jq '.x'

# List scripts and get names
cliclick scripts list | jq '.[].name'
```

Use `--table` for human-readable output:

```bash
cliclick scripts list --table
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/CLI not available/permission error |
| 130 | User interrupted (Ctrl+C) |

## Script Format

Scripts are plain text files with cliclick commands, one per line:

```
# Comment line
c:100,200       # Click at 100,200
w:500           # Wait 500ms
t:Hello World   # Type text
kp:return       # Press return key
```

### Template Variables

Use `{{variable}}` placeholders in scripts:

```
c:{{x}},{{y}}
w:{{delay}}
t:{{message}}
```

Run with `--var` to substitute:

```bash
cliclick scripts run template --var x=100 --var y=200 --var delay=500 --var message="Hi"
```

## Models

This CLI uses Pydantic models for type-safe data handling:

| Model | Description | Fields |
|-------|-------------|--------|
| `Position` | Mouse coordinates | `x`, `y` |
| `Color` | RGB color value | `r`, `g`, `b` |
| `Script` | Automation script | `name`, `path`, `variables`, `command_count` |
| `ExecutionResult` | Command result | `success`, `output`, `duration_ms` |

## Requirements

- macOS (cliclick is macOS-only)
- Python 3.12+
- cliclick CLI installed (`brew install cliclick`)
- Accessibility permissions granted

## License

MIT
