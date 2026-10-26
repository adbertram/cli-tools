---
name: gumroad-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Gumroad operations using the `gumroad` CLI tool.
  CLI interface for Gumroad.
  Triggers: gumroad, gumroad cli
---

<objective>
Execute Gumroad operations using the `gumroad` CLI. All Gumroad interactions should use this CLI.
</objective>

<project_overrides>
Before acting on this skill, run:

```bash
~/.agents/skills/skill-expert/scripts/load-skill-overrides.sh gumroad-cli
```

Apply any printed instructions alongside this skill's own workflow: they extend it and
never repeal its limits. No output means no project override is in effect. A non-zero
exit means the project's override file is broken -- report it and stop rather than
silently running unmodified.
</project_overrides>

<quick_start>
The `gumroad` CLI follows this pattern:
```bash
gumroad <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Configure authentication credentials | `gumroad auth login` |
| Clear stored credentials | `gumroad auth logout` |
| Create a new profile from .env.example template | `gumroad auth profiles create <NAME>` |
| Delete a profile and its data | `gumroad auth profiles delete <NAME>` |
| Get details for a specific profile | `gumroad auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `gumroad auth profiles list` |
| Delete a profile and its data | `gumroad auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `gumroad auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `gumroad auth profiles select <NAME>` |
| Check authentication status across profiles | `gumroad auth status` |
| Test authentication by verifying credentials work across profiles | `gumroad auth test` |
| Build current Notion Drafts; attach exact artifact and source manifest to the root | `gumroad books build-epub <BOOK_PAGE_URL> --mode publication --image-mode native` |
| Build current Notion Drafts; attach exact artifact and source manifest to the root | `gumroad books build-pdf <BOOK_PAGE_URL> --mode publication --image-mode native` |
| Read-only source, schema, order and publication-readiness inspection | `gumroad books inspect <BOOK_PAGE_URL> --mode publication` |
| Remove all cached responses | `gumroad cache clear` |
| Install locked npm dependencies and compile the standalone engine | `gumroad engine install` |
| planGumroadFormats: preserve exact source/hash/approval gates | `gumroad formats plan --input-file approved-input.json` |
| updateGumroadFormats: preserve exact source/hash/approval gates | `gumroad formats update --input-file approved-input.json` |
| Inspect product metadata, attachment IDs and target-state hash | `gumroad products get <PRODUCT_ID>` |
| List account product destinations; never expose paid-file download URLs | `gumroad products list` |
| createGumroadDraft: preserve exact source/hash/approval gates | `gumroad releases create-draft --input-file approved-input.json` |
| planGumroadRelease: preserve exact source/hash/approval gates | `gumroad releases plan --input-file approved-input.json` |
| publishGumroadBook: preserve exact source/hash/approval gates | `gumroad releases publish --input-file approved-input.json` |
| updateGumroadBook: preserve exact source/hash/approval gates | `gumroad releases update --input-file approved-input.json` |
| Discover operation schemas | `gumroad schema list --table` |
| Return an operation's complete input schema and CLI mapping without authentication | `gumroad schema get <OPERATION>` |
| createGumroadSmokeDraft: preserve exact source/hash/approval gates | `gumroad smoke-drafts create --input-file approved-input.json` |
| updateGumroadSmokeDraft: preserve exact source/hash/approval gates | `gumroad smoke-drafts update --input-file approved-input.json` |
| smokeTestGumroadUpload: preserve exact source/hash/approval gates | `gumroad uploads smoke-test --input-file approved-input.json` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Read adjacent `usage.json` before executing any Gumroad command.** Never guess flags or operation field names. Use `gumroad schema list` and `gumroad schema get CAPABILITY` for strict input contracts. Missing required contract data is an error, not permission to invent defaults.
</principle>

<principle name="Command Groups">
- **auth** -- Manage gumroad authentication (subcommands: login, logout, profiles, status, test)
- **books** -- Read current Notion manuscripts and build derived artifacts (subcommands: build-epub, build-pdf, inspect)
- **cache** -- Manage response cache (subcommands: clear)
- **engine** -- Install the local renderer and API engine (subcommands: install)
- **formats** -- Formats operations with exact JSON inputs (subcommands: plan, update)
- **products** -- Read safe product metadata and attachment IDs (subcommands: get, list)
- **releases** -- Releases operations with exact JSON inputs (subcommands: create-draft, plan, publish, update)
- **schema** -- Inspect strict operation JSON schemas (subcommands: get, list)
- **smoke-drafts** -- Smoke-Drafts operations with exact JSON inputs (subcommands: create, update)
- **uploads** -- Uploads operations with exact JSON inputs (subcommands: smoke-test)
</principle>
<principle name="Standalone engine and credentials">
This CLI runs a local API/build engine, not the hosted Worker. If the engine is missing, run `gumroad engine install` once. Gumroad auth uses the CLI-tools secret manager through `gumroad auth login`; book-only commands reuse the existing secret `notion-api-token`. Product reads require only Gumroad, manuscript builds only Notion, and release operations both. Never pull brokered Worker secrets.
</principle>
<principle name="Book builds and reviewed releases">
Read current Notion Drafts only. Use explicit publication/proof mode and native/approved ebook200 image mode; author is known or omitted. Build PDF and EPUB serially. Publication requires Final/no DETAIL. Do not edit manuscripts/statuses to pass a gate. Release input files must match `schema get`, including explicit nulls and actual review/hash/plan approvals. A boolean flag must never be set merely to make a command run. New products remain unpublished; publication and live updates require their separate exact approvals. Preserve metadata/state/attachments. Use formats plan/update for existing PDF+EPUB products.
</principle>
<principle name="Ambiguous writes and verification">
Never retry uploads/product/publication writes automatically. Inspect exact product/artifact/receipt state after ambiguous results. Receipt failure after verified delivery is not permission to repeat a write. Product output intentionally excludes signed/canonical paid-file URLs and buyer data. No audience-email operation exists. Do not perform real writes solely to test setup.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`gumroad --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
