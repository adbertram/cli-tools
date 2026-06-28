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
| Add a relation field | `notion field add DB_ID "Imports" --type relation --relation-database TARGET_ID` |
| Create a database | `notion database create PARENT_PAGE_ID -t "Tasks" --status "Phase:Todo\|Done" --date "Due"` |
| Add comment to page | `notion comments create "text" -p PAGE_ID` |
| Append markdown as toggle headings | `notion pages content append PAGE_ID -f outline.md --is-toggleable` |
| List page/block children | `notion pages blocks list --page-id PAGE_ID` |
| List blocks with IDs (database page) | `notion database page content list-blocks PAGE_ID --table` |
| Edit one block in place (keeps comments) | `notion database page content update-block --block-id BLOCK_ID --text "New text"` |
| Toggle existing heading on/off | `notion pages blocks update BLOCK_ID --toggleable` (or `--no-toggleable`) |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `notion` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
Do not run a Notion command in the same parallel batch as the `usage.json` inspection; inspect the target command node first, then execute the exact syntax it shows.

For `pages blocks list`, the page or block ID is a required option, not a positional argument:
```bash
notion pages blocks list --page-id PAGE_ID --markdown
```

For page Markdown reads, `pages get` does not accept output-format flags. Before
adding any output-format option to `notion pages get`, inspect
`commands.pages.commands.get` in `usage.json` or run `notion pages get --help`.
Use `notion pages get PAGE_ID --include-blocks --markdown` (or `-b -m
--out-file file.md`) to fetch Markdown content from a page. Use
`notion pages export PAGE_ID --output file.md --format md` only when exporting
a page through the `pages export` command.

When `pages get` uses `--out-file`, the Markdown file is the command output.
Do not redirect stdout to a `.json` file and do not parse stdout with
`python3 -m json.tool` or `jq`; stdout/stderr can contain only a human status
line or be empty. Verify the read by checking the command exit status and that
the `--out-file` path exists. Do not require the file to be non-empty: a blank
Notion page exports as a valid zero-byte Markdown file. Inspect or print that
Markdown file separately. If JSON page metadata is needed, run a separate
`notion pages get PAGE_ID` command without `--markdown` or `--out-file` and
parse that command's stdout.
</principle>

<principle name="Database Page Create Options">
`notion database page create` accepts only the options listed at
`commands.database.commands.page.commands.create` in `usage.json`: `--title`,
`--status`, `--select`, `--content-file`, `--blocks-file`, `--from-template`,
`--properties`, and `--profile`.

Do not borrow convenience flags from `notion database create` or
`notion database page update`. Flags such as `--number`, `--checkbox`, `--text`,
and `--date` are invalid for `database page create`. For any page property type
not covered by `--status` or `--select`, build the Notion API property object
and pass it through `--properties`.

```bash
notion database page create DB_ID --title "Storyline" \
  --select "Resource:Course" \
  --properties '{"Build Product Order":{"number":1},"For Kid Review":{"checkbox":false}}'
```
</principle>

<principle name="Database Metadata JSON Shape">
When parsing `notion database get` JSON, inspect the actual field type before
extracting nested values. The CLI can expose database metadata fields such as
`title` as a plain string, even though the raw Notion API commonly represents
title text as a rich_text list. Do not run rich_text-only code such as
`t.get("plain_text") for t in data["title"]` until the saved JSON proves that
field is a list of objects. For database titles, accept only the proven CLI
contract shapes: string title, or list of rich_text objects; fail clearly with
`JSON_CONTRACT_MISMATCH: database.title` for any other shape.
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

<principle name="Edit a Single Block In Place to Preserve Comments">
**`content set` destroys ALL inline comments.** Notion anchors inline/block-scoped
comments to a block's ID. `content set` (and `clear`) delete every block and
recreate them with NEW ids, so every comment is orphaned and disappears from the
page. To change a block's text while keeping the block — and therefore every
comment anchored anywhere on the page — edit the block IN PLACE. The CLI PATCHes
`/v1/blocks/{block_id}` (the block ID is unchanged), so comments survive.

Two equivalent surfaces:
```bash
# 1. Map paragraphs/headings to block IDs (id, type, text):
notion database page content list-blocks PAGE_ID --table   # database-page tree
notion pages blocks list --page-id PAGE_ID --table         # standalone-pages tree

# 2. Edit one block in place (same block ID, comments preserved):
notion database page content update-block --block-id BLOCK_ID --text "Revised."
notion pages blocks update BLOCK_ID --text "Revised."
```
Editable block types (single rich_text array): `paragraph`, `heading_1/2/3`,
`bulleted_list_item`, `numbered_list_item`, `quote`, `callout`, `to_do`, `toggle`.
Other types (image, table, table_row, code with structured payloads, etc.) cannot
be edited with `--text`; use `pages blocks update BLOCK_ID --json '...'` for those.

