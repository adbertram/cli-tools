---
name: "coursecraft-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute coursecraft operations using the `coursecraft` CLI tool. CLI interface for CourseCraft content management -- courses, modules, clips, demos, slides, outlines, and voice recordings. Triggers: coursecraft, coursecraft cli, coursecraft courses, coursecraft modules, coursecraft clips, coursecraft demos, coursecraft slides, coursecraft voice recordings, list coursecraft courses, coursecraft outlines, course content management, update coursecraft, coursecraft records"
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
| `coursecraft --no-cache clips list --module <module-record-id> --properties "id,fields.Name,fields.Status,fields.Recording Human Verified"` | List a module's clips as fresh JSON with key status and human-review fields |
| `coursecraft clips show M1C2 --course <slug>` | Show clip hierarchy tree |
| `coursecraft demos list --module <recID> --table` | List demos in a module |
| `coursecraft slides update <recID> --script "..."` | Update slide script |
| `coursecraft course-outline read -l <doc-id>` | Read outline from Google Doc |
| `coursecraft courses get <slug> --include-clips` | Get course with nested clips |
| `coursecraft courses sync-requirements <slug>` | Sync linked Pluralsight requirements; no Deadline/child writes, with gated audit/state transitions during an objective-override exception |
| `coursecraft courses request-objective-correction <slug>` | Start the gated Pluralsight objective-correction exception after a current NEEDS REVISION review |
| `coursecraft courses mark-requirements-update-received <slug>` | Move an audited correction request to Update Received after Pluralsight returns it |
| `coursecraft courses submit-outline-for-review <slug>` | Submit or resubmit the exact current Course Outline revision |
| `coursecraft modules submit-slide-deck-for-review <module>` | Submit or resubmit the exact current Slide Deck revision |
| `coursecraft modules submit-videos-for-review <module>` | Submit or resubmit the exact current Module Video manifest |
| `coursecraft courses authorize-objective-override <slug>` | Authorize the initial override after requirements resync, or reauthorize an active override from a current downstream NEEDS REVISION outline review |
| `coursecraft courses apply-objective-override <slug> --learning-objectives-file <path> --reason <text>` | Write canonical objectives and append the authorized override provenance |
| `coursecraft versions reconcile --course <course> --artifact-slug <slug> --expected-version <v> --expected-old-ledger-sha <sha> --expected-live-content-sha <sha> --check` | Read-only safety check for one exact stale Course airtable-content ledger SHA recovery |
| `coursecraft feedback list --slide <recID>` | List Feedback rows linked to a slide; do not add --filter to linked feedback reads |
| `coursecraft feedback update <recID> --processing-status Applied --processed-at <iso>` | Stamp a Feedback row after processing |
| `coursecraft voice-recordings preview --demo <recID>` | Read-only normalized narration/hash and cue/anchor validation before generation |
| `coursecraft voice-recordings generate --demo <recID>` | Generate the authoritative demo narration take (voice/model/format/output come from the production contract; no overrides) |
</quick_start>

<principle name="Boolean Update Options Are Switches">
For any `usage.json` option with `"type": "bool"` and `"takes_value": false`,
pass the flag by itself; never append `true` or `false`. When the option also
has a `secondary` field, use the primary `name` to set the value and the
`secondary` flag to clear it. For example, set Course Outline Draft verification
with `--outline-draft-human-verified` and clear it with
`--no-outline-draft-human-verified`.
</principle>

<principle name="Version Ledger Reconciliation Is Exact And Fail-Closed">
Use `coursecraft versions reconcile` only to repair one stale SHA in an existing
Course-owned `airtable_content` Version Control entry. Always run the exact
command with `--check` first. The command requires the course, artifact slug,
version, current stale ledger SHA, and current persisted-content SHA; any drift
fails before a write. It preserves the target entry's `v` and `at`, every other
ledger entry, and the Course content/lifecycle/review fields, then verifies an
uncached readback. Omit `--check` only for the already-verified repair.
</principle>

<essential_principles>
<principle name="Pluralsight Objective Overrides Are A Gated Exception">
Never use generic `courses update --learning-objectives` for a Pluralsight course.
Use the dedicated state machine in order: `request-objective-correction`,
`mark-requirements-update-received`, `sync-requirements`, persist a fresh
post-feedback course.requirements review,
`authorize-objective-override`, then `apply-objective-override --reason ...`.

