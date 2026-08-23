# CourseCraft CLI

A command-line interface for managing CourseCraft course content. Provides simplified course, module, clip, demo, and slide management.

## DESCRIPTION

CourseCraft CLI manages CourseCraft Airtable records for courses, modules, clips, demos, slides, slide templates, and voice recordings. Use it when course-building workflows need a scriptable way to read or update CourseCraft content without editing Airtable directly.

## Installation

```bash
uv tool install -e <cli-tools-root>/_personal/coursecraft --force --refresh
```

After installation, the canonical launcher is `~/.local/bin/coursecraft`.

## Quick Start

```bash
# List all modules
coursecraft modules list

# Get a specific course
coursecraft courses get recXXXXXXXXXXXXXXX

# Create a new clip
coursecraft clips create --module recXXX --name "Introduction" --order 1

# Delete a module and all its children
coursecraft modules delete recXXX --cascade
```

## Commands

### Courses

```bash
# List all courses
coursecraft courses list
coursecraft courses list

# List active courses
coursecraft courses list --filter "active:eq:true"

# Get a specific course (by record ID or slug)
coursecraft courses get recXXXXXXXXXXXXXXX
coursecraft courses get my-course-slug
coursecraft courses get my-course-slug --properties "id,fields.Name,fields.Status"

# --properties/-p is repeatable and unions every value. These are equivalent:
coursecraft courses get my-course-slug -p "fields.Platform" -p "fields.Status"
coursecraft courses get my-course-slug -p "fields.Platform,fields.Status"

# Every requested property is always emitted. A field that is absent or empty
# projects an explicit null, so "empty" is never confused with "not requested".

# Projected dot paths are flat output keys:
# jq -r '."fields.Name"', not jq -r '.fields.Name'

# Get course with nested modules
coursecraft courses get my-course-slug --include-modules

# Get course with nested modules and clips
coursecraft courses get my-course-slug --include-clips

# Update a course
coursecraft courses update my-course-slug --name "New Name"
coursecraft courses update recXXX --status "Complete" --active
coursecraft courses update my-course --target-length 60
coursecraft courses update my-course --research-report-file report.md

# Create a course
coursecraft courses create --name "My Course" --course-id "my-course" \
  --target-length 120 --course-requirements-link "https://docs.google.com/..."

# Create course with nested modules from JSON
coursecraft courses create --name "My Course" --course-id "my-course" \
  --target-length 120 --course-requirements-link "https://..." \
  --json '[{"name":"Module 1","clips":[{"name":"Intro"}]}]'

# Delete course only (warns about orphaned children)
coursecraft courses delete --course my-course-id

# Delete course and all children
coursecraft courses delete --course my-course-id --cascade

# Delete without confirmation
coursecraft courses delete --course my-course-id --cascade --force

# Scaffold a course from its approved outline (records plus course folder)
coursecraft courses scaffold --course-slug my-course
coursecraft courses scaffold --google-docs-link "https://docs.google.com/..."
coursecraft courses scaffold --file-path ./approved-outline.pdf

# Optionally write a CourseCraft Deadline during scaffolding
coursecraft courses scaffold --course-slug my-course --deadline 2026-09-30

# Plan the scaffold without creating anything (reads stay live)
coursecraft courses scaffold --course-slug my-course --dry-run

# Start an update from a published pre-CourseCraft Pluralsight import whose
# computed Status is not Complete. The explicit flag verifies the import marker,
# Version 1 identity, Module/Clip records, and every corresponding clip MP4.
coursecraft courses scaffold --base recLEGACY --legacy-import-base --dry-run

# Sync the Pluralsight Curriculum course requirements from the Course's linked Google Doc.
# This does not require or write Deadline and does not scaffold child records.
coursecraft courses sync-requirements my-course
coursecraft courses sync-requirements my-course --dry-run

# Exception lifecycle when Pluralsight still returns inaccurate objectives
coursecraft courses request-objective-correction my-course
# After Pluralsight responds, mark the returned requirements and resync them.
coursecraft courses mark-requirements-update-received my-course
coursecraft courses sync-requirements my-course
# Run and persist a fresh post-feedback course.requirements review, then authorize.
coursecraft courses authorize-objective-override my-course
coursecraft courses apply-objective-override my-course \
  --learning-objectives-file ./objectives.md \
  --reason "Pluralsight retained the current-product inaccuracies after feedback."
```