CAVEAT: `pages blocks update BLOCK_ID --toggleable` (without `--no-nest`)
RE-CREATES the heading's section siblings to nest them, which assigns NEW block
IDs and DROPS their comments. Plain `--text` (and `--toggleable --no-nest`) never
recreate blocks. Verified: editing block A in place leaves block B's comment
intact (`comments list --page-id PAGE_ID --with-context` still resolves it to its
block); a `content set` on the same page trashes the block (`archived: true`) and
orphans the comment.
</principle>

<principle name="content set Is Non-Destructive on Oversize Blocks">
`pages content set` (and `content append`, `import`, `replace-section`, `duplicate`)
auto-handle Notion's per-block limits: any single rich_text value over 2000 chars,
or any rich_text array over 100 elements, is split on word boundaries (overflowing
into sibling blocks when needed) so the original text is preserved. This applies to
`--text`, `--file`, and `--json-file` input.

`content set` transforms and validates the FULL payload BEFORE clearing the page, so
an oversize block can no longer empty the page mid-upload. You do NOT need to
pre-split long paragraphs or write the input as one >2000-char block in multiple
chunks — pass the content as-is. (Historical note: a prior version cleared first and
failed on >2000-char paragraphs, leaving the page blank. That hazard is fixed.)
</principle>

<principle name="Unsupported Code-Fence Languages Are Normalized">
Notion's API only accepts code-block languages from a fixed set (~90 languages:
`bash`, `python`, `json`, `sql`, `yaml`, `powershell`, `javascript`, `markdown`,
`plain text`, … — but NOT `kql`). The CLI normalizes any unsupported fence
language to `plain text` on every upload path (`content set`, `content append`,
`import`, `replace-section`, `duplicate`, `database page create --content-file` /
`--blocks-file`), for both Markdown input (` ```kql ` fences) and raw Notion JSON
(`--json-file`). Known languages and the Markdown `text` alias (→ `plain text`)
are preserved. You do NOT need to scrub fence languages before pushing — pass the
content as-is. (Historical note: a prior version forwarded the language verbatim,
which 400'd the request. That hazard is fixed.)
</principle>

<principle name="replace-section Validates the Full Payload Before Mutating">
`pages content replace-section` is now safe against mid-upload API rejections. It
transforms + validates the ENTIRE new payload (block-size limits AND code-fence
language normalization) BEFORE deleting or inserting any block. A pre-checkable
problem (oversize rich_text, unsupported code language) aborts before the page is
touched, so the section can no longer be left half-written with a duplicate
heading. (Historical note: a prior version inserted new blocks first, then
deleted old ones; an API rejection partway — e.g. a ` ```kql ` fence — left a
partial new section AND the original undeleted section, producing a duplicate
heading. That hazard is fixed.)
</principle>

<principle name="Markdown Round-Trip: Intraword Underscores Are Literal">
The CLI's Markdown↔Notion converter follows the CommonMark "intraword
underscore" rule: an underscore with an alphanumeric character on its
inner-facing side cannot open or close emphasis. Technical tokens that contain
underscores — `env_prep.ps1`, `ai_validation_checks`, `walkthrough-run.json`,
`foo_bar_baz` — are preserved as literal text and survive a
`pages content set --file` (or `content append` / `replace-section`) followed by
`pages get -b -m` **byte-for-byte unchanged**.

Do NOT escape underscores as `\_` in input Markdown. Escaping is unnecessary and
produces wrong output (literal backslashes or partial emphasis). Pass tokens
verbatim.

Genuine emphasis still works: whitespace- or punctuation-flanked `_emphasis_`
parses to italic. On export, italic is serialized with asterisks (`*emphasis*`),
which is itself intraword-immune, so the result re-imports as the same italic
span. Asterisk emphasis (`*text*`) intentionally still allows intraword spans,
matching CommonMark.
</principle>

<principle name="Markdown Round-Trip: Code Inside Bold Is Code-Only">
A `` `code` `` token nested inside a `**bold**` (or `*italic*`/`***bold
italic***`) span is emitted **code-only** — the code run is never also marked
bold/italic. Markdown has no syntax for a run that is simultaneously code and
bold, so a bold+code run used to export as `` **`code`** `` and the adjacent
bold delimiters collided into `****`, corrupting input like
`` **Grounding (`clip-slide-plan.1`):** `` into
`` **Grounding (****`clip-slide-plan.1`****):** ``. This is **fixed**: a label
such as `` **Grounding (`clip-slide-plan.1`):** `` now survives
`pages content set --file` → `pages export -f md` (or `pages blocks list -m`)
with **no `****`**. The surrounding text stays bold; the code token stays code.
Pass such labels verbatim — no manual escaping or splitting the bold around the
code is needed.
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

<principle name="Creating a Database">
`notion database create PARENT_PAGE_ID -t "Title"` creates a database under a parent page (POST `/v1/databases`). `PARENT_PAGE_ID` must be a page ID; Notion rejects database and data_source IDs as database parents. The property schema is supplied via `initial_data_source.properties`, which the CLI builds from `--properties` (raw JSON) and/or convenience flags. A title property is always added (named by `--title-property`, default `Name`) unless `--properties` already defines one.

