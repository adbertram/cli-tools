---
name: notion-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute Notion operations using the `notion` CLI tool.
  CLI interface for Notion API with database query filtering.
  Triggers: notion, notion cli, notion databases, notion pages, notion comments, notion fields, list notion databases, search notion pages, query notion database, create notion page, update notion page, export notion page, notion page content, notion blocks, notion schema, notion templates
---

<objective>
Execute Notion operations using the `notion` CLI. All Notion interactions should use this CLI.
</objective>

<quick_start>
The `notion` CLI follows this pattern:
```bash
notion <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List all databases | `notion database list --table` |
| Query database pages | `notion database page list -d DB_ID --filter "Status:Done" --table` |
| Get page with content | `notion pages get PAGE_ID -b -m` |
| Create database page | `notion database page create DB_ID -t "Title" --status "In progress"` |
| Search pages by title | `notion pages search "query" --table` |
| Export page to markdown | `notion pages export PAGE_ID -o file.md -f md` |
| Replace a section | `notion pages content replace-section PAGE_ID -h "## Heading" -f updated.md` |
| Get database schema | `notion database schema DB_ID --table` |
| Add comment to page | `notion comments create "text" -p PAGE_ID` |
| Append markdown as toggle headings | `notion pages content append PAGE_ID -f outline.md --is-toggleable` |
| List page/block children | `notion pages blocks list --page-id PAGE_ID` |
| Toggle existing heading on/off | `notion pages blocks update BLOCK_ID --toggleable` (or `--no-toggleable`) |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `notion` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
Do not run a Notion command in the same parallel batch as the `usage.json` inspection; inspect the target command node first, then execute the exact syntax it shows.

For `pages blocks list`, the page or block ID is a required option, not a positional argument:
```bash
notion pages blocks list --page-id PAGE_ID --markdown
```
</principle>

<principle name="Section Updates vs Full Replace">
**NEVER use `pages content set` to update a single section of a page.** `content set` is a FULL PAGE REPLACE — it deletes ALL content and rewrites the entire page, destroying image links, embeds, and other sections.

For updating a specific section, always use `pages content replace-section`:
```bash
# Replace just one section, leaving the rest of the page untouched
notion pages content replace-section PAGE_ID --heading "## Section Title" --file updated.md

# Dry run first to verify what will be changed
notion pages content replace-section PAGE_ID --heading "## Section Title" --file updated.md --dry-run
```

Only use `pages content set` when you intend to replace the ENTIRE page content.
</principle>

<principle name="Command Groups">
- **auth** — Manage authentication (status, login, logout)
- **database** — Query/manage databases, database pages, templates
- **field** — Manage database field schemas (list, add, rename, delete, update, options)
- **pages** — Search, list, create, import, export, duplicate, update, delete standalone pages; manage content and blocks
- **comments** — List, get, create comments on pages, blocks, or discussion threads
</principle>

<principle name="API 2025-09-03 Data Source Split">
Notion's `2025-09-03` API splits a database into two resources:
- A **database container** (`/v1/databases/{id}`) holding metadata and a `data_sources[]` array.
- One or more **data sources** (`/v1/data_sources/{id}`) holding the property schema and rows.

The two ID types are NOT interchangeable. There is no way to tell them apart from the ID alone.
The `notion` CLI handles this transparently:

- IDs returned by `notion database list` are data_source IDs (returned by `/v1/search` with `filter=data_source`). They work directly with `database get`, `database schema`, `database page list`.
- IDs copied from the Notion UI (the URL after `notion.so/` or the share link) are database container IDs. The CLI calls `/v1/databases/{id}` to read `data_sources[]` then routes to the right data_source.
- For the rare case of a database with multiple data sources, every database command supports `--data-source <ds_id>`. Without it, the CLI errors out and lists the available data_source IDs. Never silently picks one.
- `notion database get DB_ID` includes the resolved `data_sources` array and `resolved_data_source_id` in its output for visibility.

If you see "Resource not found" against a database you know exists, the integration likely has access via a parent page rather than direct database share. Re-share the specific database (or its parent) with the integration.
</principle>

<principle name="Toggle Blocks (Collapsible Headings)">
The right-arrow ▶ that collapses/expands a heading in the Notion UI is the
`is_toggleable: true` flag on a `heading_1`/`heading_2`/`heading_3` block.
A non-heading toggle is the `toggle` block type.

**Three ways to create toggle headings:**
```bash
# 1. From markdown -- promote ALL headings to toggleable in one shot
notion pages content append PAGE_ID --file chapter.md --is-toggleable
notion pages content set    PAGE_ID --file outline.md --is-toggleable
notion pages blocks  append BLOCK_ID --file content.md --is-toggleable
notion pages create  PARENT_ID -t "Page" --content-file outline.md --is-toggleable

# 2. From raw JSON -- mix toggleable and non-toggleable headings
#    (markdown can't express which heading is toggleable per-heading)
notion pages blocks append PAGE_ID --json-file blocks.json

# 3. Flip an existing heading on or off
#    Auto-nests siblings as children when toggling ON (default).
notion pages blocks update BLOCK_ID --toggleable
notion pages blocks update BLOCK_ID --toggleable --no-nest      # flip flag only
notion pages blocks update BLOCK_ID --no-toggleable
notion pages blocks update BLOCK_ID --text "New title" --toggleable   # combine
```

**Reading toggleability:**
- `pages blocks list` JSON summary includes `is_toggleable: true|false` for headings
- `pages blocks list --table` shows an `is_toggleable` column with a ✓/blank indicator
- `pages blocks list --markdown` and `pages blocks get --markdown` prefix toggle headings with `▶ ` (e.g. `# ▶ Section Title`)
- `pages blocks get` (raw JSON) exposes the flag at `.heading_1.is_toggleable` (or `.heading_2`/`.heading_3`)