The override workflow is fail-closed and Pluralsight-only. It requires these
Courses-table fields:

- `Learning Objectives Override State`: single select with exactly `Correction Requested`,
  `Update Received`, `Feedback Resynced`, `Override Authorized`, and `Override Active`
  (blank means the exception lifecycle has never started).
- `Learning Objectives Override Audit`: multiline text containing the schema-versioned,
  append-only logical JSON event document written only by these dedicated commands.

`request-objective-correction` requires a current `NEEDS REVISION` review whose exact
`Reviewed-Version: course.requirements@vN sha256:<hash>` trailer matches `Version Control`.
After Pluralsight returns a correction, `mark-requirements-update-received` requires the exact
`Correction Requested` state and its matching audit event, then transitions to `Update Received`.
The next `sync-requirements` captures before/after requirements and objective snapshots,
transitions to `Feedback Resynced`, and clears the old review even if the returned requirements
are byte-identical. A new current post-feedback review is therefore mandatory before
authorization. Applying the override writes
the canonical `Learning Objectives`, reason, old/new values, current requirements identity, and
timestamp to the audit, then enters `Override Active`. Later requirement syncs preserve those
canonical objectives while continuing to refresh the other Pluralsight-owned fields.

Generic `courses update --learning-objectives` cannot write Pluralsight objectives; use the
dedicated apply command so the state transition and provenance cannot be bypassed. Udemy course
updates retain the generic behavior.

### Artifacts

Run the CourseCraft artifact gates. Both verbs dispatch the owning script in the
CourseCraft checkout and pass its stdout and exit code through unchanged.

Exit codes: `0` passed, `1` failed the contract, `2` usage (unknown slug or a
wrong-shape candidate; stdout is empty).

```bash
# Validate an artifact against its checks.json contract
coursecraft artifacts validate demo.script recXXXXXXXXXXXXXXX
coursecraft artifacts validate slide.content.script recXXXXXXXXXXXXXXX
coursecraft artifacts validate module-review recXXXXXXXXXXXXXXX
coursecraft artifacts validate update.carry_forward_plan ./candidate.json \
  --course recXXXXXXXXXXXXXXX

# Run an artifact's environmental preflight checks
coursecraft artifacts preflight demo.script recXXXXXXXXXXXXXXX
coursecraft artifacts preflight module.powerpoint_deck recXXXXXXXXXXXXXXX
```

### Status

Report and gate the current CourseCraft work phase. The report is JSON on stdout
on every exit code.

Exit codes: `0` clean, `1` an assertion failed, `2` the course or `--module`
selector did not resolve.

```bash
# Report the whole course
coursecraft status get my-course-slug

# Scope the assertions to one module
coursecraft status get my-course-slug --module 2
coursecraft status get my-course-slug --module "M2 - Authenticating to Azure"

# Gate on a phase
coursecraft status get my-course-slug --module 2 --expect-phase "Module Planning"
coursecraft status get my-course-slug --module 2 --check-complete "Module Planning"

# Fail when any in-scope record is feedback-gated
coursecraft status get my-course-slug --check-feedback-gates
```

### Course Outlines

Read and update course outline data in Google Docs and/or the Airtable database.

#### Read from Google Doc

```bash
# Read course data from a Google Doc (by document ID)
coursecraft course-outline read -l 1UNCevDbw6QxYlvLx0_L_FQfbiAOZLY_U1sy3EhGxd-I

# Read by URL
coursecraft course-outline read -l "https://docs.google.com/document/d/DOC_ID/edit"

# Display as table
coursecraft course-outline read -l DOC_ID
```

Returns JSON matching the same schema as `coursecraft courses get`, including:
- Course fields: Name, Course ID, Job Role, Content Tags, Target Length, Content Level, Notes
- Course planning: Learner Profile, Prerequisites, Storyline, Platform Versions, Short/Long Description
- Learning Objectives: Terminal and Enabling objectives
- Modules: Order, Name, Learning Objectives, Module Layout, Duration