- Simple flags: `--text`, `--number`, `--date`, `--checkbox`, `--url`, `--email`, `--phone`, `--people`, `--files` take `Name`.
- Choice flags: `--select`, `--multi-select`, `--status` take `Name` or `Name:Opt1|Opt2`.
- `--relation "Name:target_data_source_id"` uses the **target's data_source ID** (from `notion database list`), NOT a database container ID. Set `--relation-type single_property` for a one-way relation (default `dual_property`).
- `--inline` creates the database inline in the parent page.
- Output JSON includes the new container `id`, the `data_sources` array (id + name), `data_source_ids`, and `url`.

```bash
notion database create PARENT_PAGE_ID -t "Tasks" \
  --status "Phase:Todo|Doing|Done" --select "Priority:High|Low" --date "Due" \
  --relation "Project:TARGET_DATA_SOURCE_ID"
```
</principle>

<principle name="Adding a Relation Field to an EXISTING Database">
`notion field add DB_ID "Name" --type relation --relation-database TARGET_ID`
adds a relation property to an existing database. Under API 2025-09-03 the
relation schema requires `relation.data_source_id` (the legacy
`relation.database_id` is rejected with a 400:
`body.properties.<Name>.relation.data_source_id should be defined`).

- `--relation-database` accepts EITHER the target's database container ID OR its
  data_source ID. The CLI resolves it to the target's data_source_id before
  sending (same resolution as every other database command). `--relation-data-source`
  is an accepted alias.
- `--relation-type` is `dual_property` (default) or `single_property`.
- `field update DB_ID "Name" --relation-database TARGET_ID [--relation-type ...]`
  repoints or retypes an existing relation field; passing only `--relation-type`
  keeps the current target, passing only `--relation-database` keeps the current type.

```bash
notion field add DB_ID "Imports" --type relation --relation-database TARGET_DB_OR_DS_ID
notion field add DB_ID "Imports" --type relation --relation-database TARGET_ID --relation-type single_property
notion field update DB_ID "Imports" --relation-database NEW_TARGET_ID
```

Note: `field list` reports a relation's target as `relation_database`, which is
the target's database CONTAINER id (Notion echoes it in `relation.database_id`);
the underlying schema still stores the resolved `relation.data_source_id`.
(Historical note: a prior version emitted `relation.database_id` for `field add`,
which 400'd on existing databases. That hazard is fixed.)
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

### 4. `pages blocks list` Truncated at 100 Blocks
**Symptom:** `notion pages blocks list --page-id PAGE_ID` returned only the first 100 child blocks on pages with more than 100 blocks, with no warning. On page `3825d9c85b2b8074bbe3ed8aa65c9f91` it returned 100 blocks / 14 `heading_2`, while `notion pages get PAGE_ID -b -m` rendered all 16 `heading_2` sections from the same page. `--recursive` was also affected: it still capped the top-level list at 100.

**Cause:** The Notion children endpoint (`GET /v1/blocks/{id}/children`) defaults to `page_size=100` and returns `has_more` + `next_cursor`. The client method `get_block_children_all` already paginates fully when called with `limit=None`, but the `blocks list` command hard-coded `--limit` to a default of `100`, passed that as the fetch limit (non-recursive), AND re-sliced the result with `formatted[:limit]` / `blocks[:limit]` in every output path — so even the recursive run (which fetched all top-level blocks) was re-truncated to 100 before output.

**Fix:** `--limit` now defaults to `None` (return the COMPLETE list). The command fetches with `limit=None` by default (full `has_more`/`next_cursor` pagination via `get_block_children_all`) and applies a client-side cap only when `--limit` is explicitly provided. One code path, no fallback. Related: `pages blocks append --after` now reports only the number of blocks actually inserted (`len(blocks)`) instead of `len(results)`; Notion echoes the entire repositioned tail in the `--after` response, which made the old count overstate (e.g. inserting 3 reported 113). The `--after` path sends a single PATCH and never re-fetches or recreates the existing tail, so no blocks are dropped past position 100.

**Verification:** After the fix on page `3825d9c85b2b8074bbe3ed8aa65c9f91` (read-only), `notion pages blocks list --page-id 3825d9c85b2b8074bbe3ed8aa65c9f91` returns 117 blocks / 16 `heading_2`, and `... -m` emits 16 `## ` headings — matching `notion pages get 3825d9c85b2b8074bbe3ed8aa65c9f91 -b -m`. `--limit 50` correctly caps at 50. On a scratch 111-block page, inserting 3 blocks with `--after` a block at index 105 reported `blocks_created: 3`, grew the page to 114, and lost 0 original blocks. Regression tests in `tests/test_blocks_list_pagination.py` cover multi-page `has_more`/`next_cursor` fetches, the uncapped default, the explicit-limit cap, the recursive path, and the `--after` count.

**Recurrence Prevention:** Any command that lists Notion children must paginate the full `has_more`/`next_cursor` sequence by default and must not impose a hidden default cap on `list` output. `--limit` is an explicit opt-in cap only. Never count `len(results)` from an `--after` append as "created" — Notion returns the full repositioned tail there; the inserted count is `len(input_blocks)`.

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
