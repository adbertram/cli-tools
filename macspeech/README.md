# macspeech CLI

## DESCRIPTION

Transcribe local audio files on-device using Apple's `SFSpeechRecognizer`, with vocabulary biasing via `contextualStrings`, automatic punctuation, and per-word timestamps. Recognition is fully offline through a bundled Swift helper, with no network service and no authentication. Use this CLI when you need fast, private, on-device speech-to-text on macOS, especially biasing recognition toward technical compound terms like worktree or detached HEAD.

## How It Works

API reference: <https://developer.apple.com/documentation/speech/sfspeechrecognizer>


Apple's Speech Recognition only runs when the requesting process is a properly bundled, code-signed app with an `NSSpeechRecognitionUsageDescription`. A bare compiled binary hard-crashes on the TCC check (SIGABRT). macspeech therefore:

1. Compiles the Swift helper (`helper/macspeech_helper.swift`) into `macspeech-helper`.
2. Assembles it into `MacSpeech.app/Contents/{MacOS/macspeech-helper, Info.plist}` (the Info.plist carries `NSSpeechRecognitionUsageDescription`).
3. Ad-hoc code-signs the `.app` (`codesign --force --deep --sign -`).
4. Launches it via LaunchServices: `open -W -n MacSpeech.app --args <audio> <locale> <out.json> ...`, so the `.app` is its own responsible process for the permission check.

Because `open` discards stdout, the helper writes its JSON result to an output-file path passed as an argument; the CLI reads that file.

The `.app` is installed at the tool's real user-data path — `~/.local/share/cli-tools/macspeech/MacSpeech.app`. The macOS Speech Recognition grant is **path-specific** for ad-hoc-signed apps, so the `.app` must live at this exact path; a grant for any other path does not carry over.

## Build

The Swift source and the bundle `Info.plist` live in `helper/`:

- `helper/macspeech_helper.swift` — the helper source.
- `helper/AppInfo.plist` — the bundle Info.plist (with `NSSpeechRecognitionUsageDescription`).
- `helper/build-app.sh` — compiles, assembles, and signs `MacSpeech.app`.

Build command (run automatically by `install.sh`):

```bash
# Assemble MacSpeech.app into ~/.local/share/cli-tools/macspeech (default)
./helper/build-app.sh

# Or into a custom directory
./helper/build-app.sh /custom/install/dir
```

Under the hood:

```bash
swiftc helper/macspeech_helper.swift -O -o macspeech-helper -framework Speech -framework Foundation
# assemble MacSpeech.app/Contents/{MacOS/macspeech-helper, Info.plist}
codesign --force --deep --sign - MacSpeech.app
```

Requires the Xcode command line tools (`xcode-select --install`) for `swiftc` and `codesign`.

## Installation

```bash
cd <cli-tools-root>/macspeech
./install.sh
```

`install.sh` installs the Python launcher (`uv tool install -e . --force --refresh`) **and** builds `MacSpeech.app` at the install path. After installation, the `macspeech` command is available in your terminal.

To install only the launcher (without rebuilding the helper):

```bash
uv tool install -e . --force --refresh
```

## First-Run Permission Grant (one-time)

The **first** live transcription pops a macOS dialog: *"MacSpeech wants to access Speech Recognition."* Click **Allow**. This grant is one-time per install path. You can check the current status at any time without prompting:

```bash
macspeech transcripts status
```

`authorization_status` raw values: `0`=notDetermined, `1`=denied, `2`=restricted, `3`=authorized.

## Quick Start

```bash
# Check Speech Recognition authorization (passive — never prompts)
macspeech transcripts status

# Transcribe an audio file (first run prompts for permission)
macspeech transcripts create audio.wav

# Bias recognition toward technical vocabulary
macspeech transcripts create audio.wav --contextual-strings "worktree;subagent;detached HEAD"
```

## Commands

### Transcripts