**Putting content inside a toggle:**
Markdown like `# Heading\n\nParagraph` produces SIBLINGS, not parent/child --
a toggle with no children renders as an empty arrow in the UI.

There are three ways to put content inside a toggle:

1. **Flip an existing non-toggle heading with `--toggleable`** (recommended for
   surgical edits). The CLI automatically re-parents the heading's "section"
   siblings -- everything between the heading and the next same/higher-level
   heading -- as children of the toggle. Pass `--no-nest` to skip this and
   only flip the flag.

   ```bash
   notion pages blocks update HEADING_ID --toggleable
   ```

   Caveat: re-parenting recreates the section blocks via the API, so block
   IDs change and any block-scoped comments on those blocks are dropped.
   Page-level comments are unaffected. Use `--no-nest` when you must preserve
   block IDs.

2. **Append children directly** to a heading that's already toggleable:
   ```bash
   notion pages blocks append HEADING_ID --text "This paragraph is INSIDE the toggle"
   ```

3. **Use raw JSON with `children`** for greenfield creation -- arbitrary nesting
   depth is supported via `--json-file`.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

## Known Issues

### 1. Comment Context Reads Can Stall on Large Pages
**Symptom:** `notion comments list --page-id PAGE_ID --with-context --limit 100` can sit silent for more than a minute and write an empty output file while the process remains alive. After a heavy comment scan, a direct API check may return HTTP 429 with `Retry-After` (for example, 50 seconds).

**Cause:** Notion's public comments endpoint does not return this workspace's inline block comments from the parent page ID alone, so `--with-context` must recursively read page blocks and check comments on each block. The old CLI used only 5 workers and did not pass the configured worker count into the recursive block-read phase. Repeated comment scans can also hit Notion API rate limiting; the CLI honors `Retry-After`, so it may appear silent while it waits.

**Fix:** Use the normal command; the CLI now defaults to 25 workers and applies that count to both recursive block reads and block comment lookups: `notion comments list --page-id PAGE_ID --with-context --limit 100 > comments.json`.

**Verification:** Confirm the output file contains valid JSON and `jq 'length' comments.json` returns the expected comment count. On the BricklinkBook page `3f5aaa654fc74a11bc0fc3865cdfcedd`, the no-manual-worker command returned 34 comments in about 25 seconds after the rate-limit window cleared.

**Recurrence Prevention:** Do not reintroduce silent exception suppression or a low default worker count in comment context reads. `--max-workers` remains available for diagnostics, but large-page review workflows should be fast by default. Avoid repeated parallel comment scans against the same large page; if 429 appears, wait the `Retry-After` period before rerunning.

### 2. Comment Target Block Is Available

**Symptom:** `notion comments list --page-id PAGE_ID --with-context` returns inline comments and parent block context. That parent block is the selected comment target for review work. Older report workflows treated `[table_row block]` as missing comment context.

**Cause:** Notion's public comments API returns comment metadata, parent, discussion ID, author/timestamps, `rich_text`, attachments, and display name. It exposes the parent block, which the CLI reports as `context` and `selected_block`. The CLI can derive nearby context by reading adjacent blocks. Separately, older CLI context extraction only read `rich_text`, so table rows and other non-`rich_text` blocks produced weak context like `[table_row block]`.

**Fix:** Use the parent block as the comment target. Use `notion comments list --page-id PAGE_ID --with-context --limit 100` for parent block and nearby block context. Current JSON output includes `context`, `context_before`, `context_after`, `context_around`, `selected_block`, and `selected_block_status`.

**Verification:** A raw `GET /comments/{comment_id}` probe on BricklinkBook comment `3535d9c8-5b2b-800a-a540-001dccf638dc` returned parent block metadata. Unit tests cover table-row context extraction and selected block output.

**Recurrence Prevention:** Review workflows must use the parent block as the comment target and use parent/nearby block context for revision planning.

### 3. Replace-Section Local Images and Dry Runs
**Symptom:** `notion pages content replace-section PAGE_ID --heading "## Section" --file section.md` did not upload local Markdown images, so replacement content containing `![alt](local.png)` could not persist image blocks correctly. The first repair attempt also uploaded images during `--dry-run`.

**Cause:** `replace-section` parsed Markdown with `text_to_blocks(content)` directly, while `content append` and database Markdown paths process local images first and pass `image_uploads` into `text_to_blocks`. Image processing was initially added before the dry-run branch, which made dry runs perform Notion file uploads.

**Fix:** `replace-section` now calls the shared Markdown image processor only when `--file` is used and `--dry-run` is false, then calls `text_to_blocks(content, image_uploads=image_uploads)`.

**Verification:** In `/Users/adam/Dropbox/GitRepos/cli-tools/notion`, `uv run --extra dev pytest -q` passes. Tests cover local image upload wiring and prove `--dry-run` does not call image upload processing.

**Recurrence Prevention:** Any future Markdown-processing page command must match the append/set behavior for local images and must keep `--dry-run` read-only before making API upload calls.

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
