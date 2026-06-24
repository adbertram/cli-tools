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
| `coursecraft courses list --active` | Get the active course |
| `coursecraft modules list --course <slug> --table` | List modules for a course |
| `coursecraft clips show M1C2 --course <slug>` | Show clip hierarchy tree |
| `coursecraft demos list --module <recID> --table` | List demos in a module |
| `coursecraft slides update <recID> --script "..."` | Update slide script |
| `coursecraft course-outlines read -l <doc-id>` | Read outline from Google Doc |
| `coursecraft courses get <slug> --include-clips` | Get course with nested clips |
| `coursecraft voice-recordings generate --slide <recID> --voice-id <voice> --model-id eleven_multilingual_v2 --output-format <format> --output-dir <dir>` | Generate slide narration audio |
| `coursecraft descript export "Project" -m 2 -c 1` | Export Descript composition |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `coursecraft` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `coursecraft --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication management via Airtable PAT delegation
- **cache** -- Local response cache management
- **courses** -- CRUD for course records with nested creation and --active/--include-modules/--include-clips support
- **course-outlines** -- Read and update course outline Google Docs, sync to database
- **modules** -- CRUD for module records with batch clip creation and ASCII tree display via show
- **clips** -- CRUD for clip records with batch creation and M1C1/M2C3 shorthand support
- **demos** -- CRUD for demo records with hierarchical filtering (--clip, --module, --course)
- **slides** -- CRUD for slide records with hierarchical filtering and build-instructions/script fields
- **slide-templates** -- Manage PowerPoint slide template definitions with --platform filtering
- **demo-build-products** -- Manage demo build product type definitions with XML sync
- **slide-build-products** -- Manage slide build product type definitions with XML sync
- **voice-recordings** -- Generate slide and demo narration audio with ElevenLabs and store recording metadata
- **descript** -- Export video clips from Descript projects to course folders
</principle>
</essential_principles>

<principle name="Voice Recording State">
`coursecraft voice-recordings generate --slide ...` and `coursecraft voice-recordings generate --demo ...` are only for workflows that need separate generated narration before video capture. They strip non-spoken recording cues, apply packaged regex pronunciation transforms from `coursecraft_cli/voice_pronunciation_patterns.json` and `coursecraft_cli/voice_pronunciation_tokens.json` for dynamic code-shaped text, sync alias rules from `coursecraft_cli/voice_pronunciations.json` into the ElevenLabs pronunciation dictionary named `CourseCraft Voice Pronunciations`, pass that dictionary locator to `elevenlabs speech create`, store generated audio metadata, and set `Dictation Recorded` to true. The regex transforms normalize common code shapes such as PowerShell cmdlets, parameters, variables, dotted module names, Windows paths, file names, pipes, and `%` aliases; static course terms stay in the source text and are handled by the ElevenLabs dictionary. They never set `Recorded`, because final recording also requires the video portion. If video and audio will be recorded together, skip voice recording generation and leave `Dictation Recorded` unset. Slide audio must be written to `<output-dir>/m<module number>/slides/<slide number> - <slide title>.mp3`; demo audio is written under `<output-dir>/demos/`.
The CLI defaults to `eleven_multilingual_v2` because CourseCraft narration uses a Professional Voice Clone and Eleven v3 does not currently support PVCs. Legacy tuning flags such as `--style` and `--speaker-boost` are not passed by default; provide tuning flags only after validating the selected ElevenLabs model supports them.
</principle>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`coursecraft --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

## Known Issues

### 1. Demo Build Product Direct Requirements Were Not Synced
**Symptom:** `coursecraft demo-build-products sync --file <xml>` created or updated a record with `Name` and `Description`, but omitted `Requirements` when the XML used direct `<requirements><item>...</item></requirements>` entries.
**Cause:** The demo build-product parser only read `<requirements><section>...</section></requirements>` structures, while slide build-product sync already supported both sectioned and direct item requirements.
**Fix:** `coursecraft_cli/commands/demo_build_products.py` now supports direct requirement items and sectioned requirement items.
**Verification:** Run `python3 -m pytest tests/test_demo_build_products_parse.py` and resync the affected demo XML file, then verify the record includes the `Requirements` field.
**Recurrence Prevention:** When adding new demo build-product XML shapes, add or update parser tests before syncing records to Airtable.