#### Update Google Doc

```bash
# Update specific fields in Google Doc (partial update - only specified cells)
coursecraft course-outline update my-course --type google_doc --name "New Name"

# Update multiple fields in Google Doc
coursecraft course-outline update my-course --type google_doc \
  --name "Course Title" --learning-objectives "Learn X, Y, Z" --target-length 120

# Update Google Doc from parsed markdown file
coursecraft course-outline update my-course --type google_doc --course-outline-file outline.md

# Update a specific module in Google Doc (structured params)
coursecraft course-outline update my-course --type google_doc --module 2 \
  --module-name "Advanced Features" \
  --module-objectives "- Learn X\n- Master Y" \
  --module-layout "Description of the module flow..." \
  --module-duration "9"

# Update a module from content file
coursecraft course-outline update my-course --type google_doc --module 2 \
  --module-content-file module2.txt --module-duration "9 min"

# Update module with inline content
coursecraft course-outline update my-course --type google_doc --module 2 \
  --module-content "Module Title

Learning Objectives
- Objective 1
- Objective 2

Module Layout
Description text here..." --module-duration "9"

# Clear an unused module slot (number, content, and duration)
coursecraft course-outline update my-course --type google_doc --module 4 --clear-module
```

`--clear-module` is exclusive: provide `--module`, and do not combine it with
course fields, outline files, module content, or module duration options. A later
normal module update restores and reuses the cleared slot.

**Update Types:**
- `--type google_doc`: Updates individual table cells in the Google Doc. Only explicitly provided fields are updated (partial update). Data comes from CLI params or `--course-outline-file`.

**Available Field Parameters (for google_doc type):**
- `--name`, `--course-id`, `--target-length`
- `--short-description`, `--long-description`
- `--content-level`, `--content-tags`, `--job-role`
- `--learner-profile`, `--prerequisites`
- `--platform-versions`, `--storyline`
- `--learning-objectives`, `--notes`

**Module Update Parameters (for google_doc type):**
- `--module`, `-m`: Module number to update (1, 2, 3, etc.) - required for module updates
- `--module-name`: Module name/title
- `--module-objectives`: Module learning objectives
- `--module-layout`: Module layout description
- `--module-duration`: Module duration (e.g., "9" or "9 min")
- `--module-content`: Full module content (overrides structured params)
- `--module-content-file`: File containing full module content

**Field Mapping (Google Doc tables):**
- Table 0: Course Information (Name, Course ID, Job Role, etc.)
- Table 1: Course Planning (Learner Profile, Prerequisites, Storyline, etc.)
- Table 3: Course Organization (Modules - name, objectives, layout, duration)

**Requirements:**
- `google` CLI must be installed and authenticated
- Course must have `Course Requirements Link` field set to a valid Google Doc URL
- Google Doc must follow the standard course outline template with tables

### Modules

```bash
# List all modules
coursecraft modules list

# List modules for a specific course
coursecraft modules list --course my-course-id

# Get a specific module
coursecraft modules get recXXXXXXXXXXXXXXX
coursecraft modules get recXXXXXXXXXXXXXXX --properties "id,fields.Name,fields.Status"

# Show module hierarchy as ASCII tree diagram
coursecraft modules show M1
coursecraft modules show M1 --course advanced-features-cursor-ai
coursecraft modules show recXXXXXXXXXXXXXXX

# Create a module
coursecraft modules create --name "Getting Started" --course my-course-id --order 1

# Update a module
coursecraft modules update recXXX --name "New Name" --status "Complete"

# Delete module only
coursecraft modules delete recXXX

# Delete module and all children (clips, demos, slides)
coursecraft modules delete recXXX --cascade
```

#### Module Show Output

The `show` command displays a hierarchical tree with statuses:

