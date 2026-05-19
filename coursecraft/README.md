# CourseCraft CLI

A command-line interface for managing CourseCraft course content. Provides simplified course, module, clip, demo, and slide management.

## Installation

```bash
cd coursecraft
pip install -e .
```

After installation, the `coursecraft` command will be available in your terminal.

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

# Get course with nested modules
coursecraft courses get my-course-slug --include-modules

# Get course with nested modules and clips
coursecraft courses get my-course-slug --include-clips

# Update a course
coursecraft courses update my-course-slug --name "New Name"
coursecraft courses update recXXX --status "Complete" --active true
coursecraft courses update my-course --target-length 60

# Create a course
coursecraft courses create --name "My Course" --course-id "my-course" \
  --target-length 120 --course-outline-link "https://docs.google.com/..."

# Create course with nested modules from JSON
coursecraft courses create --name "My Course" --course-id "my-course" \
  --target-length 120 --course-outline-link "https://..." \
  --json '[{"name":"Module 1","clips":[{"name":"Intro"}]}]'

# Delete course only (warns about orphaned children)
coursecraft courses delete --course my-course-id

# Delete course and all children
coursecraft courses delete --course my-course-id --cascade

# Delete without confirmation
coursecraft courses delete --course my-course-id --cascade --force
```

### Course Outlines

Read and update course outline data in Google Docs and/or the Airtable database.

#### Read from Google Doc

```bash
# Read course data from a Google Doc (by document ID)
coursecraft course-outlines read -l 1UNCevDbw6QxYlvLx0_L_FQfbiAOZLY_U1sy3EhGxd-I

# Read by URL
coursecraft course-outlines read -l "https://docs.google.com/document/d/DOC_ID/edit"

# Display as table
coursecraft course-outlines read -l DOC_ID
```

Returns JSON matching the same schema as `coursecraft courses get`, including:
- Course fields: Name, Course ID, Job Role, Content Tags, Target Length, Content Level, Notes
- Course planning: Learner Profile, Prerequisites, Storyline, Platform Versions, Short/Long Description
- Learning Objectives: Terminal and Enabling objectives
- Modules: Order, Name, Learning Objectives, Module Layout, Duration

#### Update Google Doc and/or Database

```bash
# Update specific fields in Google Doc (partial update - only specified cells)
coursecraft course-outlines update my-course --type google_doc --name "New Name"

# Update multiple fields in Google Doc
coursecraft course-outlines update my-course --type google_doc \
  --name "Course Title" --learning-objectives "Learn X, Y, Z" --target-length 120

# Update Google Doc from parsed markdown file
coursecraft course-outlines update my-course --type google_doc --course-outline-file outline.md

# Update Airtable "Course Outline" field from markdown file
coursecraft course-outlines update my-course --type database --course-outline-file outline.md

# Update Airtable by parsing a Google Doc URL
coursecraft course-outlines update my-course --type database \
  --course-outline-link "https://docs.google.com/document/d/DOC_ID/edit"

# Update both Google Doc and Airtable
coursecraft course-outlines update my-course --type google_doc,database \
  --course-outline-file outline.md

# Update a specific module in Google Doc (structured params)
coursecraft course-outlines update my-course --type google_doc --module 2 \
  --module-name "Advanced Features" \
  --module-objectives "- Learn X\n- Master Y" \
  --module-layout "Description of the module flow..." \
  --module-duration "9"

# Update a module from content file
coursecraft course-outlines update my-course --type google_doc --module 2 \
  --module-content-file module2.txt --module-duration "9 min"

# Update module with inline content
coursecraft course-outlines update my-course --type google_doc --module 2 \
  --module-content "Module Title

Learning Objectives
- Objective 1
- Objective 2

Module Layout
Description text here..." --module-duration "9"
```

**Update Types:**
- `--type google_doc`: Updates individual table cells in the Google Doc. Only explicitly provided fields are updated (partial update). Data comes from CLI params or `--course-outline-file`.
- `--type database`: Updates the "Course Outline" field in Airtable with markdown content. Content comes from `--course-outline-file` (saved as-is) or `--course-outline-link` (parsed to markdown).
- `--type google_doc,database`: Performs both operations.

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
- Course must have `Pluralsight Course Outline Link` field set to a valid Google Doc URL
- Google Doc must follow the standard course outline template with tables

### Modules

```bash
# List all modules
coursecraft modules list