The commands fail closed against `Learning Objectives Override State` and the exact
`Reviewed-Version: course.requirements@vN sha256:<hash>` trailer. The audit field is a
schema-versioned JSON event document whose prior operational events are preserved on every
append. `mark-requirements-update-received` requires the exact `Correction Requested`
state plus its matching correction-request audit event, moves to `Update Received`, and
only then can `sync-requirements` resync and move to `Feedback Resynced`.
When the state is `Override Active`, later `sync-requirements` calls preserve the canonical
`Learning Objectives` override while syncing the remaining Curriculum fields.

If a later outline review finds an error in the active objectives, rerun
`authorize-objective-override` while the state is `Override Active`, then use
`apply-objective-override`. The authorization is bound to the current
`course.outline_draft` review/version and the current objective content; apply fails if
either changes. Generic `courses update` rejects both active-lifecycle objective edits and
post-gap-analysis Carry-Forward Plan edits.
</principle>
<principle name="External Reviews Use Dedicated Lifecycle Commands">
Do not write the Pluralsight review state or submitted-revision fields through generic update
commands. Course Outline uses `submit-outline-for-review`,
`mark-outline-changes-requested`, and `mark-outline-approved`. Slide Deck uses
`submit-slide-deck-for-review`, `mark-slide-deck-changes-requested`, and
`mark-slide-deck-approved`. Module Video uses `submit-videos-for-review` and
`mark-videos-approved`; the feedback-ingest workflow owns the internal
`mark-video-changes-requested` action.

The hidden `accept-approved-slide-deck` action belongs only to the approved-deck release
workflow. That workflow supplies explicit approval evidence and atomically registers the
canonical returned deck, replaces submitted revision evidence, enters `Approved`, and
invalidates AI/human deck-review gates. Do not call it as an operator approval shortcut.
</principle>
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
`coursecraft feedback list` has two mutually exclusive filter paths. Use exactly one hierarchical link option (`--demo`, `--slide`, `--clip`, `--module`, or `--course`) to fetch Feedback rows linked to a specific record, OR use `--filter` for a field predicate across Feedback rows. Filter predicates use the lowercase snake_case Feedback field keys, not Airtable display labels: for example, `--filter "patterns_learned:contains:course requirements"`; `patterns learned:...` is invalid. Do not combine `--filter` with any hierarchical link option. The exact CLI error is `Cannot use --filter with --demo, --slide, --clip, --module, or --course`. When both constraints are needed, fetch by the hierarchical link option and apply the extra predicate with `jq` against the returned JSON.
</principle>

<principle name="Update Output Is Not Readback JSON">
`coursecraft <group> update ...` stdout contains identifier data only, never the updated Airtable record. `coursecraft courses update ...` and `coursecraft demos update ...` emit the record ID as a JSON string, while human status output such as `Updated course: <record-id>` goes to stderr. A JSON parser can validate or extract that scalar ID, but it must not treat the value as record readback. After any update, verify through the canonical read path: run the matching `get` command for the same record ID, save that JSON if you need an evidence file, and parse the `get` output.

If a mutating `coursecraft <group> update ...` command times out with `airtable CLI command timed out after 45s`, the write state is unknown. Do not rerun the mutation blindly. First read the same record with the matching `coursecraft <group> get <record-id>` command and compare the intended field; retry only when that read-back proves the value did not persist.
</principle>

<principle name="Feedback Remediation Claims Are Fail-Closed">
`coursecraft feedback update` accepts a repeatable `--remediation-claim`. It is REQUIRED whenever `--processing-status Applied` is passed together with `--remediation`; omitting it in that combination exits non-zero and writes nothing (`--processing-status Applied with --remediation requires at least one --remediation-claim`). This exists because an `Applied` stamp is an assertion that remediation work actually happened, and free-prose `--remediation` text alone cannot prove it -- see Known Issue #27.