```
Module: External Documentation and Context Integration (Designing Slides/Demos)
├── Clip: Connecting to Documentation with @Docs (Create Brainstorming Outline)
│   ├── Slide: Course Intro (Ready to Build)
│   ├── Demo: Adding and Sharing Documentation with @Docs (Ready to Test)
│   └── Slide: receKNHFPRwsy99Ib (Ready to Design)
├── Clip: Extending Cursor with MCP Servers (Create Brainstorming Outline)
│   ├── Slide: Clip Intro (Ready to Build)
│   └── Demo: Installing and Using MCP Servers (Designing)
└── Clip: Choosing the Right Documentation Strategy (Create Brainstorming Outline)
    ├── Slide: Clip Intro (Ready to Build)
    └── Demo: Real Migration with Documentation Validation (Designing)

Total: 3 clips, 3 demos, 5 slides
```

### Clips

```bash
# List all clips
coursecraft clips list

# List clips for a module
coursecraft clips list --module recXXX

# Get a specific clip
coursecraft clips get recXXXXXXXXXXXXXXX

# Show clip hierarchy as ASCII tree diagram
coursecraft clips show M1C3
coursecraft clips show M1C3 --course advanced-features-cursor-ai
coursecraft clips show recXXXXXXXXXXXXXXX

# Create a clip
coursecraft clips create --module recXXX --name "Introduction" --order 1

# Create multiple clips from JSON
coursecraft clips create --module recXXX \
  --json '[{"name":"Clip 1","order":1},{"name":"Clip 2","order":2}]'

# Update a clip
coursecraft clips update recXXX --name "Updated Name" --status "Complete"
coursecraft clips update recXXX --module recYYY --order 1
coursecraft clips update recXXX --content-done

# Delete clip only
coursecraft clips delete recXXX

# Delete clip and all children (demos, slides)
coursecraft clips delete recXXX --cascade
```

#### Clip Show Output

The `show` command displays demos and slides with their statuses:

```
Clip: Choosing the Right Documentation Strategy (Create Brainstorming Outline)
├── Slide: Clip Intro (Ready to Build)
├── Demo: Real Migration with Documentation Validation (Designing)
└── Slide: recmebSzHbkr5oqEA (Ready to Design)

Total: 1 demos, 2 slides
```

### Demos

```bash
# List all demos
coursecraft demos list

# List demos for a clip
coursecraft demos list --clip recXXX

# List demos for a module (all clips in module)
coursecraft demos list --module recXXX

# List demos for a course (all demos in course)
coursecraft demos list --course advanced-features-cursor-ai

# Filter by the Demo ID field
coursecraft demos list --filter "id:eq:69"

# Filter by name pattern
coursecraft demos list --filter "name:startswith:M1"
coursecraft demos list --filter "name:contains:Setup"

# Get a specific demo
coursecraft demos get recXXXXXXXXXXXXXXX

# Audit the current recording candidate, proof, reviews, source hashes, and gates
coursecraft demos audit-candidate recXXXXXXXXXXXXXXX

# Create a demo (clip-order and demo-environment are required)
coursecraft demos create --clip recXXX --clip-order 1 --name "Setup Demo"

# Create multiple demos with different orders
coursecraft demos create --clip recXXX --clip-order 1 --json '[{"name":"Demo 1","clip_order":1},{"name":"Demo 2","clip_order":2}]'

# Create a demo and set its execution method
# (choices: "Automated Walkthrough" | "Manual Instructor")
coursecraft demos create --clip recXXX --clip-order 1 --name "Setup Demo" --execution-method "Manual Instructor"

# Every created demo gets its own Recording Dictation Method (it is a per-demo
# field; courses carry none). Create defaults to "Manual Instructor Generation"
# (Adam reads the Demo Script); pass the flag for ElevenLabs narration.
coursecraft demos create --clip recXXX --clip-order 1 --name "Setup Demo" --recording-dictation-method "Automatic Narration Generation"
coursecraft demos update recXXX --recording-dictation-method "Automatic Narration Generation"

# Update a demo
coursecraft demos update recXXX --name "New Name" --idea "Updated idea"
coursecraft demos update recXXX --script "Updated narration script"

# Re-parent a demo to a different clip
coursecraft demos update recXXX --clip recCLIPID
coursecraft demos update recXXX --action-summary-review-ai "Tighten the step ordering"
coursecraft demos update recXXX --execution-method "Automated Walkthrough"

# Finalize AI testing only after the current Demo Overview, Environment Spec,
# and Action Summary have been verified. A changed Demo Overview or Environment
# Spec clears it. An Action Summary edit clears it only when the ordered
# <action>/<expect> cue sequence changes: the CLI compares the new text's
# executable-cue hash against executableCuesSha256 in the demo folder's
# walkthrough.json, so rewording an <explain>/<observe>/<wait> author cue or the
# "## Goal" prose keeps AI Tested. With no readable walkthrough.json, any Action
# Summary change clears it. Each auto-clear prints a notice naming the reason.
coursecraft demos update recXXX --ai-tested

# Delete a demo
coursecraft demos delete recXXX
coursecraft demos delete recXXX --force
```