### 2. VM Acronym Pronunciation Creates Bad TTS Output
**Symptom:** ElevenLabs generated an unnatural pause between the V and M when slide narration said `VMs`. The first attempted fix, `vee ems`, produced audio that sounded like `V E M`.
**Cause:** The CourseCraft voice pronunciation data expanded `VMs` to acronym-like or phonetic spellings that the TTS engine still interpreted as separated letters.
**Fix:** Store prose `VMs`/`VM` as alias rules in `coursecraft_cli/voice_pronunciations.json`, let `coursecraft voice-recordings generate` sync the `CourseCraft Voice Pronunciations` dictionary, and keep identifier token `VM` as `virtual machine` for code-shaped text.
**Verification:** Run `python3 -m pytest tests/test_voice_recordings.py`, then regenerate a slide containing `VMs` with `coursecraft voice-recordings generate` and verify `elevenlabs speech create` receives the `CourseCraft Voice Pronunciations` dictionary locator.
**Recurrence Prevention:** Prefer plain-English expansions for acronyms when TTS pacing is rejected; do not use phonetic spellings such as `vee ems` unless a generated audio sample has been accepted.

### 3. Idempotent Pronunciation Requires A Tight Alias
**Symptom:** ElevenLabs paused and slowed down when slide narration said `idempotent` as `eye dem poh tent`. Passing the raw word through produced audio that sounded like `eedempotent`. The spaced alias `I dim po tent` still produced brief pauses between syllables.
**Cause:** The CourseCraft voice workflow uses pronunciation dictionaries for recurring terms; per the ElevenLabs skill guidance, deterministic pronunciation problems should be handled with alias pronunciation dictionary rules unless phoneme support is documented for the selected model.
**Fix:** Store `idempotent` as the single-token alias `Idimpohtent` in `coursecraft_cli/voice_pronunciations.json`.
**Verification:** Run `python3 -m pytest tests/test_voice_recordings.py`, then regenerate a slide containing `idempotent` with `coursecraft voice-recordings generate` and verify `elevenlabs speech create` receives the synced pronunciation dictionary locator.
**Recurrence Prevention:** For rejected pronunciations, remove spaces from alias spellings when the accepted pronunciation must read as one word, then test the normalized source text before regenerating audio.

### 4. Sysadmins Pronunciation Must Stay Raw Unless Full-Slide Audio Proves Otherwise
**Symptom:** ElevenLabs mispronounced `PowerShell for Sysadmins` in the full Technical Prerequisites slide when dictionary aliases forced `sisadmins`; the generated audio sounded like `CS Admins`. Earlier spaced aliases such as `sis admins` and `sys admins` also produced separated-letter or paused pronunciations.
**Cause:** The production voice and `eleven_multilingual_v2` handled raw `Sysadmins` correctly in the accepted full-slide sample, while custom aliases changed model behavior in surrounding sentence context.
**Fix:** Do not store `PowerShell for Sysadmins`, `sysadmins`, `Sysadmins`, or `SysAdmins` in `coursecraft_cli/voice_pronunciations.json`. Let those terms pass through raw source text; the voice-recordings command should sync the shared dictionary without any sysadmins-specific rules.
**Verification:** Run `python3 -m pytest tests/test_voice_recordings.py`, sync the `CourseCraft Voice Pronunciations` dictionary, regenerate the Technical Prerequisites slide with the production voice/model/settings, then transcribe it with `whisper transcripts create` and confirm the opening says `PowerShell for sysadmins`.
**Recurrence Prevention:** Do not add sysadmins pronunciation aliases based on spelling intuition or short isolated samples. Only add a future sysadmins rule after a blind, full-slide production-voice sample is accepted and the official regenerated slide transcribes correctly.