```bash
# Transcribe an audio file on-device
macspeech transcripts create audio.wav

# Choose a language (en maps to locale en-US; others pass through)
macspeech transcripts create audio.wav --language en

# Vocabulary biasing: semicolon-separated phrases -> contextualStrings
macspeech transcripts create audio.wav --contextual-strings "worktree;subagent;Codex"

# Turn off automatic punctuation (addsPunctuation, macOS 13+)
macspeech transcripts create audio.wav --no-punctuation

# Set a transcription timeout (seconds)
macspeech transcripts create audio.wav --timeout 120

# Show per-word segments as a table
macspeech transcripts create audio.wav --table

# Show Speech Recognition authorization status (passive — never prompts)
macspeech transcripts status
macspeech transcripts status --table

# List existing macspeech transcript JSON files in a directory
macspeech transcripts list
macspeech transcripts list ./transcripts/
macspeech transcripts list --filter "language:eq:en"
macspeech transcripts list --properties "file,word_count"
macspeech transcripts list --table

# Get details of an existing transcript file
macspeech transcripts get audio.json
macspeech transcripts get audio.json --properties "text,language"
macspeech transcripts get audio.json --table
```

## Output Contract

`transcripts create` (and `transcripts get`) emit JSON uniform with the whisper CLIs:

| Field | Description |
|-------|-------------|
| `text` | The full transcript string (mapped from the helper's `transcript` field) |
| `language` | The requested language code |
| `words` | Array of `{text, start, end, confidence}`; `start`/`end` in **seconds** |

Example:

```json
{
  "text": "permanent worktree handoff",
  "language": "en",
  "words": [
    {"text": "permanent", "start": 0.0, "end": 0.5, "confidence": 0.9},
    {"text": "worktree", "start": 0.5, "end": 1.0, "confidence": 0.8}
  ]
}
```

A downstream eval harness parses the top-level `text` key.

## Vocabulary Biasing (contextualStrings)

The headline capability. Phrases passed via `--contextual-strings` (or the `MACSPEECH_CONTEXTUAL_STRINGS` default) are fed to `SFSpeechRecognitionRequest.contextualStrings`, biasing the recognizer toward domain terms it would otherwise mis-hear (e.g. recognizing `worktree` as one token instead of "work tree"). This is the Apple analog of Whisper's `--initial-prompt`.

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

## Configuration

macspeech stores non-authentication configuration in `~/.local/share/cli-tools/macspeech/.env`. There are no credentials — recognition is on-device. Do not put secrets in any `.env` file.

| Variable | Description |
|----------|-------------|
| `MACSPEECH_CONTEXTUAL_STRINGS` | Default vocabulary-biasing phrases (semicolon-separated) used when `--contextual-strings` is omitted. Unset by default. |
| `MACSPEECH_INSTALL_DIR` | Override the directory holding `MacSpeech.app` (advanced/diagnostics). Changing it requires re-granting Speech Recognition permission for the new path. |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error (missing file, helper failure, unauthorized, timeout) |
| 2 | Client/configuration error |
| 130 | User interrupted (Ctrl+C) |

macspeech is fail-fast: a missing audio file, an uninstalled `.app`, a helper non-zero exit, an unauthorized status, an empty/missing helper output, or a timeout all raise a clear error — never a silent empty transcript.

## Examples

### Transcribe and extract just the text with jq

```bash
macspeech transcripts create audio.wav | jq -r '.text'
```

### Save a transcript to a JSON file

```bash
macspeech transcripts create audio.wav > audio.json
macspeech transcripts get audio.json --properties "text,language"
```

## Requirements

- macOS 13+ (Apple Speech on-device recognition; `addsPunctuation` is macOS 13+)
- Xcode command line tools (`swiftc`, `codesign`) for the helper build
- Python 3.11+
- Dependencies (installed automatically): typer, python-dotenv, cli-tools-shared

## License

MIT