### Airtable Schema Fields

Use the CourseCraft-owned schema path instead of calling Airtable directly:

```bash
coursecraft fields rename Demos "Tested and Approved" "AI Tested"
```

The command resolves the existing field ID, rejects a duplicate destination
name, performs the rename, and verifies the field schema read-back.

### Slides

```bash
# List all slides
coursecraft slides list

# List slides for a clip
coursecraft slides list --clip recXXX

# List slides for a module (all clips in module)
coursecraft slides list --module recXXX

# List slides for a course (all slides in course)
coursecraft slides list --course advanced-features-cursor-ai

# Get a specific slide
coursecraft slides get recXXXXXXXXXXXXXXX

# Create a slide
coursecraft slides create --clip recXXX --template recTEMPLATE

# Create a slide already placed in the clip and linked to its demo
coursecraft slides create --clip recXXX --template recTEMPLATE --clip-order 3 --demo recDEMOID

# Two demos in one clip: two Demo Intro slides on the SAME template,
# separated by clip order
coursecraft slides create --clip recXXX --template recDEMOINTRO --clip-order 3 --demo recDEMO1
coursecraft slides create --clip recXXX --template recDEMOINTRO --clip-order 5 --demo recDEMO2

# Batch create with per-slide clip order
coursecraft slides create --clip recXXX \
  --json '[{"template":"recT1","clip_order":1},{"template":"recT2","clip_order":2,"demo":"recDEMOID"}]'

# Batch create where every slide shares one CLI-level demo
coursecraft slides create --clip recXXX --demo recDEMOID \
  --json '[{"template":"recT1","clip_order":1},{"template":"recT2","clip_order":2}]'

# Update a slide
coursecraft slides update recXXX --template recNEWTEMPLATE
coursecraft slides update recXXX --built
coursecraft slides update recXXX --dictation-recorded
coursecraft slides update recXXX --script "Updated narration script"

# Delete a slide
coursecraft slides delete recXXX
coursecraft slides delete recXXX --force
```

`slides create` writes the same `Clip Order` and `Demo` fields as `slides update`,
so a slide can be created ready to leave the `Define Order` status instead of
needing a follow-up `slides update` call. Both options work in single mode and in
batch (`--json` / `--file`) mode; in batch mode the per-slide JSON keys
`clip_order` and `demo` override the CLI-level `--clip-order` / `--demo`.

`slides create` refuses to create a slide only when its clip, template, AND clip
order all match an existing slide (a missing template or clip order matches a
blank one). That keeps re-runs idempotent while allowing one clip to hold several
slides built from the same template at different clip orders — for example two
Demo Intro slides for a clip that contains two demos.

Both modes keep the scripting contract: single mode echoes the bare record ID to
stdout, batch mode echoes a JSON array of record IDs, and all progress/success
messages go to stderr. `SLIDE_ID=$(coursecraft slides create --clip recXXX
--template recTEMPLATE --clip-order 3)` captures just the ID.

Updating a demo or slide Script clears generated voice recording metadata and sets `Dictation Recorded` to false.

### Feedback

Feedback records log reviewer notes against a demo or slide, plus any patterns
learned. The `Timestamp` field auto-stamps to the current UTC time on create
when `--timestamp` is omitted.