### 5. Cache Clear Requires Config Storage Directory
**Symptom:** `coursecraft cache clear` failed with `Error: 'Config' object has no attribute 'storage_dir'`.
**Cause:** CourseCraft registered the shared `cli_tools_common.cache_commands.create_cache_app`, which requires every tool config to expose a `storage_dir` property, but `coursecraft_cli.config.Config` only exposed `tool_dir` and profile helper methods.
**Fix:** Add `Config.storage_dir` returning `self.get_profile_data_dir()` in `coursecraft_cli/config.py`.
**Verification:** Run `python3 -m pytest tests/test_config.py`, `python3 -m pytest`, and `coursecraft cache clear`; the cache command should return JSON with `files_removed` and `bytes_freed`.
**Recurrence Prevention:** When registering shared `cli_tools_common` apps, verify the tool-specific config implements the properties required by that shared app and add a focused config test.

### 6. Script Updates Must Clear All Voice Metadata
**Symptom:** A slide or demo can show `Voice Generated At` after its `Script` changes even though `Voice Recording Path`, model metadata, and `Dictation Recorded` were cleared. The record then looks partially generated and blocks slide recording preflight.
**Cause:** `coursecraft_cli/voice_recording_fields.py` invalidated generated voice fields after script edits but did not clear `Voice Character Count` or `Voice Generated At`.
**Fix:** Include `Voice Character Count` and `Voice Generated At` in `get_voice_recording_invalidation_fields()`, then regenerate narration with `coursecraft voice-recordings generate` for any records that were already invalidated.
**Verification:** Run `python3 -m pytest tests/test_voice_recording_invalidation.py tests/test_voice_recordings.py tests/test_slides_update.py tests/test_demos_update.py tests/test_config.py`, then verify affected records with `coursecraft --no-cache slides list --module <module-id> --properties "id,fields.Name,fields.Voice Recording Path,fields.Dictation Recorded,fields.Voice Generated At"`.
**Recurrence Prevention:** When adding new generated voice metadata fields, update the invalidation helper and `tests/test_voice_recording_invalidation.py` in the same change.

### 7. Slide Recordings Need A Final Recorded CLI Flag
**Symptom:** After a successful slide MP4 recording, CourseCraft slide records could be marked `Dictation Recorded` but not final `Recorded` through the `coursecraft slides update` command.
**Cause:** Demo updates exposed `--recorded`, but slide updates only exposed `--dictation-recorded`, leaving the final slide recording state without a supported CLI path.
**Fix:** Add `coursecraft slides update <record-id> --recorded` so the command writes `Recorded=true`.
**Verification:** Run `python3 -m pytest tests/test_slides_update.py -q`, `python3 -m pytest`, `coursecraft slides update --help`, and verify live records with `coursecraft --no-cache slides list --module <module-id> --properties "id,fields.Name,fields.Recorded,fields.Dictation Recorded,fields.Status"`.
**Recurrence Prevention:** Keep separate flags for dictation audio and final video recording. Generated narration uses `--dictation-recorded`; completed slide videos use `--recorded`.

### 8. Clip Update Boolean Flags Must Count Toward The Empty-Payload Guard
**Symptom:** `coursecraft clips update <record-id> --brainstorming-outline-fact-checked` (the flag passed as the only argument) failed with `No fields to update. Provide at least one field option.`, even though `coursecraft modules update <record-id> --brainstorming-outline-fact-checked` accepts the same standalone flag. Agents worked around it by re-passing the clip's entire existing `Brainstorming Outline` text alongside the flag, which risks content drift. That workaround is no longer needed -- the standalone flag now works.
**Cause:** In `coursecraft_cli/commands/clips.py` `update_clip`, the `if not fields:` empty-payload guard ran BEFORE the boolean-flag assignments (`brainstorming_outline_fact_checked` was applied after the guard, along with the fact-check auto-reset). So when only that boolean flag was passed, `fields` was still empty at the guard and the command exited. `modules.py` `update_module` already placed its guard AFTER all boolean flags, so module updates counted booleans correctly.
**Fix:** Move the `if not fields:` guard in `coursecraft_cli/commands/clips.py` to AFTER every field assignment, including the fact-check auto-reset and the explicit `--brainstorming-outline-fact-checked` flag, mirroring `modules.py`. The guard is kept (an update with truly no fields still errors); booleans now count as a valid lone update. Note there is no `--no-brainstorming-outline-fact-checked` form: the param is `Optional[bool] = None`, so only the positive flag exists (it sets the value to true).
**Verification:** `python3 -m pytest tests/test_clips_update.py -q` (includes `test_update_clip_accepts_only_brainstorming_outline_fact_checked`), then `python3 -m pytest`. Live: read `fields["Brainstorming Outline Fact Checked"]` with `coursecraft clips get <id>`, run `coursecraft clips update <id> --brainstorming-outline-fact-checked` with no other args, confirm no "No fields to update" error and that the read-back is true.
**Recurrence Prevention:** Keep the empty-payload guard after ALL field assignments (text, numeric, and boolean) in every `update` command, and keep explicit user-provided fact-check flags after automatic invalidation logic so the explicit command wins. Boolean/flag fields must count toward "has updates."

