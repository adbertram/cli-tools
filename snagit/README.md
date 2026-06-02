# Snagit CLI

A command-line interface for managing Snagit capture files (.snagx format).

## Installation

```bash
cd snagit
pip install -e .
```

After installation, the `snagit` command will be available in your terminal.

## Quick Start

```bash
# List all Snagit capture files
snagit capture list

# View a capture file
snagit capture view 2025-12-23_10-24-24.snagx

# Export the main PNG image from a capture file
snagit capture export 2025-12-23_10-24-24.snagx --output ./my-exports/
```

## Commands

### Captures

```bash
# List all .snagx capture files
snagit capture list
snagit capture list

# View a capture file (extracts to temp directory and outputs image path)
snagit capture view capture.snagx
snagit capture view 2025-12-23_10-24-24.snagx

# Export the main PNG image from a capture file
snagit capture export capture.snagx
snagit capture export capture.snagx --output ./image.png
snagit capture export capture.snagx --output ./exports/
snagit capture export capture.snagx

# Specify custom Snagit captures folder
snagit capture list --path ~/Pictures/Snagit/Archive
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

### JSON Output Example

```bash
snagit capture list
```

### Table Output Example

```bash
snagit capture list
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--output` | `-o` | Output directory for export command |
| `--path` | `-p` | Path to Snagit captures folder |
| `--version` | `-v` | Show version and exit |

## Configuration

By default, the CLI looks for `.snagx` files in:
```
~/Pictures/Snagit/Autosaved Captures.localized/
```

You can specify a different location using the `--path` option:
```bash
snagit capture list --path ~/Pictures/Snagit/Archive
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Captures and Filter with jq

```bash
snagit capture list | jq '.captures[].filename'
```

### Export Capture Information to JSON File

```bash
snagit capture list > captures.json
```

### Export Multiple Captures

```bash
# Export recent captures to a specific directory
for file in $(snagit capture list | jq -r '.captures[0:5][].filename'); do
  snagit capture export "$file" --output ./exports/
done
```

### Get Exported Image Path

```bash
# Export and get the output path
output_path=$(snagit capture export capture.snagx | jq -r '.output_path')
echo "Exported to: $output_path"
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests

## License

MIT
