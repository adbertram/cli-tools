---
name: "coursecraft-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute coursecraft operations using the `coursecraft` CLI tool. CLI interface for CourseCraft content management -- courses, modules, clips, demos, slides, outlines, voice recordings, and Descript exports. Triggers: coursecraft, coursecraft cli, coursecraft courses, coursecraft modules, coursecraft clips, coursecraft demos, coursecraft slides, coursecraft voice recordings, list coursecraft courses, coursecraft outlines, coursecraft descript, course content management, update coursecraft, coursecraft records"
---

<objective>
Execute coursecraft operations using the `coursecraft` CLI. All coursecraft interactions should use this CLI.
</objective>

<quick_start>
The `coursecraft` CLI follows this pattern:
```bash
coursecraft <command-group> <action> [arguments] [options]
```

| Command | Description |
|---------|-------------|
| `coursecraft cache clear` | Clear CourseCraft CLI cache data |
| `coursecraft courses list --active` | List active courses |
| `coursecraft modules list --course <slug> --table` | List modules for a course |
| `coursecraft clips show M1C2 --course <slug>` | Show clip hierarchy tree |
| `coursecraft demos list --module <recID> --table` | List demos in a module |
| `coursecraft slides update <recID> --script "..."` | Update slide script |
| `coursecraft course-outline read -l <doc-id>` | Read outline from Google Doc |
| `coursecraft courses get <slug> --include-clips` | Get course with nested clips |
| `coursecraft feedback list --slide <recID>` | List Feedback rows linked to a slide; do not add --filter to linked feedback reads |
| `coursecraft feedback update <recID> --processing-status Applied --processed-at <iso>` | Stamp a Feedback row after processing |
| `coursecraft voice-recordings preview --demo <recID>` | Read-only normalized narration/hash and cue/anchor validation before generation |
| `coursecraft voice-recordings generate --slide <recID> --voice-id <voice> --model-id eleven_multilingual_v2 --output-format <format> --output-dir <dir>` | Generate slide narration audio |
| `coursecraft descript export "Project" -m 2 -c 1` | Export Descript composition |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` before executing ANY `coursecraft` command.**
Use `/Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/coursecraft-cli/usage.json`; it contains the generated command tree with arguments, options, examples, and usage instructions. Do not look for command syntax in the CourseCraft project `.agents` tree, the CLI source folder, the installed uv tool directory, or by importing `coursecraft_cli` with ambient `python3`.

For live CLI state, inspect the actual `coursecraft` launcher/shebang or run `coursecraft --help` and the relevant subcommand `--help`. Never guess at command syntax. `usage.json` is generated from the live CLI and must be refreshed in this repo-owned skill folder after command-surface changes.

`usage.json` is a top-level object with command groups under `.commands`, not a top-level array. When querying several groups with `jq`, select them from `.commands` in one expression, for example:
`jq '.commands | {courses, demos, clips, slides}' /Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/coursecraft-cli/usage.json`.
Each command group stores actions under a nested `commands` object, not `actions`; inspect demo get/update syntax with:
`jq '.commands.demos.commands | {get, update}' /Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/coursecraft-cli/usage.json`.
Each command node stores `options` as an array of option objects, not an object keyed by option name. Inspect option names by iterating the array, for example:
`jq '.commands.demos.commands.update.options[].name' /Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/coursecraft-cli/usage.json`.
In Python probes, check the schema before formatting: `options = command.get("options") or []` and iterate the list.
</principle>

<principle name="Live Install Path">
The live `coursecraft` command is the uv tool launcher at
`~/.local/bin/coursecraft`, with its interpreter under
`~/.local/share/uv/tools/coursecraft-cli/`. Inspect the launcher shebang and
that interpreter's `importlib.metadata` / `coursecraft_cli.__file__` to prove
which editable source is active. Ignore ambient `python3 -m pip show
coursecraft-cli` when it reports the stale editable path
`/Users/adam/Dropbox/GitRepos/cli-tools/coursecraft`; that is not the live
console script. If source changes under
`/Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft` are not reflected,
reinstall the uv tool from that actual source:
`uv tool install -e /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --force --refresh`.
</principle>

<principle name="List Output Format">
`coursecraft <group> list` commands emit JSON by default. Do not add a guessed `--json` flag to list commands. Use `--table` only when human-formatted output is needed; save or pipe the default JSON output for `jq` parsing.
</principle>

<principle name="Hierarchical List Filters">
`coursecraft modules list` supports combining `--course` with `--filter`; use that form when you need modules for one course plus an additional module-field predicate. Other `coursecraft <group> list` commands with hierarchical convenience options still use exactly one selection path: either a hierarchy option (`--course`, `--module`, `--clip`, `--demo`, or `--slide`, as supported by that command) OR `--filter`. Do not combine `--filter` with non-module hierarchy options; when both constraints are needed outside `modules list`, list by the hierarchy option first, save or pipe the JSON, and apply the extra predicate locally with `jq`.
</principle>

<principle name="Feedback List Filters">
`coursecraft feedback list` has two mutually exclusive filter paths. Use exactly one hierarchical link option (`--demo`, `--slide`, `--clip`, `--module`, or `--course`) to fetch Feedback rows linked to a specific record, OR use `--filter` for a field predicate across Feedback rows. Do not combine `--filter` with any hierarchical link option. The exact CLI error is `Cannot use --filter with --demo, --slide, --clip, --module, or --course`. When both constraints are needed, fetch by the hierarchical link option and apply the extra predicate with `jq` against the returned JSON.
</principle>

<principle name="Update Output Is Not Readback JSON">
`coursecraft <group> update ...` commands print human status output such as `Updated demo: <record-id>`. Do not pipe update stdout to `jq` or treat it as the updated Airtable record. After any update, verify through the canonical read path: run the matching `get` command for the same record ID, save that JSON if you need an evidence file, and parse the `get` output.

If a mutating `coursecraft <group> update ...` command times out with `airtable CLI command timed out after 45s`, the write state is unknown. Do not rerun the mutation blindly. First read the same record with the matching `coursecraft <group> get <record-id>` command and compare the intended field; retry only when that read-back proves the value did not persist.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication management via Airtable PAT delegation
- **cache** -- Local response cache management
- **courses** -- CRUD for course records with nested creation and --active/--include-modules/--include-clips support
- **course-outline** -- Read and update course outline Google Docs, sync to database
- **modules** -- CRUD for module records with batch clip creation and ASCII tree display via show
- **clips** -- CRUD for clip records with batch creation and M1C1/M2C3 shorthand support
- **demos** -- CRUD for demo records with hierarchical filtering (--clip, --module, --course)
- **slides** -- CRUD for slide records with hierarchical filtering and build-instructions/script fields
- **slide-templates** -- Manage PowerPoint slide template definitions with --platform filtering
- **feedback** -- CRUD for CourseCraft Feedback rows with per-level link filters (`--demo`, `--slide`, `--clip`, `--module`, `--course`), `Processing Status`/`Patterns Learned`/`Processed At` writes, and write verification. This is the first-class path for Feedback-table I/O; do not use raw `airtable` for the Feedback table.
- **voice-recordings** -- Generate slide and demo narration audio with ElevenLabs and store recording metadata
- **descript** -- Export video clips from Descript projects to course folders
</principle>

<principle name="Order And Narrative Field Names By Table">
The sequence-within-parent concept and narrative fields are named differently per table. These names are verbatim from `coursecraft_cli/field_mappings.py` and live Airtable; use them exactly.

| Table | Sequence field | Narrative field |
|-------|----------------|-----------------|
| **Clips** | `Order` | `Story` |
| **Slides** | `Clip Order` | none |
| **Demos** | `Clip Order` | `Clip Story` |

`Clip Order` and `Clip Story` do not exist on the Clips table. When operating on a clip record, never probe `fields["Clip Order"]` or `fields["Clip Story"]`; those are Slides/Demos field names. `Demos.Clip Story` is separate from `Clips.Story`.
</principle>
</essential_principles>

<principle name="Voice Recording State">
Run `coursecraft voice-recordings preview --demo <recID>` before automatic demo narration generation. The preview is read-only: it makes no ElevenLabs call and performs no Airtable mutation. Preview and demo generation require one positive record `Target Length (Min)`, enforce the same `Target Length (Min) * 180` total-word budget through CourseCraft's canonical Demo Script parser, and do so before pronunciation-dictionary, ElevenLabs, or Airtable mutation. Preview emits the normalized spoken narration, deterministic SHA-256, enforced `narrationBudget` identity, cue validation, and manifest-anchor validation as JSON. A nonzero result means paid generation is blocked until the Script/manifest contract is corrected.

`coursecraft voice-recordings generate --slide ...` and `coursecraft voice-recordings generate --demo ...` are only for workflows that need separate generated narration before video capture. They strip non-spoken recording cues, apply packaged regex pronunciation transforms from `coursecraft_cli/voice_pronunciation_patterns.json` and `coursecraft_cli/voice_pronunciation_tokens.json` for dynamic code-shaped text, sync alias rules from `coursecraft_cli/voice_pronunciations.json` into the ElevenLabs pronunciation dictionary named `CourseCraft Voice Pronunciations`, pass that dictionary locator to `elevenlabs speech create`, store generated audio metadata, and set `Dictation Recorded` to true. The regex transforms normalize common code shapes such as PowerShell cmdlets, parameters, variables, dotted module names, Windows paths, file names, pipes, and `%` aliases; static course terms stay in the source text and are handled by the ElevenLabs dictionary. They never set `Recorded`, because final recording also requires the video portion. If video and audio will be recorded together, skip voice recording generation and leave `Dictation Recorded` unset. Slide audio keeps the legacy `<output-dir>/m<module number>/slides/<slide number> - <slide title>.mp3` path; demo narration uses the transactional authority contract below.

For `generate --demo`, production voice precedence is deterministic and live-verified: (1) explicit `--voice-id`, (2) the Demo's current `ElevenLabs Voice ID`, then (3) exactly one live ElevenLabs voice labeled `coursecraft_role=production`. Every selected ID is verified with `elevenlabs voices get`; missing or multiple labeled fallbacks fail before generation. The only supported authoritative demo format is `mp3_44100_128`, which derives `.mp3`; unsupported formats fail before spend. `--model-id` defaults to `eleven_multilingual_v2` because CourseCraft narration uses a Professional Voice Clone and Eleven v3 does not currently support PVCs. Legacy tuning flags such as `--style` and `--speaker-boost` are not passed by default; provide tuning flags only after validating the selected ElevenLabs model supports them.

Demo generation is fail-closed and transactional. It keys idempotence on the canonical normalized Script hash plus voice, model, format, pronunciation dictionary ID/version, tuning, and validated output hash. It generates to a UUID staging path, never the current `Voice Recording Path`; full-decodes the one audio stream; requires positive duration; verifies the canonical source hash, request identity, no cue leakage, whole-script Whisper recall, and a `-1.0 dBFS` peak/no-clipping policy; then promotes to a content-identity path without overwrite. An adjacent `<audio>.narration.json` records source/output hashes, exact identities, validation evidence, and the deterministic derived-WAV input policy (`pcm_s16le`, 48 kHz, mono) for downstream adapters. Only after promotion does one CourseCraft update write narration metadata, `Voice Recording Path`, and `Dictation Recorded=true`, followed by uncached readback; `Recorded` is never in that write. A validated local promotion can be registered after a write failure without another paid generation. Generation timeouts create a pending reconciliation record and block automatic retry until local, CourseCraft, and ElevenLabs history state are reconciled; failures leave the prior authoritative take and CourseCraft fields unchanged.
</principle>

<principle name="Course Disable Gate">
The Courses table has a `Disabled` checkbox plus required `Disabled Notes` long-text reason. Use `coursecraft courses disable <course> --why "<reason>"` to disable a course; do not set `Disabled` through ad hoc Airtable writes. After `Disabled` is checked, CourseCraft CLI mutations to the course and to records in its course hierarchy (Modules, Clips, Demos, Slides, linked Feedback) are blocked by the client. The only allowed transition is the initial disable write while the course is still enabled. Read-only commands remain allowed so agents can inspect and report the disabled reason.
</principle>

<reference_index>
**`/Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/coursecraft-cli/usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions.
**`coursecraft --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

## Testing

Run CourseCraft CLI tests through the CourseCraft uv project so the editable
`cli-tools-shared` dependency is importable. Do not use ambient Python.

```bash
uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_modules_update.py -q
```

## Known Issues

### 1. VM Acronym Pronunciation Creates Bad TTS Output
**Symptom:** ElevenLabs generated an unnatural pause between the V and M when slide narration said `VMs`. The first attempted fix, `vee ems`, produced audio that sounded like `V E M`.
**Cause:** The CourseCraft voice pronunciation data expanded `VMs` to acronym-like or phonetic spellings that the TTS engine still interpreted as separated letters.
**Fix:** Store prose `VMs`/`VM` as alias rules in `coursecraft_cli/voice_pronunciations.json`, let `coursecraft voice-recordings generate` sync the `CourseCraft Voice Pronunciations` dictionary, and keep identifier token `VM` as `virtual machine` for code-shaped text.
**Verification:** Run `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_voice_recordings.py`, then regenerate a slide containing `VMs` with `coursecraft voice-recordings generate` and verify `elevenlabs speech create` receives the `CourseCraft Voice Pronunciations` dictionary locator.
**Recurrence Prevention:** Prefer plain-English expansions for acronyms when TTS pacing is rejected; do not use phonetic spellings such as `vee ems` unless a generated audio sample has been accepted.

### 2. Idempotent Pronunciation Requires A Tight Alias
**Symptom:** ElevenLabs paused and slowed down when slide narration said `idempotent` as `eye dem poh tent`. Passing the raw word through produced audio that sounded like `eedempotent`. The spaced alias `I dim po tent` still produced brief pauses between syllables.
**Cause:** The CourseCraft voice workflow uses pronunciation dictionaries for recurring terms; per the ElevenLabs skill guidance, deterministic pronunciation problems should be handled with alias pronunciation dictionary rules unless phoneme support is documented for the selected model.
**Fix:** Store `idempotent` as the single-token alias `Idimpohtent` in `coursecraft_cli/voice_pronunciations.json`.
**Verification:** Run `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_voice_recordings.py`, then regenerate a slide containing `idempotent` with `coursecraft voice-recordings generate` and verify `elevenlabs speech create` receives the synced pronunciation dictionary locator.
**Recurrence Prevention:** For rejected pronunciations, remove spaces from alias spellings when the accepted pronunciation must read as one word, then test the normalized source text before regenerating audio.

### 3. Sysadmins Pronunciation Must Stay Raw Unless Full-Slide Audio Proves Otherwise
**Symptom:** ElevenLabs mispronounced `PowerShell for Sysadmins` in the full Technical Prerequisites slide when dictionary aliases forced `sisadmins`; the generated audio sounded like `CS Admins`. Earlier spaced aliases such as `sis admins` and `sys admins` also produced separated-letter or paused pronunciations.
**Cause:** The production voice and `eleven_multilingual_v2` handled raw `Sysadmins` correctly in the accepted full-slide sample, while custom aliases changed model behavior in surrounding sentence context.
**Fix:** Do not store `PowerShell for Sysadmins`, `sysadmins`, `Sysadmins`, or `SysAdmins` in `coursecraft_cli/voice_pronunciations.json`. Let those terms pass through raw source text; the voice-recordings command should sync the shared dictionary without any sysadmins-specific rules.
**Verification:** Run `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_voice_recordings.py`, sync the `CourseCraft Voice Pronunciations` dictionary, regenerate the Technical Prerequisites slide with the production voice/model/settings, then transcribe it with `openai-whisper transcripts create` and confirm the opening says `PowerShell for sysadmins`.
**Recurrence Prevention:** Do not add sysadmins pronunciation aliases based on spelling intuition or short isolated samples. Only add a future sysadmins rule after a blind, full-slide production-voice sample is accepted and the official regenerated slide transcribes correctly.

### 4. Cache Clear Requires Config Storage Directory
**Symptom:** `coursecraft cache clear` failed with `Error: 'Config' object has no attribute 'storage_dir'`.
**Cause:** CourseCraft registered the shared `cli_tools_common.cache_commands.create_cache_app`, which requires every tool config to expose a `storage_dir` property, but `coursecraft_cli.config.Config` only exposed `tool_dir` and profile helper methods.
**Fix:** Add `Config.storage_dir` returning `self.get_profile_data_dir()` in `coursecraft_cli/config.py`.
**Verification:** Run `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_config.py`, `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest`, and `coursecraft cache clear`; the cache command should return JSON with `files_removed` and `bytes_freed`.
**Recurrence Prevention:** When registering shared `cli_tools_common` apps, verify the tool-specific config implements the properties required by that shared app and add a focused config test.

### 5. Script Updates Must Clear All Voice Metadata
**Symptom:** A slide or demo can show `Voice Generated At` after its `Script` changes even though `Voice Recording Path`, model metadata, and `Dictation Recorded` were cleared. The record then looks partially generated and blocks slide recording preflight.
**Cause:** `coursecraft_cli/voice_recording_fields.py` invalidated generated voice fields after script edits but did not clear `Voice Character Count` or `Voice Generated At`.
**Fix:** Include `Voice Character Count` and `Voice Generated At` in `get_voice_recording_invalidation_fields()`, then regenerate narration with `coursecraft voice-recordings generate` for any records that were already invalidated.
**Verification:** Run `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_voice_recording_invalidation[.]py /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_voice_recordings.py /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_slides_update.py /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_demos_update.py /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_config.py`, then verify affected records with `coursecraft --no-cache slides list --module <module-id> --properties "id,fields.Name,fields.Voice Recording Path,fields.Dictation Recorded,fields.Voice Generated At"`.
**Recurrence Prevention:** When adding new generated voice metadata fields, update the voice-recording invalidation helper and its tests in the same change.

### 6. Slide Recordings Need A Final Recorded CLI Flag
**Symptom:** After a successful slide MP4 recording, CourseCraft slide records could be marked `Dictation Recorded` but not final `Recorded` through the `coursecraft slides update` command.
**Cause:** Demo updates exposed `--recorded`, but slide updates only exposed `--dictation-recorded`, leaving the final slide recording state without a supported CLI path.
**Fix:** Add `coursecraft slides update <record-id> --recorded` so the command writes `Recorded=true`.
**Verification:** Run `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_slides_update.py -q`, `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest`, `coursecraft slides update --help`, and verify live records with `coursecraft --no-cache slides list --module <module-id> --properties "id,fields.Name,fields.Recorded,fields.Dictation Recorded,fields.Status"`.
**Recurrence Prevention:** Keep separate flags for dictation audio and final video recording. Generated narration uses `--dictation-recorded`; completed slide videos use `--recorded`.

### 7. --no-cache Flag Position And The OSC Escape Are Not Output Bugs
**Symptom:** `coursecraft demos get <id> --no-cache` with the flag after the subcommand exited 2 with empty stdout; when stderr was discarded it looked like JSON output was missing. A terminal OSC escape also appeared around output in some shells.
**Cause:** `--no-cache` is a global app-level option and older shared parsing only honored it before the subcommand. The OSC escape came from the terminal/shell background-color query, not from `coursecraft` JSON output.
**Fix:** Shared CLI app startup hoists standalone `--no-cache` so it is position-independent. `coursecraft` JSON output is written as raw JSON bytes and redirected stdout is escape-free.
**Verification:** Run shared app-factory tests, a coursecraft JSON read with `--no-cache` after the subcommand, and parse redirected stdout with `jq`.
**Recurrence Prevention:** Do not diagnose empty JSON output with stderr discarded. For CourseCraft write verification, rely on the client's built-in persistence check and/or a plain `coursecraft <res> get <id>` read-back.

### 9. Long-Text Write Verification Tolerates Airtable Canonicalization
**Symptom:** Writes to long-text fields such as `Learning Objectives`, `Script`, `Demo Overview`, `Brainstorming Outline`, `Story`, or `Clip Story` raised `WriteVerificationError` even though read-back showed the content persisted. Differences were limited to Airtable-added trailing newlines or Markdown canonicalization such as escaped punctuation and `*`/`_` emphasis delimiter rewrites.
**Cause:** Airtable canonicalizes rich long-text fields on persist, while the client originally compared sent and persisted strings too literally.
**Fix:** CourseCraft write verification normalizes only render-identical Airtable reshaping: trailing whitespace/newline, CommonMark punctuation escapes, and `*`/`_` emphasis delimiter swaps. Interior changes, truncation, substitutions, and leading whitespace still fail verification.
**Verification:** `tests/test_client_write_verification.py` covers accepted canonicalization and rejected real content changes; live long-text writes should persist and read back intact.
**Recurrence Prevention:** If a new long-text write trips `WriteVerificationError`, diff sent vs uncached read-back first. Extend only the canonical long-text comparison for render-identical Airtable reshaping; do not weaken per-field logic or normalize content differences.

### 10. Slide Template Version Must Be CLI-Writable
**Symptom:** `build_module_deck.py` rejects slides with `template version invalid: None` when the linked slide template lacks `Template Deck Version`, and `coursecraft slide-templates update` cannot repair the template if it has no `--template-deck-version` flag.
**Cause:** The slide-template create/update commands did not expose the Airtable `Template Deck Version` field even though the PowerPoint deck builder hard-gates on `2025.2`.
**Fix:** Add `--template-deck-version` to `coursecraft_cli/commands/slide_templates.py` create and update paths so template records can be corrected through the CLI.
**Verification:** Run `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_slide_templates_requirements.py -q`, `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest`, then verify the live template with `coursecraft --no-cache slide-templates get <template-record-id> --properties "id,fields.Name,fields.Template Deck Version"`.
**Recurrence Prevention:** When a builder depends on a template metadata field, expose that field through the template CLI before editing Airtable records.

### 11. Demo AI-Test Approval Is Invalidated By Design Changes
**Symptom:** A demo can remain `AI Tested=true` after its Demo Overview, Environment Spec, or Action Summary changes, leaving stale proof attached to different design content.
**Cause:** The demo update path previously treated the approval checkbox as independent state and did not invalidate it when its tested inputs changed.
**Fix:** `coursecraft demos update` writes `AI Tested=false` whenever Demo Overview, Environment Spec, or Action Summary changes. Finalization is a separate explicit `coursecraft demos update <id> --ai-tested` operation after verification; the CLI rejects combining `--ai-tested` with those content updates.
**Verification:** Run `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_demos_update.py -q`, then verify live records with `coursecraft demos get <demo-record-id> --properties "id,fields.Name,fields.AI Tested"`.
**Recurrence Prevention:** Treat Demo Overview, Environment Spec, and Action Summary as the canonical inputs to AI testing. Any new command that mutates one of them must clear `AI Tested` in the same write.

### 12. Single Demo Reads Support `--properties`
**Symptom:** `coursecraft demos get <id> --properties ...` failed even though list commands support field projection.
**Cause:** `demos get` did not expose the shared properties filter.
**Fix:** Add `--properties/-p` to `coursecraft_cli/commands/demos.py` get path and apply `apply_properties_filter([record], properties)[0]` for JSON output.
**Verification:** Run `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_demos_update.py -q` and `coursecraft demos get --help`.
**Recurrence Prevention:** When a resource list command supports `--properties`, keep its single-record get command in parity unless table output intentionally needs the full record.

### 13. Single Clip Reads Support `--properties`
**Symptom:** `coursecraft clips get <id> --properties ...` failed even though `clips list` and `demos get` supported field projection.
**Cause:** `clips get` did not expose the shared properties filter.
**Fix:** Add `--properties/-p` to `coursecraft_cli/commands/clips.py` get path and apply `apply_properties_filter([record], properties)[0]` for JSON output.
**Verification:** Run `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_clips_update.py -q`, `coursecraft clips get --help`, and a live read such as `coursecraft --no-cache clips get <clip-id> --properties "id,fields.Name,fields.Status"`.
**Recurrence Prevention:** Keep every single-record `get` command in parity with the shared output-field-selection contract unless table output intentionally needs the full record.

### 14. Single Course and Module Reads Support `--properties`
**Symptom:** `coursecraft courses get <id-or-slug> --properties ...` and `coursecraft modules get <id> --properties ...` failed even though their list commands and the clips/demos get commands supported field projection.
**Cause:** `courses get` and `modules get` did not expose the shared properties filter.
**Fix:** Add `--properties/-p` to `coursecraft_cli/commands/courses.py` and `coursecraft_cli/commands/modules.py` get paths and apply `apply_properties_filter([record], properties)[0]` for JSON output.
**Verification:** Run `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_courses_update.py /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_modules_get.py -q`, `coursecraft courses get --help`, `coursecraft modules get --help`, and live reads such as `coursecraft --no-cache courses get <course-id-or-slug> --properties "id,fields.Name,fields.Status"` and `coursecraft --no-cache modules get <module-id> --properties "id,fields.Name,fields.Status"`.
**Recurrence Prevention:** Keep `get --properties` parity across every resource whose `list` command supports field projection.

### 15. Intermittent `airtable CLI is not installed or not in PATH` Is A False Positive
**Symptom:** `python3 scripts/validate_build_product.py content-slide <recId>` (or any `coursecraft <res> get/list/update`) intermittently failed ONE record/call with `Error: airtable CLI is not installed or not in PATH. Install it with scripts/install-cli-tool.sh airtable from the cli-tools repo root.` Re-running the identical command immediately succeeded (`ok:true`). `which airtable` returned `/Users/adam/.local/bin/airtable` (exit 0) the entire time -- the binary was always present. Most reproducible under batch contention (e.g. several slide validations at once): one failed while the rest passed.
**Cause:** `CourseCraftClient.__init__` gated on `_check_airtable_cli()`, which spawned `airtable --version` with a 5s timeout (`AIRTABLE_CLI_VERSION_TIMEOUT_SECONDS`) and treated `subprocess.TimeoutExpired` as "binary missing". `airtable` is a uv-tool CLI whose launcher cold-starts a fresh Python interpreter (~0.23s warm). Under concurrent cold-cache load -- the validator spawns `coursecraft` (interpreter cold start) which spawns `airtable --version` (another cold start) plus the real `airtable records get` -- that `--version` probe could exceed 5s and be misreported as "not installed". It was never a PATH problem (PATH always contained `~/.local/bin`); it was a timeout false negative on a heavy startup probe.
**Fix:** Replaced the subprocess `--version` probe with a pure PATH lookup. `coursecraft_cli/client.py` now has module-level `_resolve_airtable_binary()` using `shutil.which("airtable", path=...)` (with `~/.local/bin` forced onto the search path); `_check_airtable_cli()` returns `_resolve_airtable_binary() is not None`. A PATH lookup never starts a process and never times out, so a present-on-PATH binary can never yield the false "not installed". Any genuinely transient runtime failure now surfaces later with the real airtable stderr via `_run_airtable_command` (`airtable CLI error: <stderr>`), not the misleading install hint. Removed the now-unused `AIRTABLE_CLI_VERSION_TIMEOUT_SECONDS` constant.
**Verification:** `tests/test_client_airtable_detection.py` (availability check spawns no subprocess; a timing-out `--version` no longer false-negatives; a genuinely missing binary still raises the clear install error; `_resolve_airtable_binary` finds `~/.local/bin/airtable` even when PATH omits it, and returns None when absent). Full suite `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/` -> 144 passed. Ran `python3 scripts/validate_build_product.py content-slide recvSkOmGovjeG3sn` 22x (10 serial + 12 concurrent) with zero false "not installed" and every `slide_script.record_read` passing.
**Recurrence Prevention:** Never gate availability on a process-spawning probe (`<tool> --version`) with a short timeout -- a slow interpreter cold start under load reads as "missing". Use `shutil.which` for "is the binary on PATH" checks. If an "airtable not installed" error ever appears while `which airtable` exits 0, treat it as a transient/false positive and surface the real downstream stderr rather than the install hint.

### 16. Datetime Write Verification Is A False Positive Across `+00:00` vs `.000Z`
**Symptom:** A `coursecraft <res> create/update` (or `coursecraft feedback create`) that writes a dateTime field (e.g. `Feedback Requested At`, the `Feedback` table `Timestamp`) raised `WriteVerificationError` — `sent '2026-06-20T19:05:00+00:00', persisted '2026-06-20T19:05:00.000Z'` — even though the row persisted intact (reproduced on Feedback row `reckVbS58RCw2C3Wn`). Re-reading the record showed the value was correctly stored; only the post-write verification failed.
**Cause:** `CourseCraftClient._persisted_value_matches` compared scalar values as literal strings (plus the existing trailing-newline and Markdown tolerances). Airtable persists dateTime fields in UTC as `...T...:00.000Z`, while callers send the equivalent `+00:00` offset form. Those two strings are unequal but denote the **same instant**, so verification wrongly reported a mismatch — the same class of false-positive as the older long-text trailing-newline bug, just for datetimes.
**Fix:** `coursecraft_cli/client.py` now adds `_parse_iso_datetime` (parses an ISO-8601 string, normalizing a trailing `Z` to `+00:00`, returns `None` for non-datetimes) and `_datetime_instants_match` (true only when both sides parse as datetimes AND refer to the same instant; aware datetimes compared via `timestamp()`, a naive-vs-aware mix rejected). `_persisted_value_matches` calls it after the trailing-whitespace branch and before the long-text normalization. A different instant, a naive-vs-aware mix, or any non-datetime scalar still mismatches, so verification is not weakened.
**Verification:** Smoke-checked against the installed module via the launcher shebang interpreter: `_persisted_value_matches("2026-06-20T19:05:00+00:00", "2026-06-20T19:05:00.000Z")` returns `True`; a one-minute-different datetime and a `-05:00` offset of the same wall-clock both return `False`; non-datetime text and `--typecast` number coercion still behave as before. (Per project policy no new test file was added.)
**Recurrence Prevention:** When verifying that a typed value persisted, compare by the value's semantic identity, not its string form. For datetimes that means comparing instants (tolerating offset vs `Z` and millisecond precision); for other coerced types prefer the canonical-form compare already used for numbers and long text. A bare string mismatch on a value Airtable is known to canonicalize is a verification bug, not a failed write.

### 17. Single Slide Reads Support `--properties`
**Symptom:** `coursecraft slides get <id> --properties ...` failed with `No such option: --properties`, even though `slides list` and other single-record get commands supported field projection.
**Cause:** `slides get` did not expose the shared properties filter.
**Fix:** Add `--properties/-p` to `coursecraft_cli/commands/slides.py` get path and apply `apply_properties_filter([record], properties)[0]` for JSON output.
**Verification:** Run `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_slides_update.py -q`, `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft coursecraft slides get --help`, and a live read such as `coursecraft --no-cache slides get <slide-id> --properties "id,fields.Name,fields.Status"`.
**Recurrence Prevention:** Keep every single-record `get` command in parity with the shared output-field-selection contract unless table output intentionally needs the full record.

### 18. Demo Status Formula Must Not Gate On Non-Writable `Estimated Length`
**Symptom:** A demo with `Target Length (Min)` set and `Estimated Length` empty stayed in `Ready to Design (Basic Fields)` after `Demo Overview Human Verified=true`.
**Cause:** The live Airtable Demos `Status` formula gates basic readiness on `Estimated Length`, but `coursecraft demos create/update --target-length` writes the existing writable Demos field `Target Length (Min)`. Attempting to write `Estimated Length` through Airtable returned `403`: `You are not permitted to write cell values in field Estimated Length (fldiTTGwIN858p5Rr)`.
**Fix:** Keep the CLI mapped to writable `Target Length (Min)`. The durable source fix is in Airtable: update the Demos `Status` formula to use `Target Length (Min)` for basic readiness, or replace `Estimated Length` with a writable field and migrate the CLI/schema deliberately.
**Verification:** Run `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_demos_update.py -q`, verify `coursecraft demos update <id> --target-length <n>` writes `Target Length (Min)`, and verify Airtable Demos `Status` no longer depends on non-writable `Estimated Length`.
**Recurrence Prevention:** Do not remap Demos `--target-length` to `Estimated Length` while Airtable rejects writes to that field. Align the Airtable `Status` formula with the writable CLI field first.

### 19. Single Feedback Reads Support `--properties`
**Symptom:** `coursecraft feedback get <id> --properties ...` failed with `No such option: --properties`, even though `feedback list` and every other single-record get command (courses/modules/clips/demos/slides) supported field projection. Callers had to fetch the full record and project fields with `jq`.
**Cause:** `feedback get` did not expose the shared properties filter.
**Fix:** Add `--properties/-p` to `coursecraft_cli/commands/feedback.py` get path and apply `apply_properties_filter([record], properties)[0]` for JSON output. Empty/absent requested fields project as explicit `null`, matching the shared projection contract.
**Verification:** Reinstall with `uv tool install -e /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --force --refresh`, run `coursecraft feedback get --help`, and a live read such as `coursecraft feedback get <feedback-id> --properties "fields.Feedback,fields.Processing Status"` returns only the projected keys while `coursecraft feedback get <feedback-id>` still returns the full record.
**Recurrence Prevention:** Keep every single-record `get` command in parity with the shared output-field-selection contract unless table output intentionally needs the full record.

### 20. Single Slide Template Reads Support `--properties`
**Symptom:** `coursecraft slide-templates get <id> --properties ...` failed with `No such option: --properties`, even though `slide-templates list` and every other single-record get command (courses/modules/clips/demos/slides/feedback) supported field projection. Fetching template cue metadata (e.g. `Template Deck Number`) required pulling full records with large `Image` attachment payloads.
**Cause:** `slide-templates get` did not expose the shared properties filter.
**Fix:** Add `--properties/-p` to `coursecraft_cli/commands/slide_templates.py` get path and apply `apply_properties_filter([record], properties)[0]` (via the shared `project_record` helper) for JSON output.
**Verification:** Run `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft/tests/test_slide_templates_get.py -q`, reinstall with `uv tool install -e /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --force --refresh`, run `coursecraft slide-templates get --help`, and a live read such as `coursecraft slide-templates get <template-record-id> --properties "id,fields.Name,fields.Template Deck Number"` returns only the projected keys while `coursecraft slide-templates get <template-record-id>` still returns the full record.
**Recurrence Prevention:** Keep every single-record `get` command in parity with the shared output-field-selection contract unless table output intentionally needs the full record.

### 21. Feedback Create/Update Wrote A Non-Existent `Feedback Source` Field
**Symptom:** `coursecraft feedback create` — with the REQUIRED `--source`/`--feedback-source` option supplied exactly as `--help` documents — and `coursecraft feedback update --source ...` both failed live with `Error: Error running airtable CLI: airtable CLI error: Error: API request failed (422): Unknown field name: "Feedback Source"`, making `feedback create` unusable for any caller following its own `--help`.
**Cause:** `coursecraft_cli/commands/feedback.py` hardcoded the literal string `"Feedback Source"` inline at both write sites (`create` and `update`) instead of resolving the field name through `field_mappings.py`. `field_mappings.py`'s `'Feedback'` table mapping carried two keys for the same concept — the stale `'feedback_source': 'Feedback Source'` and the correct `'source': 'Source'` — and the command module referenced the wrong one. The live Airtable Feedback table's field is named `Source`, not `Feedback Source`. The `create` command's own `--help` docstring compounded this: its prose and examples showed `--source User` / `--source Pluralsight`, neither of which is a valid `FeedbackSource` enum value (the real values are `CourseCraft` and `Pluralsight Feedback Sheet`).
**Fix:** Added `SOURCE_FIELD = validate_field("source", "Feedback")` as a module-level constant in `coursecraft_cli/commands/feedback.py` (the same pattern `demos.py` uses for `AI_TESTED_FIELD`) and used it at both the `create` and `update` write sites in place of the hardcoded literal. Removed the dead `'feedback_source': 'Feedback Source'` key from `field_mappings.py`'s `Feedback` mapping since no field by that name exists on the live table. Corrected the `create` docstring's prose and every example to use the real enum values `CourseCraft` / `Pluralsight Feedback Sheet`. Corrected the `tests/test_feedback.py` assertions that had encoded the wrong field name (`"Feedback Source"` in expected written/mapped/filtered fields) to expect `"Source"`.
**Verification:** `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest tests/test_feedback.py -v` (6 passed) and full suite `python -m pytest tests/` (358 passed). Reinstalled with `uv tool install -e /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --force --refresh`. Live: re-ran the exact originally failing repro (`coursecraft feedback create --slide recfqQO9GuR5pezkH --source CourseCraft --feedback "test" --element-type Slide --attribute-name "Build Instructions" --attribute-snapshot "test" --processing-status Pending`) — it now succeeds; `coursecraft feedback get <id>` confirmed `"Source": "CourseCraft"` was actually persisted, then the verification record was deleted. Separately created, read back, and deleted two throwaway unlinked rows (no `--slide`/`--clip`/`--module`/`--course`/`--demo`), one per enum value (`CourseCraft` and `Pluralsight Feedback Sheet`), confirming both `create` and `update` persist to the correct `Source` field for both allowed values.
**Recurrence Prevention:** Never hardcode an Airtable field-name literal inline in a command module when `field_mappings.py` already has, or should have, a mapping entry for that table/field — reference it via `validate_field(<cli_key>, <table>)` as a module-level constant, matching the `demos.py` `AI_TESTED_FIELD` pattern. When a table's mapping carries two keys that could plausibly represent the same concept, verify both against the live Airtable schema and delete whichever does not correspond to a real field rather than assuming the more descriptive-looking key is correct. Keep a command's own `--help` docstring examples in sync with its enum's real values; a wrong example in `--help` is as much a bug as wrong code.

### 22. Demos Update Had No Way To Unlink A Demo From Its Clip
**Symptom:** `coursecraft demos update <id> --clip ""`, the only plausible syntax for clearing a demo's clip relationship, failed live with `Error: Error running airtable CLI: airtable CLI error: Error: API request failed (422): Value "" is not a valid record ID. Could not find record with matching name and we can not create linked records because their primary field is computed`. There was no supported way to unlink a demo from its clip (e.g. when retiring a demo record after merging its content into a sibling) without this error; the command only supported re-parenting to a new, non-empty clip record ID.
**Cause:** `coursecraft_cli/commands/demos.py`'s `update_demo` unconditionally wrapped any non-`None` `--clip` value as a one-element list — `fields["Clip"] = [clip]` — so `--clip ""` sent `["", ]` (a linked-record array containing an empty-string record ID) instead of `[]` (an empty linked-record array, which is how Airtable's API represents "no linked record"). Airtable rejects `""` as a record ID because it cannot resolve or create a linked record from it. Note `Clip` — not the `field_mappings.py`-declared `'clip': 'Clip Record ID'` — is the real Demos linked-record field; `Clip Record ID` (along with `Clip ID`, `Clip Name`, and the rest of the Clip-side lookups on a Demo) is a read-only lookup that mirrors the linked Clip and goes empty automatically once `Clip` is cleared.
**Fix:** Changed the `--clip` handling in `update_demo` to `fields["Clip"] = [clip] if clip else []`, so an explicit empty string is the unlink sentinel (sends `[]`) while any non-empty value still re-parents exactly as before. Updated the `--clip` option help text and the command's example list to document `--clip ""` as the unlink syntax.
**Verification:** Added `test_update_demo_accepts_clip_unlink` to `tests/test_demos_update.py` asserting `--clip ""` sends `{"Clip": []}` (alongside the existing `test_update_demo_accepts_clip_reparent` covering the non-empty case). `uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --with pytest python -m pytest tests/test_demos_update.py -q` (54 passed) and full suite `python -m pytest tests/` (363 passed). Reinstalled with `uv tool install -e /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --force --refresh`. Live: ran `coursecraft demos update recTjIj9kTgnoCs5R --clip "" --name "MERGED — see recUQg2QKq3aGOVV6 — Adding a circuit breaker"` (and the same pattern for two sibling demos being retired after a content merge); `coursecraft --no-cache demos get <id> --properties "fields.Clip,fields.Clip Record ID,fields.Clip ID,fields.Clip Name"` confirmed all four project to `null`, and `coursecraft --no-cache demos list --clip <former-clip-id>` no longer returned the unlinked demo, while the record itself still existed (Status populated, Name renamed) — unlinked, not deleted.
**Recurrence Prevention:** When a CLI option re-parents a single-link field, decide and document the clear/unlink syntax (an explicit empty-string sentinel mapping to `[]`) in the same change that adds the re-parent option, rather than leaving link-clearing unsupported until a real workflow (like retiring a merged record) needs it. `slides.py`'s `update_slide --clip` re-parent option had the same one-directional shape; see Known Issue #23 for its matching fix.

### 23. Slides Update Had No Way To Unlink A Slide From Its Clip
**Symptom:** `coursecraft slides update <id> --clip ""` -- the same unlink syntax fixed for demos in Known Issue #22 -- had no supported way to clear a slide's clip relationship; the command only supported re-parenting to a new, non-empty clip record ID.
**Cause:** `coursecraft_cli/commands/slides.py`'s `update_slide` had the identical one-directional shape flagged as a follow-up in Known Issue #22: it unconditionally wrapped any non-`None` `--clip` value as a one-element list -- `fields["Clip"] = [clip]` -- so `--clip ""` would send `[""]` (a linked-record array containing an empty-string record ID) instead of `[]`, which Airtable's API rejects as an invalid record ID with the same 422 error demos hit.
**Fix:** Changed the `--clip` handling in `update_slide` to `fields["Clip"] = [clip] if clip else []`, matching the demos.py fix from Known Issue #22 exactly. Updated the `--clip` option help text and the command's example list to document `--clip ""` as the unlink syntax.
**Verification:** Added `test_update_slide_accepts_clip_reparent`, `test_update_slide_accepts_clip_unlink`, and `test_update_slide_help_lists_clip_option` to `tests/test_slides_update.py`, asserting a non-empty `--clip` still sends `{"Clip": [<id>]}` and `--clip ""` sends `{"Clip": []}`. Ran `uv run --with pytest python -m pytest tests/test_slides_update.py -v` (20 passed) and the full suite `uv run --with pytest python -m pytest tests/` (366 passed, up from 363). Reinstalled with `uv tool install -e /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --force --refresh` and confirmed `coursecraft slides update --help` shows the updated `--clip` help text and the new unlink example. No live Airtable slide was unlinked to verify this fix -- unlike Known Issue #22, no real record currently needs unlinking, and unlinking a live slide's clip is a content-modifying action on real course data that should not be performed just to prove a CLI fix; the unit-test coverage mirrors the exact code path (`fields["Clip"] = [clip] if clip else []`) that Known Issue #22 verified live for demos.
**Recurrence Prevention:** When a bug is fixed in one resource command (e.g. `demos.py`), grep sibling resource commands (`slides.py`, `clips.py`, `modules.py`, `courses.py`) for the same shape before closing the issue -- a fix documented as "just here" often applies verbatim elsewhere. Known Issue #22 explicitly flagged this file as unchecked; that follow-up note is what caught this gap.

### 24. Approval Flags Survived In-Place Rewrites Of The Field They Approve
**Symptom:** A slide's `Script` was rewritten by an agent while `Script Human Verified` stayed `true`, so the record advertised Adam's approval of text he had never seen and sat at `Ready to Build`. The same shape existed for every other content-field/approval-field pair: Slides `Template` + `Slide Type Human Verified`; Demos `Demo Overview`/`Environment Spec`/`Action Summary`/`Script` each paired with their own `... Review (AI)` and `... Human Verified` fields; Modules `Learning Objectives`/`Description` + `Module Plan Complete`/`Module Review Complete`/`Plan Review (AI)`; Modules `Slide Deck Hash` + `PowerPoint Deck Human Verified`/`PowerPoint Deck Review (AI)`. A separate latent bug in the existing Demos `AI Tested` invalidation made it worse: resubmitting the *identical* existing content still forced `AI Tested` to `False`.
**Cause:** `update_slide`/`update_demo`/`update_module` wrote a changed content field without ever touching the approval field(s) that vouch for it; nothing enforced that an approval must be re-earned after the approved text changes. The existing `AI Tested` invalidation in `update_demo` compounded this by treating "a value was passed" as "the value changed," so even a no-op resubmission cleared it.
**Fix:** Each `update_*` command now compares an incoming content value (`.strip()`-normalized) against the record's currently persisted value before writing. A REAL difference auto-clears the paired approval field(s) in the same write: Slides `--script`→`Script Human Verified`; Slides `--template`/`--clear-template`→`Slide Type Human Verified`; Demos `--demo-overview`/`--environment-spec`/`--action-summary`/`--script`→that field's own `... Review (AI)` (cleared to `""`) and `... Human Verified` (cleared to `False`); Modules `--learning-objectives`/`--description`→`Module Plan Complete`, `Module Review Complete`, `Plan Review (AI)`; Modules `--slide-deck-hash`→`PowerPoint Deck Human Verified`, `PowerPoint Deck Review (AI)`. A no-op resubmission (identical content) never clears anything. Passing an explicit review/verified flag value in the SAME call as a real content change is rejected (`typer.Exit(1)`) -- verification must be a deliberate, separate call after the content change is in place, mirroring the pre-existing `--ai-tested` mutual-exclusion guard. Also fixed `update_demo`'s `design_content_changed` to require an actual difference, not just "a value was passed," so a no-op resubmission no longer clears `AI Tested` either. This was deliberately built in the CLI write path (not an Airtable formula/automation, not a post-hoc validator) because this CLI is CourseCraft's sole database write path -- enforcing it here closes the gap for every calling agent/runtime at once, with no reliance on an agent remembering to self-report a stale flag.
**Verification:** Added 20 new unit tests across `tests/test_slides_update.py`, `tests/test_demos_update.py`, `tests/test_modules_update.py` (content-change clears, no-op-doesn't-clear, explicit-flag-respected-on-no-op, reject-on-differing-content-plus-explicit-flag) plus fixed stale pre-existing test expectations in those files and `tests/test_voice_recording_invalidation.py`. Full suite `uv run --with pytest python -m pytest tests/` -- 386 passed (up from 366). Reinstalled with `uv tool install -e /Users/adam/Dropbox/GitRepos/cli-tools/_personal/coursecraft --force --refresh`; `coursecraft slides update --help`, `coursecraft demos update --help`, `coursecraft modules update --help` all confirmed to document the new auto-clear behavior.
**Recurrence Prevention:** Clips' `Recording Human Verified` and Courses' `Scaffolding Review (AI)` were deliberately left alone: neither pairs with a CLI-writable content field on the same record (the recording is produced by a separate registration pipeline that explicitly forbids touching `Recording Human Verified`; scaffolding isn't a record field at all), so there is no in-place-rewrite path for the CLI to guard. When a new content field gains a paired `... Human Verified` or `... Review (AI)` field in Airtable, add the same compare-before-write + guard pattern to its `update_*` command in the same change that adds the field's write support -- do not leave it to a skill/prose reminder for agents to self-police.

## Domain Knowledge

### Course Artifact Paths and Module Deletion
**Context:** Relevant when answering whether CourseCraft can locate MP4 clip exports, slide deck files, or generated narration files, and when deleting modules or courses.
**Key Facts:** `coursecraft modules delete --cascade` and `coursecraft courses delete --cascade` delete Airtable records only; they do not remove MP4, PPTX, demo, or narration files. `coursecraft descript export` is the only command with a built-in course artifact root: `/Users/adam/Library/CloudStorage/GoogleDrive-adbertram@gmail.com/My Drive/Adam the Automator/CourseWork/courses/<course-slug>/clips/m<module>c<clip>.mp4`. `coursecraft voice-recordings generate` requires explicit `--output-dir`; slide narration is written under `<output-dir>/m<module number>/slides/<slide number> - <slide title>.mp3`, demo narration under `<output-dir>/demos/`, and the path is stored in `Voice Recording Path`. The CLI does not store clip MP4 paths or PowerPoint deck paths on standard CourseCraft records.
**Gotchas:** In project-scoped course repos, do not rely on CourseCraft global active course when deriving artifact paths; resolve the Course ID slug for the selected course and pass `--course` where supported. For filesystem cleanup, derive paths separately and verify files before deleting.

### Projected Dot-Notation Fields Are Flat Keys
**Context:** Relevant when using `--properties` with Airtable-shaped records and then piping the JSON to `jq`.
**Key Facts:** `--properties "id,fields.Name,fields.Status"` uses the shared cli-tools projection helper. Dot notation selects the nested value, but the projected JSON stores it under the original flat key, for example `"fields.Name"`, not under a nested `fields` object. A single-record `get` result is an object, so read it with `jq '.["fields.Name"]'`; `jq '.fields.Name'` returns null because `fields` is absent after projection. A `list` result is an array, so read its first projected record with `jq '.[0]["fields.Name"]'`. For example, `coursecraft --no-cache slides get <record-id> --properties "id,fields.Name" | jq -r '[.id, .["fields.Name"]] | @tsv'` returns both values. Every requested property key is ALWAYS present in the projected record: a requested field that is empty or absent on the record projects as an explicit `null` (the key is never silently dropped), so a `null` under a flat key such as `"fields.Status"` means that field is genuinely empty/unset — it does NOT mean the property was not requested. Do not infer "field missing" from a vanished key. The "null means empty" guarantee holds only for REAL field names: a misspelled or nonexistent field name ALSO projects an explicit `null` — the projector cannot tell a wrong key from an empty field. Confirmed live 2026-07-19: `--properties "fields.Slide Template"` projected `null` on slide `recvOAtzRVnNqv5ok` while the real `fields.Template` held a linked record id.
**Gotchas:** If downstream code needs normal Airtable shape such as `.fields.Name` or `.fields["Demo Overview"]`, do not use `--properties`; fetch the full record or full list and project with `jq` afterward. Before treating a projected `null` as proof a field is empty, verify the field name against `field_mappings.py`; when the same field projects `null` across every record in a set (a blanket absence), suspect the field name and confirm with a full unprojected `get` on one record.

### Unchecked Checkbox Fields Are Absent, Never `false`
**Context:** Relevant whenever a caller (human, script, or an LLM agent such as `coursecraft-explore`) reads or reports the value of any Airtable checkbox field — every `*Human Verified`, `Feedback Requested`, `Recording Review (Human)`, and similar gate/boolean field across every table.
**Key Facts:** Airtable's API omits an unchecked checkbox field from `fields` entirely — it never returns `false`. A full, unprojected `coursecraft <group> get <id>` (no `--properties`) on a record with several checkbox fields will therefore show only the CHECKED ones (`"Demo Overview Human Verified": true`) and silently have no key at all for the unchecked ones (`Action Summary Human Verified` absent = unchecked). Reading a large unprojected record and eyeballing for a specific boolean key's presence is unreliable — an absent key surrounded by several `true` sibling fields (e.g. three different `*Human Verified` fields on one Demo record) is easy to misread as "must also be true" by pattern-matching the surrounding fields instead of checking literally. Confirmed live 2026-07-07 against demo `recayQxum1knKY7pZ`: `Action Summary Human Verified` is absent from a full `get`.
**Gotchas:** To reliably check a checkbox/gate field's value, request it explicitly with `--properties "fields.<Checkbox Field Name>"` (or as one field in a larger `--properties` list) rather than reading a full unprojected record — the projector always emits an explicit `null` for an absent/unchecked field (see "Projected Dot-Notation Fields Are Flat Keys" above), which cannot be missed or pattern-matched away. Never infer or assume a checkbox's value from sibling fields, surrounding context, or "it looks like this step should be done by now" — an absent key means unchecked/empty, full stop, and must be reported as such.

### `--filter` Booleans Are Words; `1`/`0` Are Numbers
**Context:** Relevant to every `coursecraft <group> list --filter "field:op:value"` that targets a checkbox/gate field or a numeric field (`clip_order`, `order`, `target_length`, `voice_character_count`, `deck_number`).
**Key Facts:** Boolean detection in `coursecraft_cli/filter_translator.py` fires only on the spelled-out words `true`/`false`/`yes`/`no`, which become `TRUE()`/`FALSE()`. Every other value is emitted as a quoted literal, and Airtable coerces a quoted numeric literal to a number when the field is numeric — so ordering is identical either way (live on Slides: `{Clip Order}>'9'` and `{Clip Order}>9` both return the single Clip Order 10 row). Equality is NOT identical: Airtable coerces a blank numeric cell to 0, so an unquoted `{Field}=0` matches every blank row while `{Field}='0'` matches only a real zero. Confirmed live 2026-07-19 on base `app9uzzru5KZOImYQ`: `{Voice Character Count}=0` returned all 155 Slides rows (every one blank), `{Voice Character Count}='0'` returned 0. Until this was fixed, `1`/`0` were also read as booleans, so `clip_order:eq:0` emitted `{Clip Order}=FALSE()` and silently matched blanks.
**Gotchas:** Use `built:eq:false`, not `built:eq:0`, to find unchecked rows — Airtable stores an unchecked box as blank, so only `FALSE()` matches it (live: `{Built}=FALSE()` → 32, `{Built}='0'` → 0). `built:eq:1` and `built:eq:true` are both fine for checked rows (both → 123). A field-type map was deliberately not added to `field_mappings.py`: `Slides.Designed` is an Airtable `formula` field that filters like a checkbox, so name/appearance-based type inference is unreliable and a hand-maintained type map would drift from the live schema.

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