### 9. Slide Template Version Must Be CLI-Writable
**Symptom:** `build_module_deck.py` rejects slides with `template version invalid: None` when the linked slide template lacks `Template Deck Version`, and `coursecraft slide-templates update` cannot repair the template if it has no `--template-deck-version` flag.
**Cause:** The slide-template create/update commands did not expose the Airtable `Template Deck Version` field even though the PowerPoint deck builder hard-gates on `2025.2`.
**Fix:** Add `--template-deck-version` to `coursecraft_cli/commands/slide_templates.py` create and update paths so template records can be corrected through the CLI.
**Verification:** Run `python3 -m pytest tests/test_slide_templates_requirements.py -q`, `python3 -m pytest`, then verify the live template with `coursecraft --no-cache slide-templates get <template-record-id> --properties "id,fields.Name,fields.Template Deck Version"`.
**Recurrence Prevention:** When a builder depends on a template metadata field, expose that field through the template CLI before editing Airtable records.

### 10. Demo Approval Field Name Is `Tested and Approved`
**Symptom:** Checking `fields.Tested Approved` after `coursecraft demos update <id> --tested-approved` returns null and makes a successful update look like a failed persistence operation.
**Cause:** The Airtable field name includes `and`: `Tested and Approved`.
**Fix:** The `--tested-approved` update flag writes `Tested and Approved=true`.
**Verification:** Run `python3 -m pytest tests/test_demos_update.py -q`, then verify live records with `coursecraft demos get <demo-record-id> --properties "id,fields.Name,fields.Tested and Approved"`.
**Recurrence Prevention:** Use exact Airtable field names in JSON reads. For demo approval checks, always read `fields["Tested and Approved"]`.

### 11. Single Demo Reads Support `--properties`
**Symptom:** `coursecraft demos get <id> --properties ...` failed even though list commands support field projection.
**Cause:** `demos get` did not expose the shared properties filter.
**Fix:** Add `--properties/-p` to `coursecraft_cli/commands/demos.py` get path and apply `apply_properties_filter([record], properties)[0]` for JSON output.
**Verification:** Run `python3 -m pytest tests/test_demos_update.py -q` and `coursecraft demos get --help`.
**Recurrence Prevention:** When a resource list command supports `--properties`, keep its single-record get command in parity unless table output intentionally needs the full record.

### 12. Single Clip Reads Support `--properties`
**Symptom:** `coursecraft clips get <id> --properties ...` failed even though `clips list` and `demos get` supported field projection.
**Cause:** `clips get` did not expose the shared properties filter.
**Fix:** Add `--properties/-p` to `coursecraft_cli/commands/clips.py` get path and apply `apply_properties_filter([record], properties)[0]` for JSON output.
**Verification:** Run `python3 -m pytest tests/test_clips_update.py -q`, `coursecraft clips get --help`, and a live read such as `coursecraft --no-cache clips get <clip-id> --properties "id,fields.Name,fields.Status"`.
**Recurrence Prevention:** Keep every single-record `get` command in parity with the shared output-field-selection contract unless table output intentionally needs the full record.