```bash
# List all feedback
coursecraft feedback list

# List feedback for a specific demo (client-side linked-record filter)
coursecraft feedback list --demo recXXX

# List feedback for a specific slide (client-side linked-record filter)
coursecraft feedback list --slide recXXX

# Filter by feedback text (standard --filter; cannot combine with --demo/--slide)
coursecraft feedback list --filter "feedback:contains:typo"
coursecraft feedback list --filter "timestamp:gte:2026-01-01"
coursecraft feedback list --filter "patterns_learned:contains:course requirements"

# Feedback filter fields use lowercase snake_case schema keys, not Airtable display labels.
# For example, use patterns_learned, not "patterns learned".

# Table output and limit
coursecraft feedback list --table
coursecraft feedback list --limit 10

# Get a specific feedback record
coursecraft feedback get recXXXXXXXXXXXXXXX

# Create feedback against a demo (Timestamp auto-stamps to now)
coursecraft feedback create --demo recXXX --feedback "Step 3 narration was unclear"

# Create feedback against a slide, with patterns learned and an explicit timestamp
coursecraft feedback create --slide recXXX \
  --feedback "Bullet text exceeded the limit" \
  --patterns-learned "Keep each bullet under 64 characters" \
  --timestamp "2026-06-17T12:00:00+00:00"

# Update feedback (any field; --timestamp does not auto-stamp on update)
coursecraft feedback update recXXX --feedback "Revised feedback text"
coursecraft feedback update recXXX --demo recDEMOID
coursecraft feedback update recXXX --patterns-learned "New pattern"

# Delete feedback
coursecraft feedback delete recXXX
coursecraft feedback delete recXXX --force
```

The `--feedback` text is required on create. `--demo`/`--slide` link the record
to a Demos/Slides record (set each only when provided). `--demo` and `--slide`
on `list` are client-side filters over the linked-record arrays and cannot be
combined with `--filter`.

### Voice Recordings

```bash
# Read-only preview for an Automated Walkthrough demo. This performs no
# ElevenLabs call and no Airtable mutation.
coursecraft voice-recordings preview --demo recXXXXXXXXXXXXXXX

# Generate one transactional authoritative demo take. Voice, model, output
# format, tuning, and output location all come from the CourseCraft production
# narration contract; there are no overrides. Slides are never generated.
coursecraft voice-recordings generate --demo recXXXXXXXXXXXXXXX
```

`voice-recordings preview` reads the demo Script and its walkthrough manifest, uses CourseCraft's canonical Demo Script parser, and returns JSON containing `normalizedNarration`, `normalizedNarrationSha256`, `cueValidation`, and `anchorValidation`. It exits nonzero when cue/anchor validation fails. Automated Walkthrough generation runs the same validation before any ElevenLabs or Airtable operation.

Voice recording generation uses the ElevenLabs CLI only for demos whose Recording Dictation Method is Automatic Narration Generation. Demo generation supports only `mp3_44100_128`, derives `.mp3`, live-verifies voice/model/dictionary identity, and generates to a unique `.staging` candidate rather than the current authoritative path. Before promotion it requires a full single-audio-stream decode, positive duration, canonical source hash, no action-cue leakage, whole-script Whisper recall, a peak at or below `-1.0 dBFS`, and exact voice/model/format/dictionary/tuning identity. It promotes without overwrite, then makes one CourseCraft narration update and uncached readback for metadata and `Dictation Recorded=true`; a demo's take path is derived from `Folder Root` and `Recording Dictation Method`, never stored, and it never writes `Recorded`.

The adjacent `<authoritative-audio>.narration.json` is the durable transaction/adapter contract. It binds normalized source and output SHA-256 values, voice/model/format/dictionary/tuning, validation evidence, request/history IDs, and deterministic derived-WAV input policy (`pcm_s16le`, 48 kHz, mono). Timeout checkpoints contain exactly every narration-owned CourseCraft field plus `Recorded`; any key-set or value mismatch blocks before local adoption, history lookup/download, or paid authorization. Exact history-ID recovery derives character count from a positive official `character_count`, a valid positive `character_count_change_to - character_count_change_from`, or nonempty official `text` length, in that order. If none is available it blocks with `HISTORY_RECOVERY_CHARACTER_COUNT_UNAVAILABLE`. Because official history does not guarantee the original request ID, recovered metadata stores `request_id=""` (the CourseCraft/Airtable empty value) plus explicit status/provenance in the sidecar; final CourseCraft update/readback still compares all owned fields exactly. Recovered download SHA-256 must bind the candidate before narration validation. An identical validated local/CourseCraft identity is reused without paid generation. A promoted take can be registered after a write failure without regeneration. Timeout/unknown state leaves a pending reconciliation record and blocks blind retry, preserving the prior take and fields. If video and audio will be recorded together, skip this command and leave `Dictation Recorded` unset.

