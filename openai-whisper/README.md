# Whisper CLI

## DESCRIPTION

The `whisper` CLI wraps whisper with standardized cli-tools behavior.

Use it when you need the underlying command exposed through cli-tools JSON/table conventions for agents, automation, or terminal workflows.

## Prerequisites

This CLI wraps the `whisper` command-line tool. You must install it first:

```bash
pipx install openai-whisper
```

## Installation

```bash
cd whisper
pip install -e .
```

After installation, the `whisper` command will be available in your terminal.

## Quick Start

```bash
# Check CLI availability (no authentication required)
whisper auth status

# Transcribe a video/audio file
whisper transcripts create video.mp4

# Transcribe with specific model
whisper transcripts create video.mp4 --model base

# View available models
whisper transcripts models --table
```

## How It Works

This CLI is a **wrapper** around the `whisper` command-line tool:

- **Auth commands** return status (Whisper runs locally, no auth needed)
- **Transcripts commands** call `whisper`, parse the JSON output, and present it in standard format
- **Configuration** is minimal - Whisper runs entirely locally

## Commands

### Authentication

Whisper runs locally and doesn't require authentication. These commands are provided for CLI standard compliance.

```bash
# Check status (always returns authenticated: true)
whisper auth status

# Login (no-op, returns success)
whisper auth login

# Force re-login (no-op, returns success)
whisper auth login --force

# Logout (no-op, returns success)
whisper auth logout
```

### Transcripts

```bash
# Create a transcript from video/audio file
whisper transcripts create video.mp4
whisper transcripts create video.mp4 --model base
whisper transcripts create audio.wav --language es
whisper transcripts create video.mp4 --word-timestamps
whisper transcripts create video.mp4 -o ./transcripts/ --table

# List existing transcript JSON files in a directory
whisper transcripts list
whisper transcripts list ./transcripts/
whisper transcripts list --table
whisper transcripts list --filter "language:eq:en"
whisper transcripts list --limit 10
whisper transcripts list --properties "file,language"

# Get details of an existing transcript file
whisper transcripts get video.json
whisper transcripts get video.json --table
whisper transcripts get video.json --properties "text,language"

# List available Whisper models
whisper transcripts models
whisper transcripts models --table
```

### Transcripts Create Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--model` | `-m` | Whisper model to use | turbo |
| `--language` | `-L` | Language code (en, es, fr, etc.) | en |
| `--word-timestamps` | `-w` | Enable word-level timestamps | false |
| `--output-dir` | `-o` | Directory to save output files | same as input |
| `--table` | `-t` | Display segments as table | false |
| `--timeout` | | Transcription timeout in seconds | 600 |

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping
- **Table** (`--table`/`-t`): Human-readable table format

## Configuration

The wrapper stores minimal configuration in `.env`:

```bash
# Underlying CLI command (defaults to whisper)
WHISPER_CLI_COMMAND=whisper

# Optional: Full path to CLI executable
# WHISPER_CLI_PATH=
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/CLI not available error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Transcribe and Extract Text with jq

```bash
whisper transcripts create video.mp4 | jq '.text'
```

### Get Segment Times

```bash
whisper transcripts create video.mp4 | jq '.segments[] | {start, end, text}'
```

### Export to JSON File

```bash
whisper transcripts create video.mp4 > transcript.json
```

### Display as Table

```bash
whisper transcripts create video.mp4 --table
```

## Models

This CLI uses Pydantic models for type-safe data handling. All commands return strongly-typed models.

### Available Models

| Model | Description | Key Fields |
|-------|-------------|------------|
| `Transcript` | Full transcription result | `text`, `segments`, `language` |
| `TranscriptSegment` | Individual segment with timestamps | `id`, `start`, `end`, `text` |
| `TranscriptSummary` | Summary for list commands | `source_file`, `language`, `segment_count` |
| `WhisperModel` | Enum of available models | `tiny`, `base`, `small`, `medium`, `large`, `turbo` |

### Model Architecture

```
models/
├── __init__.py      # Exports all models
├── base.py          # CLIModel base class
└── transcript.py    # Transcript, TranscriptSegment models
```

## Requirements

- Python 3.9+
- `whisper` CLI installed and in PATH (via `pipx install openai-whisper`)
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - pydantic

## License

MIT
