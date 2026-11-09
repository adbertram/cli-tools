---
name: pluralsight-author-cli
description: >-
  MANDATORY: Execute pluralsight-author operations using the `pluralsight-author` CLI tool.
  CLI interface for Pluralsight Author opportunities, module submissions, whole slide-deck templates, and Author Kit icons
  Triggers: pluralsight-author, pluralsight-author cli, pluralsight author, pluralsight author opportunities, pluralsight opportunities, list pluralsight author opportunities, get pluralsight author opportunity, search pluralsight author opportunities, pluralsight author slide deck, latest Pluralsight template, download Pluralsight PowerPoint template, pluralsight author icons, author kit icons, icon library, pluralsight author auth, pluralsight author cache
---

<objective>
Execute pluralsight-author operations using the `pluralsight-author` CLI. All Pluralsight Author opportunities, whole slide-deck downloads, and Author Kit icon-library interactions should use this CLI.
</objective>

<project_overrides>
Before acting, run `~/.agents/skills/skill-expert/scripts/load-skill-overrides.sh pluralsight-author-cli`.
Apply any printed instructions. A non-zero exit means the override is broken; stop and report it.
</project_overrides>

<quick_start>
The `pluralsight-author` CLI follows this pattern:
```bash
pluralsight-author <command-group> <action> [arguments] [options]
```

| Command | Purpose |
|---|---|
| `pluralsight-author opportunities list` | List live Pluralsight Author opportunities. |
| `pluralsight-author opportunities get <slug>` | Fetch one opportunity by its slug. |
| `pluralsight-author search query <text>` | Search the opportunity dataset by keyword. |
| `pluralsight-author slide-deck list` | List whole PowerPoint template downloads from Author Kit Downloads. |
| `pluralsight-author slide-deck get latest` | Read the newest whole PowerPoint template from Author Kit Downloads. |
| `pluralsight-author slide-deck download latest --output <file-or-directory>` | Download and validate the newest whole PowerPoint template. |
| `pluralsight-author icons import <archive>` | Replace the selected profile archive with an Author Kit PNG archive. |
| `pluralsight-author icons list` | List Author Kit icon-library records. |
| `pluralsight-author icons search <query>` | Search icons by a single keyword matched as a case-insensitive substring across id, name, category, color, and tags. The query is not tokenized, so a multi-word phrase usually matches nothing -- search one keyword at a time. |
| `pluralsight-author icons get <icon-id>` | Fetch one icon-library record. |
| `pluralsight-author icons download <icon-id> --output <path>` | Download one icon asset. |
| `pluralsight-author auth login` | Create or refresh the saved browser session required for live opportunity reads. |
| `pluralsight-author cache clear` | Clear response-cache data. Preserve the imported Author Kit ZIP. |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `pluralsight-author` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `pluralsight-author` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- `modules`: Inspect uploaded module assets or submit a manifest containing the approved PowerPoint deck and ordered edited clip videos. Follow the exact adjacent `usage.json` command contract and README manifest schema. Submission verifies uploaded bytes, titles, order, and portal status; an already-submitted module is read-only. `modules submit --plan` is the read-only preview: per clip `unchanged`, `new_version`, or `new_clip`. When Pluralsight asks for edits (`updates_required`, `available_for_updates`), an edited clip becomes a new version of its existing portal clip (the portal's "Replace clip") and a clip with no portal match is refused, never added.
- `opportunities`: Direct list/get access to the live Pluralsight Author opportunities dataset.
- `search`: Keyword search over the opportunity dataset.
- `slide-deck`: Read or download the newest whole presentation template from the authenticated Author Kit Downloads page. `get latest` returns `version`, `filename`, `url`, and `title`; it accepts direct `.potx`/`.pptx` links and Pluralsight's PowerPoint `.zip` package while ignoring the parallel Keynote download. `download latest` downloads through the authenticated browser request context, validates the PowerPoint package, and returns `output`, `bytes`, and `content_type`. These commands use the `author_kit` browser profile.
- `icons`: Import, search, list, inspect, and download Author Kit PNG assets through profile data. Icon commands do not start Chrome or require browser authentication. `--profile` selects the archive namespace. When the imported archive is absent, icon commands fail fast with an error that names the archive path and the `icons import <archive.zip>` rebuild command; there is no browser fallback.
- Before refreshing icons, read the current Inky Blue package link on [Author Kit Downloads](https://authors.pluralsight.com/downloads/), download that ZIP, and run `pluralsight-author icons import <downloaded.zip> --profile author-kit`. The September 2026 package uses the supported PNG layout. Re-import after an official update, then rebuild assets from the imported archive.
- PNG downloads must use a `.png` output filename or an existing directory. The command refuses `.svg` and other mismatched extensions.
- `auth`: Browser-session login, status, auth tests, and nested profile management.
- `cache`: Clear response-cache data. Preserve the imported Author Kit ZIP.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
