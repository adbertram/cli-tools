---
name: macspeech-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute macspeech operations using the `macspeech` CLI tool.
  On-device audio transcription on macOS via Apple SFSpeechRecognizer, with contextual-string vocabulary biasing, automatic punctuation, and per-word timestamps. No network, no authentication.
  Triggers: macspeech, macspeech cli, transcribe audio on-device, apple speech recognition, contextual strings, on-device transcription, SFSpeechRecognizer.
---

<objective>
Execute macspeech operations using the `macspeech` CLI. All macspeech interactions should use this CLI.
</objective>

<quick_start>
The `macspeech` CLI follows this pattern:
```bash
macspeech transcripts <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Transcribe an audio file on-device | `macspeech transcripts create audio.wav` |
| Bias vocabulary (semicolon-separated) | `macspeech transcripts create audio.wav --contextual-strings "worktree;subagent"` |
| Disable automatic punctuation | `macspeech transcripts create audio.wav --no-punctuation` |
| Check Speech Recognition authorization (passive) | `macspeech transcripts status` |
| List transcript JSON files | `macspeech transcripts list ./dir` |
| Get an existing transcript file | `macspeech transcripts get audio.json` |

Output JSON has top-level `text` (full transcript), `language`, and `words` (per-word `{text, start, end, confidence}`; seconds) — uniform with the whisper CLIs.

First-run note: the FIRST live `transcripts create` pops a one-time macOS "Speech Recognition" permission dialog (per install path). `transcripts status` reads authorization passively and never prompts.
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `macspeech` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `macspeech --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **transcripts** -- On-device transcription: `create` (transcribe a file), `status` (passive Speech Recognition authorization read; never prompts), `list` (find transcript JSON files), `get` (read an existing transcript file).
</principle>

<principle name="No Auth, No Cache">
macspeech has no `auth` and no `cache` command — recognition is on-device with no credentials. Do not look for or run `macspeech auth` / `macspeech cache`.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`macspeech --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
