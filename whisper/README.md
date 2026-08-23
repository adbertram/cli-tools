# Whisper CLI

## DESCRIPTION

A standardized command-line wrapper for the whisper-cpp `whisper-cli` binary that does local, offline speech-to-text and emits JSON transcripts with timestamped segments and optional word-level timestamps. Its output shape mirrors the openai-whisper CLI, so the two are drop-in swappable. Use it when you need offline transcription exposed through the cli-tools JSON and table conventions for agents, automation, or terminal workflows.

## Prerequisites

This CLI wraps the whisper.cpp `whisper-cli` binary and uses `ffmpeg` to
normalize input audio. Both must be available:

```bash
brew install whisper-cpp   # provides whisper-cli
brew install ffmpeg        # provides ffmpeg/ffprobe
```

It also needs a local ggml model file (e.g. `ggml-small.en.bin`). Place it at the
default path or point `WHISPER_CPP_MODEL` / `--model` at an existing file:

```
~/.local/share/cli-tools/whisper/models/ggml-small.en.bin
```

## Installation

```bash
cd <cli-tools-root>/whisper
uv tool install -e . --force --refresh
```

After installation, the `whisper` command is available in your terminal.

## Quick Start

```bash
# Transcribe an audio/video file (JSON on stdout)
whisper transcripts create audio.wav

# Word-level timestamps
whisper transcripts create audio.wav --word-timestamps

# Table view of segments
whisper transcripts create audio.wav --table

# List local ggml models
whisper transcripts models
```

## How It Works

This CLI is a wrapper around the whisper.cpp `whisper-cli` binary:

- whisper.cpp is a local tool; there is no authentication.
- `transcripts create` normalizes the input to 16 kHz mono WAV with `ffmpeg`
  (whisper.cpp requires this), runs `whisper-cli -m <model> -f <wav> -oj`, and
  parses the resulting JSON into a uniform transcript shape.
- Timestamps in the parsed JSON are milliseconds; they are converted to seconds
  in the output.
- The binary and model are resolved fail-fast: a missing binary or missing model
  raises a clear error rather than falling back.

## Commands

### Transcripts

```bash
# Transcribe (JSON, default English)
whisper transcripts create audio.wav

# Choose a language
whisper transcripts create audio.wav --language es

# Word-level timestamps (adds a "words" array)
whisper transcripts create audio.wav --word-timestamps

# Use a specific ggml model file
whisper transcripts create audio.wav --model /path/to/ggml-small.en.bin

# Bias vocabulary/spellings with an initial prompt
whisper transcripts create audio.wav --prompt "worktree, subagent, Codex"

# Save the JSON transcript to a directory and show a table
whisper transcripts create audio.wav --output-dir ./transcripts/ --table

# Increase the timeout (seconds) for long files
whisper transcripts create long-recording.mp4 --timeout 1800
```

`transcripts create` options:

| Option | Alias | Default | Description |
|--------|-------|---------|-------------|
| `--language` | `-L` | `en` | Language code (e.g., en, es, fr, de) |
| `--word-timestamps` | `-w` | off | Emit word-level timestamps (adds `words`) |
| `--model` | `-m` | `WHISPER_CPP_MODEL` or small.en | Path to a ggml model file |
| `--output-dir` | `-o` | — | Directory to save the JSON transcript |
| `--prompt` | `-P` | `WHISPER_CPP_PROMPT` or none | Initial prompt to bias vocabulary/spellings |
| `--table` | `-t` | off | Display segments as a table |
| `--timeout` | | `600` | Transcription timeout in seconds |

```bash
# List local ggml models found in the models directory
whisper transcripts models

# Table view
whisper transcripts models --table

# Restrict output fields
whisper transcripts models --properties "name,size_mb"
```

## Output Formats

- JSON is the default output format (data on stdout).
- Add `--table` / `-t` for human-readable table output.
- Informational messages go to stderr, so `whisper ... | jq` stays clean.

`transcripts create` JSON shape (uniform with `openai-whisper`):

```json
{
  "text": "full joined transcript",
  "language": "en",
  "segments": [
    {"start": 0.0, "end": 4.0, "text": "..."}
  ],
  "words": [
    {"start": 0.0, "end": 0.24, "text": "..."}
  ]
}
```

The `words` array is present only when `--word-timestamps` is passed.

## Configuration

whisper.cpp is local and needs no credentials. Non-authentication configuration
lives in `~/.local/share/cli-tools/whisper/.env` (managed by the tool). Do not
put reusable credentials in any `.env` file.

Root config variables (all optional — sensible defaults apply):

```bash
# Path to the ggml model file
# Default: ~/.local/share/cli-tools/whisper/models/ggml-small.en.bin
WHISPER_CPP_MODEL=~/.local/share/cli-tools/whisper/models/ggml-small.en.bin

# Underlying whisper.cpp command name (default: whisper-cli)
WHISPER_CLI_COMMAND=whisper-cli

# Optional: absolute path to the whisper.cpp binary (wins over the command name)
WHISPER_CLI_PATH=/opt/homebrew/bin/whisper-cli

# Optional: default initial prompt to bias vocabulary/spellings (default: none)
WHISPER_CPP_PROMPT=worktree, subagent, Codex
```

Resolution order:

- Model: `--model` > `WHISPER_CPP_MODEL` > default `ggml-small.en.bin`
- Binary: `WHISPER_CLI_PATH` > `WHISPER_CLI_COMMAND` > default `whisper-cli`
- Prompt: `--prompt` > `WHISPER_CPP_PROMPT` > none (no prompt passed)

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error (e.g., missing file, missing model, transcription failure) |
| 2 | Client/configuration error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Transcribe and extract just the text with jq

```bash
whisper transcripts create audio.wav | jq -r '.text'
```

### Get word-level timestamps for alignment

```bash
whisper transcripts create audio.wav --word-timestamps | jq '.words'
```

### Save a transcript to a file

```bash
whisper transcripts create audio.wav > transcript.json
```

## Output Contract

`transcripts create` returns one transcript object:

| Field | Description |
|-------|-------------|
| `text` | Full transcript, joined from the segment texts |
| `language` | Language code used for transcription |
| `segments` | List of `{start, end, text}` with times in seconds |
| `words` | Same shape, present only with `--word-timestamps` |

`transcripts models` returns a list of local model records:

| Field | Description |
|-------|-------------|
| `name` | Model file name (e.g., `ggml-small.en.bin`) |
| `path` | Absolute path to the model file |
| `size_mb` | File size in megabytes |

## Requirements

- Python 3.11+
- `whisper-cli` (whisper.cpp) installed and available in PATH
- `ffmpeg` installed and available in PATH
- A local ggml model file
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - cli-tools-shared

## License

MIT