### 13. Single Course and Module Reads Support `--properties`
**Symptom:** `coursecraft courses get <id-or-slug> --properties ...` and `coursecraft modules get <id> --properties ...` failed even though their list commands and the clips/demos get commands supported field projection.
**Cause:** `courses get` and `modules get` did not expose the shared properties filter.
**Fix:** Add `--properties/-p` to `coursecraft_cli/commands/courses.py` and `coursecraft_cli/commands/modules.py` get paths and apply `apply_properties_filter([record], properties)[0]` for JSON output.
**Verification:** Run `python3 -m pytest tests/test_courses_update.py tests/test_modules_get.py -q`, `coursecraft courses get --help`, `coursecraft modules get --help`, and live reads such as `coursecraft --no-cache courses get <course-id-or-slug> --properties "id,fields.Name,fields.Status"` and `coursecraft --no-cache modules get <module-id> --properties "id,fields.Name,fields.Status"`.
**Recurrence Prevention:** Keep `get --properties` parity across every resource whose `list` command supports field projection.

### 14. Intermittent `airtable CLI is not installed or not in PATH` Is A False Positive
**Symptom:** `python3 scripts/validate_build_product.py content-slide <recId>` (or any `coursecraft <res> get/list/update`) intermittently failed ONE record/call with `Error: airtable CLI is not installed or not in PATH. Install it with scripts/install-cli-tool.sh airtable from the cli-tools repo root.` Re-running the identical command immediately succeeded (`ok:true`). `which airtable` returned `/Users/adam/.local/bin/airtable` (exit 0) the entire time -- the binary was always present. Most reproducible under batch contention (e.g. several slide validations at once): one failed while the rest passed.
**Cause:** `CourseCraftClient.__init__` gated on `_check_airtable_cli()`, which spawned `airtable --version` with a 5s timeout (`AIRTABLE_CLI_VERSION_TIMEOUT_SECONDS`) and treated `subprocess.TimeoutExpired` as "binary missing". `airtable` is a uv-tool CLI whose launcher cold-starts a fresh Python interpreter (~0.23s warm). Under concurrent cold-cache load -- the validator spawns `coursecraft` (interpreter cold start) which spawns `airtable --version` (another cold start) plus the real `airtable records get` -- that `--version` probe could exceed 5s and be misreported as "not installed". It was never a PATH problem (PATH always contained `~/.local/bin`); it was a timeout false negative on a heavy startup probe.
**Fix:** Replaced the subprocess `--version` probe with a pure PATH lookup. `coursecraft_cli/client.py` now has module-level `_resolve_airtable_binary()` using `shutil.which("airtable", path=...)` (with `~/.local/bin` forced onto the search path); `_check_airtable_cli()` returns `_resolve_airtable_binary() is not None`. A PATH lookup never starts a process and never times out, so a present-on-PATH binary can never yield the false "not installed". Any genuinely transient runtime failure now surfaces later with the real airtable stderr via `_run_airtable_command` (`airtable CLI error: <stderr>`), not the misleading install hint. Removed the now-unused `AIRTABLE_CLI_VERSION_TIMEOUT_SECONDS` constant.
**Verification:** `tests/test_client_airtable_detection.py` (availability check spawns no subprocess; a timing-out `--version` no longer false-negatives; a genuinely missing binary still raises the clear install error; `_resolve_airtable_binary` finds `~/.local/bin/airtable` even when PATH omits it, and returns None when absent). Full suite `python3 -m pytest tests/` -> 144 passed. Ran `python3 scripts/validate_build_product.py content-slide recvSkOmGovjeG3sn` 22x (10 serial + 12 concurrent) with zero false "not installed" and every `slide_script.record_read` passing.
**Recurrence Prevention:** Never gate availability on a process-spawning probe (`<tool> --version`) with a short timeout -- a slow interpreter cold start under load reads as "missing". Use `shutil.which` for "is the binary on PATH" checks. If an "airtable not installed" error ever appears while `which airtable` exits 0, treat it as a transient/false positive and surface the real downstream stderr rather than the install hint.