## Delete Behavior

For resources with children (courses, modules, clips), the delete command supports cascade deletion:

| Flags | Behavior |
|-------|----------|
| (none) | Deletes single record only. Prompts if children exist warning about orphans. |
| `--force` | Deletes single record only. No prompt, allows orphaned children. |
| `--cascade` | Deletes record AND all children. Prompts for confirmation. |
| `--cascade --force` | Deletes record AND all children. No confirmation prompt. |

**Hierarchy:**
- Course → Modules → Clips → Demos, Slides

Leaf resources (demos, slides) only support `--force` since they have no children.

## Write Verification

Every `create` and `update` re-reads the record with a fresh uncached read and
compares each scalar field against what it sent. A write that did not persist
byte-for-byte exits non-zero with `Write to <table> record '<id>' did not
persist as sent`. The CLI never reports a mutated write as a success.

Only four server-side round-trips are treated as a match, because none of them
changes a content character:

| Round-trip | Example |
|------------|---------|
| `--typecast` number/string coercion | sent `"2"`, persisted `2` |
| Multi-select string to array | sent `"a,b"`, persisted `["b", "a"]` |
| dateTime instant form | sent `...T19:05:00+00:00`, persisted `...T19:05:00.000Z` |
| One appended trailing newline | sent `"body"`, persisted `"body\n"` |

### Airtable `richText` fields corrupt Markdown punctuation

An Airtable field of type `richText` is **not a byte-exact store**. Airtable
parses the written text as Markdown and re-serializes it. Measured on base
`app9uzzru5KZOImYQ` on 2026-07-27:

| Sent | Persisted |
|------|-----------|
| `__$operation 2 ... __$operation 4` | `**$operation 2 ... **$operation 4` |
| `__single pair__` | `**single pair**` |
| `module_brainstorming_outline` | `module_brainstorming\_outline` |
| `*emphasis*` | `_emphasis_` |
| `"text   "` (trailing spaces) | `"text\n"` (spaces dropped) |

The identical payloads round-tripped byte-for-byte through a `multilineText`
field in the same record. The rewriting belongs to the field type, not to this
CLI or to the `airtable` CLI.

This breaks any content that legitimately contains `__`, `*`, or `_`: SQL Server
CDC column names (`__$operation`, `__$start_lsn`), Python dunders (`__init__`),
and environment-variable conventions. The CLI fails the write and names the
cause. To store such text, convert the field to **Long text with rich text
formatting turned OFF** in the Airtable UI. The Airtable Meta API cannot change
a field's type.

`richText` fields in the CourseCraft base as of 2026-07-27:

| Table | Field |
|-------|-------|
| Demos | `Script` |
| Clips | `Learning Objectives` |
| Modules | `Learning Objectives` |
| Modules | `Brainstorming Outline` |
| Courses | `Brainstorming Notes` |

Check any field with:

```bash
airtable fields get Demos Script --base app9uzzru5KZOImYQ
```

## Output Formats

All list and get commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

```bash
# JSON output (default)
coursecraft modules list

# Table output
coursecraft modules list
```

## Filter Syntax

Use the `--filter` option with `field:op:value` format to filter records:

```bash
# Filter by status
coursecraft clips list --filter "status:eq:Complete"

# Filter by multiple conditions (AND within filter, OR between filters)
coursecraft modules list --filter "status:eq:Complete,order:gte:2"

# Multiple filters are combined with OR
coursecraft courses list --filter "status:eq:Complete" --filter "active:eq:true"
```

### Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `eq` | Equals | `status:eq:Complete` |
| `ne` | Not equals | `status:ne:Draft` |
| `gt` | Greater than | `order:gt:5` |
| `gte` | Greater than or equal | `order:gte:3` |
| `lt` | Less than | `order:lt:10` |
| `lte` | Less than or equal | `target_length:lte:60` |
| `in` | In list (pipe-separated) | `status:in:Complete\|Draft` |
| `nin` | Not in list | `status:nin:Archived\|Deleted` |
| `like` | Contains (case-sensitive) | `name:like:intro` |
| `ilike` | Contains (case-insensitive) | `name:ilike:intro` |
| `contains` | Contains text | `description:contains:setup` |
| `startswith` | Starts with | `name:startswith:Module` |
| `endswith` | Ends with | `name:endswith:Demo` |
| `null` | Field is empty | `description:null` |
| `notnull` | Field has value | `status:notnull` |

### Booleans vs. numbers

Checkbox fields take the spelled-out words `true`/`false` (or `yes`/`no`):
`built:eq:true`, `recorded:eq:false`. `1` and `0` are numeric values, not
booleans -- `clip_order:eq:0` matches a Clip Order of exactly 0, and
`built:eq:1` matches checked rows because Airtable reads a checked box as 1.
Use `built:eq:false` rather than `built:eq:0`: an unchecked box is stored blank,
so only the boolean word matches it.

### Available Fields by Resource

**Courses:** `name`, `status`, `active`, `course_id`, `target_length`, `content_level`, `job_role`

**Modules:** `name`, `status`, `order`, `course`, `target_length`, `description`

**Clips:** `name`, `status`, `order`, `module`, `target_length`, `description`, `story`

**Demos:** `name`, `clip`, `idea`, `action_summary`, `action_summary_review_ai`, `script`, `dictation_recorded`, `voice_recording_id`, `voice_source_hash`, `elevenlabs_voice_id`, `elevenlabs_model_id`, `elevenlabs_output_format`, `elevenlabs_request_id`, `elevenlabs_history_item_id`, `voice_character_count`, `voice_generated_at`

**Slides:** `clip`, `template`, `dictation_recorded`

**Feedback:** `timestamp`, `feedback`, `patterns_learned`, `demo`, `slide`

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--filter` | `-f` | Filter using `field:op:value` format |
| `--force` | `-f` | Skip confirmation prompts |
| `--cascade` | | Delete all child records |
| `--version` | `-v` | Show version and exit |

## Configuration

Configuration is stored in a `.env` file in the package directory. See the package documentation for required environment variables.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Modules and Extract IDs with jq

```bash
coursecraft modules list | jq '.[].id'
```

### Get Module Names for a Course

```bash
coursecraft modules list --course my-course-id | jq '.[].fields.Name'
```

### Create a Complete Course Structure

```bash
# Create course with modules and clips in one command
coursecraft courses create \
  --name "Introduction to Python" \
  --course-id "intro-python" \
  --target-length 180 \
  --course-requirements-link "https://docs.google.com/..." \
  --json '[
    {"name": "Getting Started", "order": 1, "clips": [
      {"name": "Welcome", "order": 1},
      {"name": "Installation", "order": 2}
    ]},
    {"name": "Basic Syntax", "order": 2, "clips": [
      {"name": "Variables", "order": 1},
      {"name": "Data Types", "order": 2}
    ]}
  ]'
```

### Batch Update Module Status

```bash
# Get all module IDs for a course, then update each
for id in $(coursecraft modules list --course my-course | jq -r '.[].id'); do
  coursecraft modules update "$id" --status "In Progress"
done
```

## Requirements

- Python 3.9+
- Database backend configured
- `google` CLI (required for `course-outline` commands, must be authenticated)
- Dependencies (installed automatically):
  - typer
  - python-dotenv

## License

MIT

## Additional Commands

### Slide Templates

```bash
coursecraft slide-templates --help
coursecraft slide-templates update recXXX --requirements "Exactly three points; each point must be 64 characters or fewer."
```

## Cache

```bash
coursecraft cache status
coursecraft cache clear
```
