---
name: coursecraft
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Coursecraft operations using the `coursecraft` CLI tool.
  CLI interface for Coursecraft.
  Triggers: coursecraft, coursecraft cli
---

<objective>
Execute Coursecraft operations using the `coursecraft` CLI. All Coursecraft interactions should use this CLI.
</objective>

<quick_start>
The `coursecraft` CLI follows this pattern:
```bash
coursecraft <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Run a CourseCraft artifact's environmental preflight checks | `coursecraft artifacts preflight <SLUG> <CANDIDATE>` |
| Validate a CourseCraft artifact against its checks.json contract | `coursecraft artifacts validate <SLUG> <CANDIDATE>` |
| Configure authentication credentials | `coursecraft auth login` |
| Clear stored credentials | `coursecraft auth logout` |
| Create a new profile from .env.example template | `coursecraft auth profiles create <NAME>` |
| Delete a profile and its data | `coursecraft auth profiles delete <NAME>` |
| Get details for a specific profile | `coursecraft auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `coursecraft auth profiles list` |
| Delete a profile and its data | `coursecraft auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `coursecraft auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `coursecraft auth profiles select <NAME>` |
| Check authentication status across profiles | `coursecraft auth status` |
| Test authentication by verifying credentials work across profiles | `coursecraft auth test` |
| Remove all cached responses | `coursecraft cache clear` |
| Create clip record(s) in Airtable | `coursecraft clips create` |
| Get a single clip record by ID | `coursecraft clips get <RECORD_ID>` |
| List clip records | `coursecraft clips list` |
| Display clip hierarchy as an ASCII tree diagram | `coursecraft clips show <CLIP_IDENTIFIER>` |
| Update a clip record | `coursecraft clips update <RECORD_ID>` |
| Read course outline data from a Google Doc | `coursecraft course-outline read` |
| Update course outline Google Doc table cells | `coursecraft course-outline update <COURSE>` |
| Apply an authorized override and persist its complete provenance | `coursecraft courses apply-objective-override <COURSE>` |
| Authorize the contract's initial or late objective-override action | `coursecraft courses authorize-objective-override <COURSE>` |
| Create a course record, optionally with modules and clips | `coursecraft courses create` |
| Disable a course and block future CourseCraft mutations for it | `coursecraft courses disable <COURSE>` |
| Get a single course record by ID or slug | `coursecraft courses get <COURSE>` |
| List course records | `coursecraft courses list` |
| Record external approval of the current Course Outline submission | `coursecraft courses mark-outline-approved <COURSE>` |
| Record external Course Outline changes requested | `coursecraft courses mark-outline-changes-requested <COURSE>` |
| [OPTIONS] {course} Record the external return of corrected Pluralsight requirements | `coursecraft courses mark-requirements-update-received <COURSE>` |
| Enter the Pluralsight objective-correction lifecycle after a current failed review | `coursecraft courses request-objective-correction <COURSE>` |
| Scaffold a course from its approved outline (records plus course folder) | `coursecraft courses scaffold` |
| Record the current ready Course Outline as submitted for review | `coursecraft courses submit-outline-for-review <COURSE>` |
| Sync the Pluralsight Curriculum course requirements into the Course record | `coursecraft courses sync-requirements <COURSE>` |
| Update a course record | `coursecraft courses update <COURSE>` |
| Create demo record(s) in Airtable linked to a clip | `coursecraft demos create` |
| Get a single demo record by ID | `coursecraft demos get <RECORD_ID>` |
| List demo records | `coursecraft demos list` |
| Update a demo record | `coursecraft demos update <RECORD_ID>` |
| Create a feedback record | `coursecraft feedback create` |
| Delete a feedback record | `coursecraft feedback delete <RECORD_ID>` |
| Get a single feedback record by ID | `coursecraft feedback get <RECORD_ID>` |
| List feedback records | `coursecraft feedback list` |
| Update a feedback record | `coursecraft feedback update <RECORD_ID>` |
| List one table's schema fields as JSON rows of id, name, and type | `coursecraft fields schema` |
| Create a module record, optionally with clips | `coursecraft modules create` |
| Get a single module record by ID | `coursecraft modules get <RECORD_ID>` |
| Backfill empty Pluralsight review states to "Not Submitted" (idempotent) | `coursecraft modules initialize-review-states <MODULE>` |
| List module records | `coursecraft modules list` |
| Record external approval of the current Slide Deck submission | `coursecraft modules mark-slide-deck-approved <MODULE>` |
| [OPTIONS] {module} Record external Slide Deck changes requested | `coursecraft modules mark-slide-deck-changes-requested <MODULE>` |
| Record external approval of the current Module Video submission | `coursecraft modules mark-videos-approved <MODULE>` |
| Display module hierarchy as an ASCII tree diagram | `coursecraft modules show <MODULE_IDENTIFIER>` |
| Record the current ready Slide Deck as submitted for review | `coursecraft modules submit-slide-deck-for-review <MODULE>` |
| Record the current ready Module Video review state as submitted | `coursecraft modules submit-videos-for-review <MODULE>` |
| Update a module record | `coursecraft modules update <RECORD_ID>` |
| Create a slide template record | `coursecraft slide-templates create` |
| Get a single slide template by ID or name | `coursecraft slide-templates get <RECORD_ID>` |
| List slide template records | `coursecraft slide-templates list` |
| Update a slide template record | `coursecraft slide-templates update <RECORD_ID>` |
| Create slide record(s) in Airtable linked to a clip | `coursecraft slides create` |
| Get a single slide record by ID | `coursecraft slides get <RECORD_ID>` |
| List slide records | `coursecraft slides list` |
| Update a slide record | `coursecraft slides update <RECORD_ID>` |
| Report the current CourseCraft work phase and findings | `coursecraft status get <COURSE>` |
| Generate the authoritative voiceover take for one demo Script | `coursecraft voice-recordings generate` |
| Preview normalized demo voiceover and validate Script cues without mutation | `coursecraft voice-recordings preview` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `coursecraft` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `coursecraft --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **artifacts** -- Run CourseCraft artifact validation and preflight (subcommands: preflight, validate)
- **auth** -- Manage authentication (subcommands: login, logout, profiles, status, test)
- **cache** -- Manage CLI cache (subcommands: clear)
- **clips** -- Manage clip records (subcommands: create, get, list, show, update)
- **course-outline** -- Manage course outline documents (subcommands: read, update)
- **courses** -- Manage course records (subcommands: apply-objective-override, authorize-objective-override, create, disable, get, list, mark-outline-approved, mark-outline-changes-requested, mark-requirements-update-received, request-objective-correction, scaffold, submit-outline-for-review, sync-requirements, update)
- **demos** -- Manage demo records (subcommands: create, get, list, update)
- **feedback** -- Manage feedback records (subcommands: create, delete, get, list, update)
- **fields** -- Manage CourseCraft Airtable schema fields (subcommands: schema)
- **modules** -- Manage module records (subcommands: create, get, initialize-review-states, list, mark-slide-deck-approved, mark-slide-deck-changes-requested, mark-videos-approved, show, submit-slide-deck-for-review, submit-videos-for-review, update)
- **slide-templates** -- Manage slide template records (subcommands: create, get, list, update)
- **slides** -- Manage slide records (subcommands: create, get, list, update)
- **status** -- Report CourseCraft work phase status (subcommands: get)
- **voice-recordings** -- Generate demo voice recordings (subcommands: generate, preview)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`coursecraft --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
