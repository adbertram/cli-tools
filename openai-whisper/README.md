# OpenAI Whisper CLI

## DESCRIPTION

The `openai-whisper` CLI wraps OpenAI Whisper with standardized cli-tools behavior.

Use it when you need the underlying command exposed through cli-tools JSON/table conventions for agents, automation, or terminal workflows.

## Prerequisites

This CLI wraps the OpenAI-Whisper `whisper` command-line tool. You must install it first:

```bash
pipx install openai-whisper
```

## Installation

```bash
cd openai-whisper
uv tool install -e . --force --refresh
```

After installation, the `openai-whisper` command will be available in your terminal.

## Quick Start

```bash
# Check CLI availability (no authentication required)
openai-whisper auth status

# Transcribe a video/audio file
openai-whisper transcripts create video.mp4

# Transcribe with specific model
openai-whisper transcripts create video.mp4 --model base

# View available models
openai-whisper transcripts models --table
```

## How It Works

This CLI is a **wrapper** around the OpenAI-Whisper `whisper` command-line tool:

- **Auth commands** return status (Whisper runs locally, no auth needed)
- **Transcripts commands** call the underlying `whisper` binary, parse the JSON output, and present it in standard format
- **Configuration** is minimal - Whisper runs entirely locally

## Commands

### Authentication

Whisper runs locally and doesn't require authentication. These commands are provided for CLI standard compliance.

```bash
# Check status (always returns authenticated: true)
openai-whisper auth status

# Login (no-op, returns success)
openai-whisper auth login

# Force re-login (no-op, returns success)
openai-whisper auth login --force

# Logout (no-op, returns success)
openai-whisper auth logout
```

### Transcripts

```bash
# Create a transcript from video/audio file
openai-whisper transcripts create video.mp4
openai-whisper transcripts create video.mp4 --model base
openai-whisper transcripts create audio.wav --language es
openai-whisper transcripts create video.mp4 --word-timestamps
openai-whisper transcripts create video.mp4 -o ./transcripts/ --table
openai-whisper transcripts create audio.mp3 --initial-prompt "worktree, subagent, Codex"
openai-whisper transcripts create audio.mp3 --temperature 0

# List existing transcript JSON files in a directory
openai-whisper transcripts list
openai-whisper transcripts list ./transcripts/
openai-whisper transcripts list --table
openai-whisper transcripts list --filter "language:eq:en"
openai-whisper transcripts list --limit 10
openai-whisper transcripts list --properties "file,language"

# Get details of an existing transcript file
openai-whisper transcripts get video.json
openai-whisper transcripts get video.json --table
openai-whisper transcripts get video.json --properties "text,language"

# List available Whisper models
openai-whisper transcripts models
openai-whisper transcripts models --table
```

### Transcripts Create Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--model` | `-m` | Whisper model to use | `OPENAI_WHISPER_MODEL` or turbo |
| `--language` | `-L` | Language code (en, es, fr, etc.) | en |
| `--word-timestamps` | `-w` | Enable word-level timestamps | false |
| `--output-dir` | `-o` | Directory to save output files | same as input |
| `--table` | `-t` | Display segments as table | false |
| `--timeout` | | Transcription timeout in seconds | 600 |
| `--initial-prompt` | | Vocabulary-biasing prompt (passed to Whisper as `--initial_prompt`); biases spelling toward the supplied terms. Omitted entirely when empty. | `OPENAI_WHISPER_INITIAL_PROMPT` or unset |
| `--temperature` | | Sampling temperature (passed to Whisper as `--temperature`); lower is more deterministic | engine default |

### Vocabulary biasing with `--initial-prompt`

Whisper accepts a short free-text prompt that biases how it spells domain terms,
product names, and jargon. Pass the terms you expect in the audio:

```bash
openai-whisper transcripts create lesson.mp3 --initial-prompt "worktree, subagent, Codex, Pluralsight"
```

Resolution order for the prompt: the explicit `--initial-prompt` flag wins; if it
is omitted, the `OPENAI_WHISPER_INITIAL_PROMPT` environment default is used; if the
resolved value is empty or unset, no `--initial_prompt` is passed to the engine
(current behavior). The same explicit-flag-then-env-default pattern applies to
`--model` via `OPENAI_WHISPER_MODEL`.

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

# Optional: default model when --model is not passed (defaults to turbo)
# OPENAI_WHISPER_MODEL=turbo

# Optional: default vocabulary-biasing prompt when --initial-prompt is not passed.
# Unset/empty means no prompt is sent to the engine.
# OPENAI_WHISPER_INITIAL_PROMPT=
```

These are non-secret runtime settings and live in the tool's profile `.env`
under `~/.local/share/cli-tools/openai-whisper/.env`, not in the source tree.

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
openai-whisper transcripts create video.mp4 | jq '.text'
```

### Get Segment Times

```bash
openai-whisper transcripts create video.mp4 | jq '.segments[] | {start, end, text}'
```

### Export to JSON File

```bash
openai-whisper transcripts create video.mp4 > transcript.json
```

### Display as Table

```bash
openai-whisper transcripts create video.mp4 --table
```

## Models

This CLI uses Pydantic models for type-safe data handling. All commands return strongly-typed models.

### Available Models

| Model | Description | Key Fields |
|-------|-------------|------------|
| `Transcript` | Full transcription result | `text`, `segments`, `language` |
| `TranscriptSegment` | Individual segment with timestamps | `id`, `start`, `end`, `text` |
| `TranscriptSummary` | Summary for list commands | `source_file`, `language`, `segment_count` |
| `WhisperModel` | Enum of available models | `tiny[.en]`, `base[.en]`, `small[.en]`, `medium[.en]`, `large`, `large-v1/v2/v3`, `large-v3-turbo`, `turbo` |

### Model Architecture

```
models/
├── __init__.py      # Exports all models
├── base.py          # CLIModel base class
└── transcript.py    # Transcript, TranscriptSegment models
```

## Requirements

- Python 3.9+
- OpenAI-Whisper `whisper` CLI installed and in PATH (via `pipx install openai-whisper`)
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - pydantic

## License

MIT