Two claim forms, both verified against live state before ANY field is written:
- `check:<dotted.check.id>` -- the id must be declared as an `id` in a `checks.json` under the CourseCraft skills tree (`.agents/skills`, resolved via `COURSECRAFT_PROJECT_ROOT` or the known repo path), and that contract must be reported reachable by `.agents/skills/course-pipeline/tools/check_validation_coverage.py --json`. If that gate's JSON has no top-level `unreachable` key, reachability is UNVERIFIABLE and the claim fails closed rather than silently passing.
- `record:<recordId>:<Field>=<expected>` -- the live record (read through the CLI's own uncached read path, searched across Slides/Demos/Clips/Modules/Courses/Feedback/Slide Templates) must have `<Field>` equal to `<expected>` as trimmed strings. Use `record:<recordId>:<Field>~=<substring>` instead for a long-text field where an exact match is impractical -- that form checks containment.

Any claim that fails to verify aborts the whole command with exit 1 and writes NOTHING -- no partial update, no warn-and-continue. The error names the exact claim and what was actually found (e.g. the real field value vs. the claimed one, or the check id search that came up empty).

Example:
```
coursecraft feedback update recXXX --processing-status Applied --processed-at "2026-07-25T12:00:00+00:00" \
    --remediation "Rewrote the slide's opening line and added the missing AI check." \
    --remediation-claim "check:slide.demo_intro.script.no_action_cues" \
    --remediation-claim "record:recSLIDEID:Script~=the concrete replacement phrase"
```
</principle>

<principle name="Command Groups">
- **auth** -- Authentication management via Airtable PAT delegation
- **cache** -- Local response cache management
- **courses** -- CRUD for course records with nested creation and --active/--include-modules/--include-clips support
- **courses sync-requirements** -- parses the existing Course record's `Course Requirements Link` with the canonical outline parser, stores the document verbatim in `Course Requirements`, and updates the Pluralsight-owned Course attributes. It never requires or writes Deadline and never touches modules, clips, folders, or Slack fields. During the objective-override exception only, it appends the audit, advances `Update Received` to `Feedback Resynced`, clears the pre-feedback review, and preserves `Learning Objectives` once the state is `Override Active`. Use `courses mark-requirements-update-received` after `courses request-objective-correction`; generic `courses update` cannot drive this lifecycle. `courses scaffold` accepts optional `--deadline`; omitting it in either intake (`--base`) or ordinary scaffold mode leaves Deadline unchanged.
- **course-outline** -- Read and update course outline Google Docs, sync to database
- **modules** -- CRUD for module records with batch clip creation and ASCII tree display via show
- **clips** -- CRUD for clip records with batch creation and M1C1/M2C3 shorthand support
- **demos** -- CRUD for demo records with hierarchical filtering (--clip, --module, --course)
- **slides** -- CRUD for slide records with hierarchical filtering and build-instructions/script fields
- **slide-templates** -- Manage PowerPoint slide template definitions with --platform filtering
- **feedback** -- CRUD for CourseCraft Feedback rows with per-level link filters (`--demo`, `--slide`, `--clip`, `--module`, `--course`), `Processing Status`/`Patterns Learned`/`Processed At` writes, write verification, and fail-closed `--remediation-claim` verification for `Applied` stamps. This is the first-class path for Feedback-table I/O; do not use raw `airtable` for the Feedback table.
- **voice-recordings** -- Generate demo narration audio with ElevenLabs and store recording metadata (demos only; slides carry an instructor WAV take)
</principle>

<principle name="Legacy Import Update Intake">
`coursecraft courses scaffold --base <course>` still requires the base course's
computed Status to be `Complete`. The only exception is the explicit
`--legacy-import-base` flag for a published pre-CourseCraft Pluralsight predecessor.
That flag fails closed unless the base is Version 1, its Notes begin with the canonical
legacy-import marker and contain its canonical Pluralsight course-overview source,
it has Module and Clip records, every Clip ID has a unique `M#C#` prefix, and every
corresponding `<courses-root>/<base-slug>/clips/m#c#.mp4` file is regular and non-empty. Use
`--dry-run` first to read the `legacy_import_evidence` object without
creating a Course record or folder. Do not use `courses create` for this workflow;
the scaffold intake remains the single writer of Version, the `-vN` slug, and the
Base Course link. Ordinary duplicate-name protection remains unchanged.
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

`coursecraft voice-recordings generate --demo <recID>` is the only generation command; it exists for demos whose `Recording Dictation Method` is `Automatic Narration Generation`. Slides have no generated narration: a slide's narration is the instructor's WAV take at its derived take path, and `Dictation Recorded` is the only narration state a slide record carries. Demo generation strips non-spoken recording cues through the canonical Demo Script contract, applies packaged regex pronunciation transforms from `coursecraft_cli/voice_pronunciation_patterns.json` and `coursecraft_cli/voice_pronunciation_tokens.json` for dynamic code-shaped text, syncs alias rules from `coursecraft_cli/voice_pronunciations.json` into the ElevenLabs pronunciation dictionary named `CourseCraft Voice Pronunciations`, passes that dictionary locator to `elevenlabs speech create`, stores generated audio metadata, and sets `Dictation Recorded` to true. The regex transforms normalize common code shapes such as PowerShell cmdlets, parameters, variables, dotted module names, Windows paths, file names, pipes, and `%` aliases; static course terms stay in the source text and are handled by the ElevenLabs dictionary. It never sets `Recorded`, because final recording also requires the video portion.

The command takes no voice, model, format, tuning, or output-directory overrides. Every one of those values comes from the CourseCraft production narration contract (`demo/artifacts/dictation_audio/production-narration.json`), the voice is live-verified with `elevenlabs voices get`, and the only supported authoritative format is `mp3_44100_128`, which derives `.mp3`.

Demo generation is fail-closed and transactional. It keys idempotence on the canonical normalized Script hash plus voice, model, format, pronunciation dictionary ID/version, tuning, and validated output hash. It generates to a UUID staging path, never the current authoritative take; full-decodes the one audio stream; requires positive duration; verifies the canonical source hash, request identity, no cue leakage, whole-script Whisper recall, and a `-1.0 dBFS` peak/no-clipping policy; then promotes to a content-identity path without overwrite. An adjacent `<audio>.narration.json` records source/output hashes, exact identities, validation evidence, and the deterministic derived-WAV input policy (`pcm_s16le`, 48 kHz, mono) for downstream adapters. Only after promotion does one CourseCraft update write narration metadata and `Dictation Recorded=true`, followed by uncached readback; a demo's take path is derived from `Folder Root` plus `Recording Dictation Method` and is never stored on the record; `Recorded` is never in that write. A validated local promotion can be registered after a write failure without another paid generation. Generation timeouts create a pending reconciliation record and block automatic retry until local, CourseCraft, and ElevenLabs history state are reconciled; failures leave the prior authoritative take and CourseCraft fields unchanged.
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

Historical bug postmortems (28 entries) for the `coursecraft` CLI live in `references/known-issues.md`. Read that file only when troubleshooting an error whose symptoms match a documented pattern; it is not required reading for normal CLI usage.

## Domain Knowledge

### Course Artifact Paths and Module Deletion
**Context:** Relevant when answering whether CourseCraft can locate MP4 clip exports, slide deck files, or generated narration files, and when deleting modules or courses.
**Key Facts:** `coursecraft modules delete --cascade` and `coursecraft courses delete --cascade` delete Airtable records only; they do not remove MP4, PPTX, demo, or narration files. `coursecraft voice-recordings generate --demo` takes no output directory: the take's location comes from the demo's `Folder Root` plus the production contract's `authoritativeOutput`, and no path is stored on the record. Slide narration is never generated; the per-slide WAV take path is derived from the clip's Order and the slide's Clip Order, and no slide field stores it. The CLI does not store clip MP4 paths or PowerPoint deck paths on standard CourseCraft records.
**Gotchas:** In project-scoped course repos, do not rely on CourseCraft global active course when deriving artifact paths; resolve the Course ID slug for the selected course and pass `--course` where supported. For filesystem cleanup, derive paths separately and verify files before deleting.

### Projected Dot-Notation Fields Are Flat Keys
**Context:** Relevant when using `--properties` with Airtable-shaped records and then piping the JSON to `jq`.
**Key Facts:** `--properties "id,fields.Name,fields.Status"` uses the shared cli-tools projection helper. Dot notation selects the nested value, but the projected JSON stores it under the original flat key, for example `"fields.Name"`, not under a nested `fields` object. A single-record `get` result is an object, so read it with `jq '.["fields.Name"]'`; `jq '.fields.Name'` returns null because `fields` is absent after projection. A `list` result is an array, so read its first projected record with `jq '.[0]["fields.Name"]'`. For example, `coursecraft --no-cache slides get <record-id> --properties "id,fields.Name" | jq -r '[.id, .["fields.Name"]] | @tsv'` returns both values. Every requested property key is ALWAYS present in the projected record: a requested field that is empty or absent on the record projects as an explicit `null` (the key is never silently dropped), so a `null` under a flat key such as `"fields.Status"` means that field is genuinely empty/unset — it does NOT mean the property was not requested. Do not infer "field missing" from a vanished key. The "null means empty" guarantee holds only for REAL field names: a misspelled or nonexistent field name ALSO projects an explicit `null` — the projector cannot tell a wrong key from an empty field. Confirmed live 2026-07-19: `--properties "fields.Slide Template"` projected `null` on slide `recvOAtzRVnNqv5ok` while the real `fields.Template` held a linked record id.
**Gotchas:** If downstream code needs normal Airtable shape such as `.fields.Name` or `.fields["Demo Overview"]`, do not use `--properties`; fetch the full record or full list and project with `jq` afterward. Before treating a projected `null` as proof a field is empty, verify the field name against `field_mappings.py`; when the same field projects `null` across every record in a set (a blanket absence), suspect the field name and confirm with a full unprojected `get` on one record. Do not use `jq -r` output for exact long-text byte comparisons. `jq -r` adds one output record newline after the decoded value. A field that already ends with `\n` therefore gains one extra byte in the extracted file. Parse the saved JSON and compare the decoded string in-process instead.

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