### 15. Datetime Write Verification Is A False Positive Across `+00:00` vs `.000Z`
**Symptom:** A `coursecraft <res> create/update` (or `coursecraft feedback create`) that writes a dateTime field (e.g. `Feedback Requested At`, the `Feedback` table `Timestamp`) raised `WriteVerificationError` — `sent '2026-06-20T19:05:00+00:00', persisted '2026-06-20T19:05:00.000Z'` — even though the row persisted intact (reproduced on Feedback row `reckVbS58RCw2C3Wn`). Re-reading the record showed the value was correctly stored; only the post-write verification failed.
**Cause:** `CourseCraftClient._persisted_value_matches` compared scalar values as literal strings (plus the existing trailing-newline and Markdown tolerances). Airtable persists dateTime fields in UTC as `...T...:00.000Z`, while callers send the equivalent `+00:00` offset form. Those two strings are unequal but denote the **same instant**, so verification wrongly reported a mismatch — the same class of false-positive as the older long-text trailing-newline bug, just for datetimes.
**Fix:** `coursecraft_cli/client.py` now adds `_parse_iso_datetime` (parses an ISO-8601 string, normalizing a trailing `Z` to `+00:00`, returns `None` for non-datetimes) and `_datetime_instants_match` (true only when both sides parse as datetimes AND refer to the same instant; aware datetimes compared via `timestamp()`, a naive-vs-aware mix rejected). `_persisted_value_matches` calls it after the trailing-whitespace branch and before the long-text normalization. A different instant, a naive-vs-aware mix, or any non-datetime scalar still mismatches, so verification is not weakened.
**Verification:** Smoke-checked against the installed module via the launcher shebang interpreter: `_persisted_value_matches("2026-06-20T19:05:00+00:00", "2026-06-20T19:05:00.000Z")` returns `True`; a one-minute-different datetime and a `-05:00` offset of the same wall-clock both return `False`; non-datetime text and `--typecast` number coercion still behave as before. (Per project policy no new test file was added.)
**Recurrence Prevention:** When verifying that a typed value persisted, compare by the value's semantic identity, not its string form. For datetimes that means comparing instants (tolerating offset vs `Z` and millisecond precision); for other coerced types prefer the canonical-form compare already used for numbers and long text. A bare string mismatch on a value Airtable is known to canonicalize is a verification bug, not a failed write.

## Domain Knowledge

### Course Artifact Paths and Module Deletion
**Context:** Relevant when answering whether CourseCraft can locate MP4 clip exports, slide deck files, or generated narration files, and when deleting modules or courses.
**Key Facts:** `coursecraft modules delete --cascade` and `coursecraft courses delete --cascade` delete Airtable records only; they do not remove MP4, PPTX, demo, or narration files. `coursecraft descript export` is the only command with a built-in course artifact root: `/Users/adam/Library/CloudStorage/GoogleDrive-adbertram@gmail.com/My Drive/Adam the Automator/CourseWork/courses/<course-slug>/clips/m<module>c<clip>.mp4`. `coursecraft voice-recordings generate` requires explicit `--output-dir`; slide narration is written under `<output-dir>/m<module number>/slides/<slide number> - <slide title>.mp3`, demo narration under `<output-dir>/demos/`, and the path is stored in `Voice Recording Path`. The CLI does not store clip MP4 paths or PowerPoint deck paths on standard CourseCraft records.
**Gotchas:** In project-scoped course repos, do not rely on CourseCraft global active course when deriving artifact paths; resolve the Course ID slug for the selected course and pass `--course` where supported. For filesystem cleanup, derive paths separately and verify files before deleting.

### Projected Dot-Notation Fields Are Flat Keys
**Context:** Relevant when using `--properties` with Airtable-shaped records and then piping the JSON to `jq`.
**Key Facts:** `--properties "id,fields.Name,fields.Status"` uses the shared cli-tools projection helper. Dot notation selects the nested value, but the projected JSON stores it under the original flat key, for example `"fields.Name"`, not under a nested `fields` object. A projected record should be read with `jq '.[0]["fields.Name"]'`; `jq '.[0].fields.Name'` returns null because `fields` is absent after projection. Every requested property key is ALWAYS present in the projected record: a requested field that is empty or absent on the record projects as an explicit `null` (the key is never silently dropped), so a `null` under a flat key such as `"fields.Status"` means that field is genuinely empty/unset — it does NOT mean the property was not requested. Do not infer "field missing" from a vanished key.
**Gotchas:** If downstream code needs normal Airtable shape such as `.fields.Name` or `.fields["Demo Overview"]`, do not use `--properties`; fetch the full record or full list and project with `jq` afterward.

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
