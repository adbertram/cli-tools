---
name: "whisper-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute whisper operations using the `whisper` CLI tool. CLI wrapper for OpenAI Whisper speech-to-text transcription. Triggers: whisper, whisper cli, transcribe, transcription, speech to text, audio transcription, video transcription, transcribe audio, transcribe video"
---

<objective>
Execute whisper operations using the `whisper` CLI. All Whisper transcription interactions should use this CLI.
</objective>

<quick_start>
The `whisper` CLI follows this pattern:
```bash
whisper <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Transcribe a file | `whisper transcripts create video.mp4` |
| Transcribe with specific model | `whisper transcripts create video.mp4 --model base` |
| Transcribe with word timestamps | `whisper transcripts create video.mp4 -w` |
| List available models | `whisper transcripts models` |
| List existing transcripts | `whisper transcripts list ./dir/` |
| Read a transcript | `whisper transcripts get video.json` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `whisper` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Check Whisper availability (no-op -- runs locally)
- **transcripts** -- Transcription operations (create, list, get, models)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
