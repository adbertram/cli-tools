---
name: whisper-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute whisper.cpp transcription operations using the `whisper` CLI tool.
  CLI interface for whisper.cpp (whisper-cli) local, offline speech-to-text; output mirrors the openai-whisper CLI.
  Triggers: whisper, whisper cli, whisper.cpp, whisper-cli, transcribe audio, local transcription, speech to text, ggml transcript
---

<objective>
Execute whisper.cpp transcription operations using the `whisper` CLI. All whisper.cpp interactions should use this CLI. It runs entirely offline against a local ggml model and emits transcripts whose shape matches the `openai-whisper` CLI, so the two are drop-in swappable.
</objective>

<quick_start>
The `whisper` CLI follows this pattern:
```bash
whisper <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Transcribe a file (JSON) | `whisper transcripts create audio.wav` |
| Word-level timestamps | `whisper transcripts create audio.wav --word-timestamps` |
| Pick a language | `whisper transcripts create audio.wav --language es` |
| Use a specific model | `whisper transcripts create audio.wav --model /path/to/ggml-small.en.bin` |
| Table view of segments | `whisper transcripts create audio.wav --table` |
| List local ggml models | `whisper transcripts models` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `whisper` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `whisper --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="No Authentication">
whisper.cpp is a local, offline tool. There is no auth, no cache, and no network calls. The wrapper resolves the `whisper-cli` binary and a local ggml model, normalizes input to 16 kHz mono WAV via `ffmpeg`, runs whisper.cpp, and returns JSON.
</principle>

<principle name="Command Groups">
- **transcripts create** -- Transcribe an audio/video file into a JSON transcript with timestamped segments (seconds). With `--word-timestamps`, the output also includes a word-level `words` array.
- **transcripts models** -- List local ggml model files found in the models directory.
</principle>

<principle name="Resolution Order">
- Model: `--model` > env `WHISPER_CPP_MODEL` > default `~/.local/share/cli-tools/whisper/models/ggml-base.en.bin`
- Binary: env `WHISPER_CLI_PATH` > env `WHISPER_CLI_COMMAND` > default `whisper-cli`
A missing binary or missing model fails fast with a clear error (no fallback).
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`whisper --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format (JSON by default, table with `--table`)
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
