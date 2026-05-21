---
name: elevenlabs-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute ElevenLabs operations using the `elevenlabs` CLI tool.
  CLI interface for ElevenLabs API.
  Triggers: elevenlabs, elevenlabs cli, elevenlabs voices, elevenlabs models, elevenlabs speech, ElevenLabs text to speech, generate ElevenLabs audio, pronunciation dictionary, mispronounced words, list ElevenLabs voices, check ElevenLabs subscription, my ElevenLabs data
---

<objective>
Execute ElevenLabs operations using the `elevenlabs` CLI. All ElevenLabs interactions should use this CLI.
</objective>

<quick_start>
The `elevenlabs` CLI follows this pattern:
```bash
elevenlabs <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Authenticate | `elevenlabs auth login` |
| Check auth | `elevenlabs auth status` |
| List voices | `elevenlabs voices list --table` |
| Get voice settings | `elevenlabs voices settings <voice-id>` |
| List TTS models | `elevenlabs models list --filter "can_do_text_to_speech:eq:true" --table` |
| Generate speech | `elevenlabs speech create <voice-id> "Text" --output output.mp3` |
| List pronunciation dictionaries | `elevenlabs pronunciation-dictionaries list --table` |
| Create pronunciation dictionary rules | `elevenlabs pronunciation-dictionaries create-from-rules --name "Course Terms" --alias-rule "Sysadmins=sys admins"` |
| Generate speech with dictionary | `elevenlabs speech create <voice-id> "Text" --output output.mp3 --pronunciation-dictionary DICT_ID:VERSION_ID` |
| Check quota | `elevenlabs user subscription --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `elevenlabs` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `elevenlabs --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **voices** -- List voices, get voice metadata, and inspect voice settings.
- **models** -- List and inspect ElevenLabs models.
- **speech** -- Generate text-to-speech audio files, including pronunciation dictionary locators with `--pronunciation-dictionary DICT_ID:VERSION_ID`.
- **pronunciation-dictionaries** -- List, inspect, create from rules or PLS files, update metadata, set/add/remove rules, and download versioned PLS files.
- **user** -- Inspect subscription and quota state.
- **auth** -- Manage API-key authentication and profiles.
- **cache** -- Clear cached responses.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`elevenlabs --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
