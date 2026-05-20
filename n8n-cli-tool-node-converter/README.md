# n8n CLI Tool Node Converter

Convert standardized Python CLI tools into n8n community node packages.

## Installation

```bash
cd n8n-cli-tool-node-converter
pip install -e .
```

## Quick Start

```bash
# Check configuration
n8n-cli-tool-node-converter auth status

# List available CLI tools
n8n-cli-tool-node-converter tools list

# Inspect a CLI tool
n8n-cli-tool-node-converter tools get brickowl

# Generate an n8n node package
n8n-cli-tool-node-converter nodes generate brickowl
```

## Commands

### Authentication

```bash
# Configure directories
n8n-cli-tool-node-converter auth login --tools-dir ~/cli-tools --output-dir ~/n8n-nodes

# Check configuration status
n8n-cli-tool-node-converter auth status

# Clear configuration
n8n-cli-tool-node-converter auth logout
```

### Tools

```bash
# List available CLI tools
n8n-cli-tool-node-converter tools list
n8n-cli-tool-node-converter tools list --table

# Inspect a CLI tool's metadata
n8n-cli-tool-node-converter tools get brickowl
n8n-cli-tool-node-converter tools get shippo --table
```

### Nodes

```bash
# Generate an n8n node package
n8n-cli-tool-node-converter nodes generate brickowl
n8n-cli-tool-node-converter nodes generate shippo --force

# List generated packages
n8n-cli-tool-node-converter nodes list
n8n-cli-tool-node-converter nodes list --table

# Get details for a generated package
n8n-cli-tool-node-converter nodes get brickowl
```

## Configuration

Settings are stored in `.env`:

```bash
# Path to CLI tools directory (default: discovered from this clone)
N8N_CONVERTER_CLI_TOOLS_DIR=

# Path for generated n8n node packages (default: profile data dir / n8n-nodes)
N8N_CONVERTER_OUTPUT_DIR=
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Configuration error |
| 130 | User interrupted (Ctrl+C) |

## Requirements

- Python 3.9+
- Dependencies: typer, python-dotenv, pydantic

## License

MIT