# List modules for a specific course
coursecraft modules list --course my-course-id

# Get a specific module
coursecraft modules get recXXXXXXXXXXXXXXX

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

# Filter by name pattern
coursecraft demos list --filter "fields.Name:startswith:M1"
coursecraft demos list --filter "fields.Name:contains:Setup"

# Get a specific demo
coursecraft demos get recXXXXXXXXXXXXXXX

# Create a demo (clip-order and demo-environment are required)
coursecraft demos create --clip recXXX --clip-order 1 --name "Setup Demo" --demo-environment local-macos

# Create multiple demos with different orders
coursecraft demos create --clip recXXX --clip-order 1 --demo-environment local-macos --json '[{"name":"Demo 1","clip_order":1},{"name":"Demo 2","clip_order":2}]'

# Update a demo
coursecraft demos update recXXX --name "New Name" --idea "Updated idea"
coursecraft demos update recXXX --script "Updated narration script"
coursecraft demos update recXXX --demo-walkthrough-script-path /Users/adam/courses/example/m2c3/demo_walkthrough.ps1
coursecraft demos update recXXX --demo-environment azure-adam-the-automator
coursecraft demos update recXXX --demo-environment azure-adam-the-automator --demo-environment local-macos

# Delete a demo
coursecraft demos delete recXXX
coursecraft demos delete recXXX --force
```

### Demo Environments

Demo environment records store reusable environment-specific prep and validation
details for CourseCraft demos. Every demo must have at least one linked
`Demo Environment` record. Demo prep/testing agents should read those linked
record IDs, then fetch each environment before running setup or validation.

```bash
# List all demo environments
coursecraft environments list

# List environments for a provider
coursecraft environments list --provider Azure

# Get an environment by record ID, Environment ID, or exact Name
coursecraft environments get azure-adam-the-automator

# Get only the fields needed for prep
coursecraft environments get azure-adam-the-automator \
  --properties "id,fields.Name,fields.Authentication Preflight,fields.Validation Commands,fields.Safe Diagnostics"
```

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

# Update a slide
coursecraft slides update recXXX --template recNEWTEMPLATE
coursecraft slides update recXXX --built
coursecraft slides update recXXX --dictation-recorded
coursecraft slides update recXXX --script "Updated narration script"

# Delete a slide
coursecraft slides delete recXXX
coursecraft slides delete recXXX --force
```

Updating a demo or slide Script clears generated voice recording metadata and sets `Dictation Recorded` to false.

### Voice Recordings

```bash
# Generate narration audio for a slide script
coursecraft voice-recordings generate --slide recXXXXXXXXXXXXXXX \
  --voice-id VOICE_ID \
  --model-id eleven_multilingual_v2 \
  --output-format mp3_44100_128 \
  --output-dir /path/to/course/audio

# Generate narration audio for a demo script
coursecraft voice-recordings generate --demo recXXXXXXXXXXXXXXX \
  --voice-id VOICE_ID \
  --model-id eleven_multilingual_v2 \
  --output-format mp3_44100_128 \
  --output-dir /path/to/course/audio
```

Voice recording generation uses the ElevenLabs CLI for workflows that need separate generated narration before video capture. The command strips non-spoken recording cues, applies packaged regex pronunciation transforms from `coursecraft_cli/voice_pronunciation_patterns.json` and `coursecraft_cli/voice_pronunciation_tokens.json` for dynamic code-shaped text, syncs alias rules from `coursecraft_cli/voice_pronunciations.json` into the ElevenLabs pronunciation dictionary named `CourseCraft Voice Pronunciations`, passes that dictionary locator to `elevenlabs speech create`, validates the output file, and stores voice recording metadata on the record. Regex transforms normalize common code shapes such as PowerShell cmdlets, parameters, variables, dotted module names, Windows paths, file names, pipes, and `%` aliases; static course terms stay in the source text and are handled by the ElevenLabs dictionary. Slide audio is written to `<output-dir>/m<module number>/slides/<slide number> - <slide title>.mp3`; demo audio is written under `<output-dir>/demos/`. Generated audio sets `Dictation Recorded` to true and never sets `Recorded`, because final recording also requires the video portion. If video and audio will be recorded together, skip this command and leave `Dictation Recorded` unset. The CLI defaults to `eleven_multilingual_v2` because CourseCraft narration uses a Professional Voice Clone and Eleven v3 does not currently support PVCs. Legacy tuning flags such as `--style` and `--speaker-boost` are not passed by default; provide tuning flags only after validating the selected ElevenLabs model supports them.

### Demo Build Products

```bash
# List all demo build products
coursecraft demo-build-products list

# List with table output
coursecraft demo-build-products list --table

# List with limit
coursecraft demo-build-products list --limit 5

# Filter demo build products
coursecraft demo-build-products list --filter "name:contains:Demo"

# Get a specific build product by ID or name
coursecraft demo-build-products get recXXXXXXXXXXXXXXX
coursecraft demo-build-products get "Demo Action Summary"

# Sync from XML files to Airtable
coursecraft demo-build-products sync
coursecraft demo-build-products sync --dry-run
coursecraft demo-build-products sync --file demo-action-summary.xml

# Update a build product
coursecraft demo-build-products update recXXX --version "2.0"
```

### Slide Build Products

```bash
# List all slide build products
coursecraft slide-build-products list

# List with table output
coursecraft slide-build-products list --table

# List with limit
coursecraft slide-build-products list --limit 5

# Filter slide build products
coursecraft slide-build-products list --filter "name:contains:Slide"

# Get a specific build product by ID or name
coursecraft slide-build-products get recXXXXXXXXXXXXXXX
coursecraft slide-build-products get "Module intro slide script"

# Sync from XML files to Airtable
coursecraft slide-build-products sync
coursecraft slide-build-products sync --dry-run

# Update a build product
coursecraft slide-build-products update recXXX --version "2.0"
```

### Descript

```bash
# Export a Descript project to the course clips folder
coursecraft descript export "M1C2 - MCP Server" -m 1 -c 2

# Export with specific course
coursecraft descript export "M1C2 - MCP Server" -m 1 -c 2 --course advanced-features-cursor-ai

# Dry run to preview without exporting
coursecraft descript export "M2" -m 2 -c 1 --dry-run

# Export with custom resolution
coursecraft descript export "M1C2" -m 1 -c 2 --width 3840 --height 2160 --fps 60
```

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

### Available Fields by Resource

**Courses:** `name`, `status`, `active`, `course_id`, `target_length`, `content_level`, `job_role`

**Modules:** `name`, `status`, `order`, `course`, `target_length`, `description`

**Clips:** `name`, `status`, `order`, `module`, `target_length`, `story`

**Demos:** `name`, `clip`, `idea`, `action_summary`, `script`, `demo_environment`, `demo_walkthrough_script_path`, `demo_walkthrough_script_created`, `dictation_recorded`, `voice_recording_id`, `voice_recording_path`, `voice_source_hash`, `elevenlabs_voice_id`, `elevenlabs_model_id`, `elevenlabs_output_format`, `elevenlabs_request_id`, `elevenlabs_history_item_id`, `voice_character_count`, `voice_generated_at`

**Demo Environments:** `name`, `environment_id`, `provider`, `status`, `notes`, `tenant_name`, `tenant_id`, `subscription_name`, `subscription_id`, `cloud_name`, `default_location`, `owner_account`

**Slides:** `clip`, `template`, `dictation_recorded`, `voice_recording_id`, `voice_recording_path`, `voice_source_hash`, `elevenlabs_voice_id`, `elevenlabs_model_id`, `elevenlabs_output_format`, `elevenlabs_request_id`, `elevenlabs_history_item_id`, `voice_character_count`, `voice_generated_at`

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
  --course-outline-link "https://docs.google.com/..." \
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
- `google` CLI (required for `course-outlines` commands, must be authenticated)
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
