---
name: notion-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute Notion operations using the `notion` CLI tool.
  CLI interface for Notion API with database query filtering.
  Triggers: notion, notion cli, notion databases, notion pages, notion comments, notion fields, notion users, notion mention, mention someone in notion, notify notion user, list notion databases, search notion pages, query notion database, create notion page, update notion page, export notion page, notion page content, notion blocks, notion schema, notion templates
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
| Trash a whole database | `notion database delete DB_ID --force` |
| Restore a trashed database | `notion database delete DB_ID --restore --force` |
| Add comment to page | `notion comments create "text" -p PAGE_ID` |
| Notify a person in a comment | `notion comments create "text" -p PAGE_ID --mention someone@example.com` |
| Add shell-sensitive comment text | `notion comments create --text-file comment.md --discussion-id DISCUSSION_ID` |
| List workspace users | `notion users list --table` |
| Find a user by email | `notion users list --filter "person.email:eq:someone@example.com"` |
| Get one user | `notion users get USER_ID --table` |
| Append markdown as toggle headings | `notion pages content append PAGE_ID -f outline.md --is-toggleable` |
| List page/block children | `notion pages blocks list --page-id PAGE_ID` |
| List blocks with IDs (database page) | `notion database page content list-blocks PAGE_ID --table` |
| Edit one block in place (keeps comments) | `notion database page content update-block --block-id BLOCK_ID --text "New text"` |
| Delete a block non-interactively | `notion pages blocks delete BLOCK_ID --force` |
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

For database status-page readbacks, `database page get` does not accept
`--properties`; that option is available on list/search-style commands such as
`notion database page list --database-id DB_ID --properties "id,Name,Status,url"`.
When checking one known page after an update, run:
```bash
notion database page get PAGE_ID
```
Its default JSON output includes the page summary fields produced by the CLI
(for example `id`, `url`, `Status`, and `Name`). Filter that JSON after the
command if you need a smaller display.

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

<principle name="Non-Interactive Destructive Commands Require Explicit Confirmation Flags">
Destructive Notion commands prompt only when stdin is an interactive terminal.
In agent Bash tools, CI, cron jobs, pipes, or other non-interactive contexts,
pass the command's documented confirmation-skip flag explicitly. For block
deletion, use:

```bash
notion pages blocks delete BLOCK_ID --force
notion pages blocks delete BLOCK_ID --recursive --force
```

Without `--force`, the command refuses before deletion and tells the caller to
re-run with `--force`; it does not read from non-interactive stdin. Always
confirm the exact target ID before supplying a mutation-skip flag.
</principle>

<principle name="Full ID Extraction">
Use default JSON output when a Notion ID will be copied into a follow-up
command. Do not copy page, block, database, data_source, comment, or discussion
IDs from table output that contains an ellipsis (`...` or `…`). Rich table
rendering can shorten UUID cells when several columns are shown. For follow-up
commands, first run a JSON command with `--properties id,<needed fields>` when
the command supports it, copy the full UUID from JSON, then call commands such
as `notion pages get PAGE_ID`, `notion database page update PAGE_ID`, or
`notion comments create --discussion-id DISCUSSION_ID`.

When any requested property name contains spaces, quote the entire
comma-separated `--properties` value so Bash passes it as one argument:
`notion database page list --database-id DB_ID --properties "id,Name,Website,Contact Email"`.
Do not pass an unquoted comma list such as
`--properties id,Name,Website,Contact Email`; Bash splits `Contact Email` and
Typer rejects the extra `Email` argument before the CLI can parse properties.
</principle>

<principle name="A Plain @Name In Comment Text Notifies Nobody">
Typing `@Mandy Mowers` into a comment body stores plain text. Notion sends **no**
notification for it, and the reader gets no link to the person. A mention is a
distinct `rich_text` object type, and `--mention` is the only way to create one.

```bash
notion comments create "please review this" --page-id PAGE_ID --mention someone@example.com
notion comments create "please review this" --page-id PAGE_ID --mention USER_UUID
notion comments create "handoff" --discussion-id DISCUSSION_ID -m a@x.com -m b@x.com
```

`--mention` is repeatable, accepts an email address or a user UUID, and works
with `--page-id`, `--block-id`, and `--discussion-id` alike. Resolved mentions
lead the comment in the order given, each followed by a single space, then the
body text from the positional argument or `--text-file`.

Resolution fails before the write and never degrades to plain text:

- An email matching no user is an error naming the email; no comment is posted.
- An email matching more than one user is an error listing every match.
- A user of type `bot` is rejected before the API call; only `person` users can
  be mentioned, and Notion rejects a bot ID for the whole request.
- A value that is neither a UUID nor an email is an error before any API call.

After creation the CLI validates the returned `rich_text`: if the created
comment's user mentions are not exactly the resolved IDs, the command fails
instead of printing success. `comments list`/`get`/`create` JSON now include a
`mentions` array of the mentioned user IDs.

Resolve by email only when the integration has both the **read user information**
capability (for `GET /v1/users`) and the **email** capability (which populates
`person.email`). Without the email capability, `notion users list` shows empty
emails; pass the user UUID instead.
</principle>

<principle name="Listing Workspace Users">
`notion users list` walks every `GET /v1/users` cursor page, so it returns the
complete workspace roster rather than the first 100. `--limit` is an explicit
opt-in cap, not a default.

Notion has no server-side name or email filter for users, so `--filter` is
applied client-side. Each record keeps the raw `person` / `bot` sub-object plus a
flat `email` convenience field, so both forms work:

```bash
notion users list --table
notion users list --filter "type:eq:person" --table
notion users list --filter "person.email:eq:someone@example.com"
notion users list --filter "email:eq:someone@example.com"
notion users list --properties "id,name,email"
notion users get USER_ID --table
```

Only `type: person` users can be mentioned. Bot users (integrations) appear in
the listing with an empty email and are rejected by `comments create --mention`.

`GET /v1/users` returns HTTP 403 when the integration lacks the **read user
information** capability. That is a Notion integration settings change, not a CLI
defect.
</principle>

<principle name="Comment Text With Shell Metacharacters">
For comment bodies containing backticks, `$()`, shell variables, angle-bracket
placeholders, quotes, or newlines, write the exact body to a file with a quoted
heredoc and pass it with `--text-file`:

```bash
comment_file=$(mktemp -t notion-comment.XXXXXX)
cat >"$comment_file" <<'EOF'
Processed this correction for target `deploy/instructions/developmental-reviewer.md`.
The email includes `ATA-TOPIC-<topic_id>`.
EOF
notion comments create --text-file "$comment_file" --discussion-id DISCUSSION_ID
```

Do not put shell-sensitive comment text inside a double-quoted command argument;
Bash evaluates backticks and command substitutions before the CLI receives the
text.
</principle>

<principle name="Replies to Discussions on Deleted Blocks Fail Loudly">
Notion can accept `POST /comments` for an inline discussion whose parent block
is in trash while creating a comment with empty `rich_text`, even when the
request contains non-empty text. The CLI validates the created comment response
against the submitted text. If Notion drops or changes any non-empty reply text,
`notion comments create` prints an error containing the created comment ID and
exits nonzero instead of emitting success JSON.

Do not retry the same discussion: retries can create more empty comments. Move
the reply to a live page/block discussion or restore the parent block first.
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

<principle name="Filter Operators Depend On The Property Type">
`notion database page list --filter "Field:op:value"` reads the database schema
and builds a Notion filter for that property's type. The property name must
exist in the schema; an unknown name fails locally and lists the real property
names. An operator the property type does not support also fails locally, before
any API call.

Generic operators for non-date properties: `eq`, `ne`, `in`, `nin`, `like`,
`ilike`, `contains`, `gt`, `gte`, `lt`, `lte`, `null`, `notnull`. `in` and `nin`
take pipe-separated values. `gt`/`gte`/`lt`/`lte` require a `number` property.
Omitting the operator means `eq` (`--filter "Status:Done"`).

`null` and `notnull` become Notion's `is_empty` and `is_not_empty` conditions,
nested under the property's own type. They work for `title`, `rich_text`,
`number`, `select`, `status`, `multi_select`, `people`, `files`, `relation`,
`url`, `email`, `phone_number`, `created_by`, `created_time`, `last_edited_by`,
`last_edited_time`, and `date`. Notion has no emptiness condition for
`checkbox`, `formula`, or `rollup`, so those fail locally before any API call.

```bash
notion database page list -d DB_ID --filter "Keywords:null"
notion database page list -d DB_ID --filter "Category:notnull"
```

**Date properties use Notion's own date operators:** `equals`, `before`,
`after`, `on_or_before`, `on_or_after`, `this_week`, `past_week`, `past_month`,
`past_year`, `next_week`, `next_month`, `next_year`, `is_empty`, `is_not_empty`.
These aliases also work: `eq`=`equals`, `gt`=`after`, `gte`=`on_or_after`,
`lt`=`before`, `lte`=`on_or_before`, `null`=`is_empty`, `notnull`=`is_not_empty`.

```bash
notion database page list -d DB_ID --filter "Publish Date:on_or_after:2026-07-20"
notion database page list -d DB_ID --filter "Publish Date:gte:2026-07-20"
notion database page list -d DB_ID --filter "Publish Date:before:2026-08-01"
notion database page list -d DB_ID --filter "Publish Date:past_week"
notion database page list -d DB_ID --filter "Publish Date:is_not_empty:true"
```

The relative-range operators (`this_week`, `past_week`, ...) and the presence
operators (`is_empty`, `is_not_empty`) take no value; write the operator alone
or with the value `true`. The value operators require an ISO 8601 date such as
`2026-07-20` or `2026-07-20T09:00:00Z`, or one of Notion's keywords: `today`,
`tomorrow`, `yesterday`, `one_week_ago`, `one_week_from_now`, `one_month_ago`,
`one_month_from_now`.
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
It also archives/removes any child pages represented by `child_page` blocks in
that parent. Create intended child pages only after the full parent replacement,
or avoid `pages content set` and use a non-full-replace operation.
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
IDs and DROPS their block-scoped comments. Notion-hosted images/files in the
section are now PRESERVED: the re-parent path re-uploads each hosted `image`/
`video`/`pdf`/`file` block via the File Upload API before recreating it, so the
image survives inside the toggle intact (see Known Issue #8). Only comments (and
the block IDs they anchor to) are lost. Plain `--text` (and
`--toggleable --no-nest`) never recreate blocks. Verified: editing block A in
place leaves block B's comment intact (`comments list --page-id PAGE_ID
--with-context` still resolves it to its block); a `content set` on the same page
trashes the block (`archived: true`) and orphans the comment.
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

<principle name="Markdown Round-Trips Through Notion Unchanged">
`content set` followed by `get --include-blocks --markdown` returns the same
markdown. Do NOT pre-transform content to work around export damage, and do NOT
treat an exported body as lossy. Constructs Notion cannot store natively:

- **Images.** `![alt](https://…)` becomes an `external` `image` block whose
  `caption` holds the alt text and exports as `![alt](url)`. A src that is a
  local filesystem path (`![alt](/abs/scene.png)` or a path relative to the
  `--file` argument) is uploaded through Notion's File Upload API and becomes a
  Notion-hosted `image` block; if that file is missing or is not a supported
  image type, the command FAILS with exit 1 before mutating the page instead of
  storing the line as text (see Known Issue #9). Only a line that is entirely
  `![alt](src)` is an image; fenced code and inline references are left as-is.
  An `![alt](src)` whose src is neither an `http(s)` URL nor a filesystem path —
  a pipeline `IMAGE_PLACEHOLDER: …` marker, for example — is stored as a
  paragraph holding the original markdown line verbatim, so alt text and image
  syntax both survive. Nothing is rewritten to a `[Image: src]` string any more.
- **Code fences.** Notion stores `text` as `plain text`; the exporter maps it
  back to `text`. Every exported fence is a single-token info-string, so
  ` ```plain text ` can no longer reach a file.
- **Table column alignment.** Notion tables have no per-column alignment, so
  `| :--- | ---: |` is persisted in a `<!-- notion-table-align: … -->` marker
  paragraph placed immediately before the `table` block. The exporter consumes
  that paragraph and rebuilds the exact separator row; the marker never appears
  in exported markdown. It is written only when a column declares an explicit
  alignment, so plain `| --- |` tables add no extra block. Do NOT delete the
  marker paragraph in the Notion UI without deleting its table — the export
  fails loudly on an orphaned marker rather than dropping it.
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
- **users** — List and inspect workspace users; source of the user IDs `comments create --mention` resolves to
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

<principle name="Trashing a Whole Database">
`notion database delete DB_ID` moves a whole database container to the trash
(PATCH `/v1/databases/{id}` with `{"in_trash": true}`). Use `--force`/`-F` to
skip the confirmation prompt and `--restore` to bring it back.

Pick the right command for the right resource. These three are NOT
interchangeable:

| Goal | Command |
|------|---------|
| Trash a whole database container | `notion database delete DB_ID --force` |
| Archive one database row | `notion database page update PAGE_ID --archive` |
| Archive one standalone page | `notion pages delete PAGE_ID --force` |

`notion pages delete DB_ID` cannot trash a database. The page-retrieve endpoint
rejects a database ID, so it fails with "Could not find page with ID".

`database delete` accepts a database container ID or a data_source ID (the IDs
`notion database list` prints); a data_source ID resolves to its parent
container first. After a trash, `notion --no-cache database get DB_ID` reports
`"archived": true`.
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
   Page-level comments are unaffected. Notion-hosted images/files ARE preserved:
   the CLI re-uploads each hosted `image`/`video`/`pdf`/`file` block via the File
   Upload API before recreating it, so section images survive inside the toggle
   (see Known Issue #8). Use `--no-nest` when you must preserve block IDs and
   block-scoped comments.

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

### 1. Comment Listing Is Open/Unresolved Only

**Symptom:** A comment can be created successfully and remain retrievable by
`notion comments get COMMENT_ID`, while the Notion List comments endpoint omits
it. The API returns HTTP 200 with `has_more: false`, so pagination, cache, block
traversal, discussion grouping, and CLI response shaping cannot recover it.

**Cause:** Notion documents List comments as an open/unresolved-only endpoint and
documents that the public API cannot retrieve resolved comments or start a new
inline discussion. Some API versions nevertheless accept
`POST /comments` with `parent.block_id` and return a comment object. That object
can be individually retrievable without being enumerable.

**Fix:** `comments list` now fails before reading unless `--open-only` explicitly
accepts the API's narrower scope. With `--open-only --with-context`, every page
and block source is fully paginated; lookup/traversal/pagination failures remain
nonzero. `comments create --block-id` fails before writing. Use `--page-id` to add
a page comment or `--discussion-id` to reply to an existing inline discussion.

**Verification:** On page `3965d9c85b2b81239ef5d7ceba8f9b13`, comment
`3a05d9c8-5b2b-81a4-a658-001da3a6bb20` was retrievable with full text and live
parent block `39f5d9c8-5b2b-81b8-a3df-fec2c4c500e1`. The raw block list response
returned one sibling, `has_more: false`, and omitted the target. Tests cover the
fail-loud default, unsupported block creation, per-block pagination, and malformed
pagination.

**Recurrence Prevention:** Never describe Notion List comments output as all
comments. Require explicit `--open-only`, and never use `--block-id` to create a
new inline discussion.

### 2. Comment Context Reads Can Stall on Large Pages
**Symptom:** `notion comments list --page-id PAGE_ID --with-context --open-only --limit 100` can sit silent for more than a minute and write an empty output file while the process remains alive. After a heavy comment scan, a direct API check may return HTTP 429 with `Retry-After` (for example, 50 seconds).

**Cause:** Notion's public comments endpoint does not return this workspace's inline block comments from the parent page ID alone, so `--with-context` must recursively read page blocks and check comments on each block. The old CLI used only 5 workers and did not pass the configured worker count into the recursive block-read phase. Repeated comment scans can also hit Notion API rate limiting; the CLI honors `Retry-After`, so it may appear silent while it waits.

**Fix:** Use the explicit open-only command; the CLI defaults to 25 workers and applies that count to both recursive block reads and block comment lookups: `notion comments list --page-id PAGE_ID --with-context --open-only --limit 100 > comments.json`.

**Verification:** Confirm the output file contains valid JSON and `jq 'length' comments.json` returns the expected comment count. On the BricklinkBook page `3f5aaa654fc74a11bc0fc3865cdfcedd`, the no-manual-worker command returned 34 comments in about 25 seconds after the rate-limit window cleared.

**Recurrence Prevention:** Do not reintroduce silent exception suppression or a low default worker count in comment context reads. `--max-workers` remains available for diagnostics, but large-page review workflows should be fast by default. Avoid repeated parallel comment scans against the same large page; if 429 appears, wait the `Retry-After` period before rerunning.

### 3. Comment Target Block Is Available

**Symptom:** `notion comments list --page-id PAGE_ID --with-context --open-only` returns open inline comments and parent block context. That parent block is the selected comment target for review work. Older report workflows treated `[table_row block]` as missing comment context.

**Cause:** Notion's public comments API returns comment metadata, parent, discussion ID, author/timestamps, `rich_text`, attachments, and display name. It exposes the parent block, which the CLI reports as `context` and `selected_block`. The CLI can derive nearby context by reading adjacent blocks. Separately, older CLI context extraction only read `rich_text`, so table rows and other non-`rich_text` blocks produced weak context like `[table_row block]`.

**Fix:** Use the parent block as the comment target. Use `notion comments list --page-id PAGE_ID --with-context --open-only --limit 100` for parent block and nearby block context. Current JSON output includes `context`, `context_before`, `context_after`, `context_around`, `selected_block`, and `selected_block_status`.

**Verification:** A raw `GET /comments/{comment_id}` probe on BricklinkBook comment `3535d9c8-5b2b-800a-a540-001dccf638dc` returned parent block metadata. Unit tests cover table-row context extraction and selected block output.

**Recurrence Prevention:** Review workflows must use the parent block as the comment target and use parent/nearby block context for revision planning.

### 4. Replace-Section Local Images and Dry Runs
**Symptom:** `notion pages content replace-section PAGE_ID --heading "## Section" --file section.md` did not upload local Markdown images, so replacement content containing `![alt](local.png)` could not persist image blocks correctly. The first repair attempt also uploaded images during `--dry-run`.

**Cause:** `replace-section` parsed Markdown with `text_to_blocks(content)` directly, while the `database page content` Markdown paths processed local images first and passed `image_uploads` into `text_to_blocks`. Image processing was initially added before the dry-run branch, which made dry runs perform Notion file uploads. (This entry originally claimed `content append` also processed images. That was true only of `database page content append`; every `pages …` Markdown path still dropped local images — see Known Issue #9.)

**Fix:** `replace-section` calls the shared Markdown image processor whenever `--dry-run` is false (for `--text` as well as `--file` since the #9 repair), then calls `text_to_blocks(content, image_uploads=image_uploads)`.

**Verification:** In `/Users/adam/Dropbox/GitRepos/cli-tools/notion`, `uv run --with pytest python -m pytest tests -q` passes. Tests cover local image upload wiring and prove `--dry-run` does not call image upload processing.

**Recurrence Prevention:** Any future Markdown-processing page command must match the append/set behavior for local images and must keep `--dry-run` read-only before making API upload calls.

### 5. `pages blocks list` Truncated at 100 Blocks
**Symptom:** `notion pages blocks list --page-id PAGE_ID` returned only the first 100 child blocks on pages with more than 100 blocks, with no warning. On page `3825d9c85b2b8074bbe3ed8aa65c9f91` it returned 100 blocks / 14 `heading_2`, while `notion pages get PAGE_ID -b -m` rendered all 16 `heading_2` sections from the same page. `--recursive` was also affected: it still capped the top-level list at 100.

**Cause:** The Notion children endpoint (`GET /v1/blocks/{id}/children`) defaults to `page_size=100` and returns `has_more` + `next_cursor`. The client method `get_block_children_all` already paginates fully when called with `limit=None`, but the `blocks list` command hard-coded `--limit` to a default of `100`, passed that as the fetch limit (non-recursive), AND re-sliced the result with `formatted[:limit]` / `blocks[:limit]` in every output path — so even the recursive run (which fetched all top-level blocks) was re-truncated to 100 before output.

**Fix:** `--limit` now defaults to `None` (return the COMPLETE list). The command fetches with `limit=None` by default (full `has_more`/`next_cursor` pagination via `get_block_children_all`) and applies a client-side cap only when `--limit` is explicitly provided. One code path, no fallback. Related: `pages blocks append --after` now reports only the number of blocks actually inserted (`len(blocks)`) instead of `len(results)`; Notion echoes the entire repositioned tail in the `--after` response, which made the old count overstate (e.g. inserting 3 reported 113). The `--after` path sends a single PATCH and never re-fetches or recreates the existing tail, so no blocks are dropped past position 100.

**Verification:** After the fix on page `3825d9c85b2b8074bbe3ed8aa65c9f91` (read-only), `notion pages blocks list --page-id 3825d9c85b2b8074bbe3ed8aa65c9f91` returns 117 blocks / 16 `heading_2`, and `... -m` emits 16 `## ` headings — matching `notion pages get 3825d9c85b2b8074bbe3ed8aa65c9f91 -b -m`. `--limit 50` correctly caps at 50. On a scratch 111-block page, inserting 3 blocks with `--after` a block at index 105 reported `blocks_created: 3`, grew the page to 114, and lost 0 original blocks. Regression tests in `tests/test_blocks_list_pagination.py` cover multi-page `has_more`/`next_cursor` fetches, the uncapped default, the explicit-limit cap, the recursive path, and the `--after` count.

**Recurrence Prevention:** Any command that lists Notion children must paginate the full `has_more`/`next_cursor` sequence by default and must not impose a hidden default cap on `list` output. `--limit` is an explicit opt-in cap only. Never count `len(results)` from an `--after` append as "created" — Notion returns the full repositioned tail there; the inserted count is `len(input_blocks)`.

### 6. `pages duplicate` Failed on Column Layouts
**Symptom:** `notion pages duplicate PAGE_ID --title "..."` on a page containing a `column_list` failed with exit 1: `400 - body.children[N].column_list.children[0].column.children should be defined, instead was undefined`. Progress reached "[5] Uploading N blocks..." then the API rejected the payload.

**Cause:** `_upload_blocks_with_nesting` in `notion_cli/client.py` treated every direct child of a child-required block the same way — it popped each child's children to re-attach them after creation. But a `column` inside a `column_list` is itself a child-required type: Notion refuses to create a childless column, so popping the column's content sent `column: {}` and the 400 rejected the whole request. Separately, `_apply_text_replacements` only recursed block-level `children`, so `--replace` never reached content nested inside cleaned container blocks (columns, toggles, callouts) whose children live at `block[type]["children"]`.

**Fix:** New `_pop_optional_descendants` helper keeps the required descendant chain (`column_list` → `column` → content) inline in the creation payload and pops children only from descendants that can be created childless, recording each pop as an index path. The inline re-attachment loop resolves those paths against the created blocks by fetching server children level by level and raises `ClientError` on any path mismatch instead of silently dropping content. `_apply_text_replacements` now recurses via `_get_children`, covering both block-level and type-nested children. Dead code superseded by this path (`_prepare_blocks_for_upload`, `_get_block_children_key`) was removed.

**Verification:** Duplicating page `9cb674489a004afd83df94b9dfc26756` (5-column `column_list` + callout with children) succeeded; the new page's `column_list` contained all 5 columns, each with its heading, divider, and list items, and the callout kept its 8 children. Regression tests in `tests/test_page_duplicate_columns.py` cover inline column payload shape, nested sub-bullet re-attachment by index path, callout append-after-creation, and `--replace` reaching type-nested children. Full suite: 107 passed; `test-cli-tool.sh --cli-name notion`: 288 passed, 0 failed.

**Recurrence Prevention:** When uploading blocks, never pop the children of a block whose type is in `_CHILD_REQUIRED_TYPES` (`column_list`, `column`, `table`, `synced_block`) — the required chain must stay inline in the creation payload. Any new recursive block walker must use `_get_children`/`_pop_children` so both block-level and API-2025-09-03 type-nested children locations are handled.

### 7. `pages duplicate` Omitted Child Pages and Their Content

**Symptom:** `notion pages duplicate PAGE_ID` reported success after uploading the
ordinary top-level blocks, but the destination contained no `child_page` blocks
and none of the nested subpage content.

**Cause:** The creation cleaner classified `child_page` as uncreatable through
the block-children endpoint and silently filtered it. In addition, recursive
block reads caught subtree API failures and substituted an empty child list, so
a failed child-page read was indistinguishable from a genuinely empty page.

**Fix:** Duplication now preflights the complete recursively fetched source tree
before creating a destination. It uploads contiguous ordinary-block runs and
recreates each `child_page` with the pages endpoint under the new parent, then
recurses through all nested subpages while preserving source order. Recursive
read failures propagate, and other block types the API cannot recreate cause a
clear pre-mutation error instead of silent omission.

**Verification:** `tests/test_page_duplicate_child_pages.py` covers a root page,
child page, nested grandchild page, content at every level, ordering around the
child page, unsupported-block preflight, and propagation of child-page read
errors. The Notion unit suite passes 120 tests; `test-cli-tool.sh --cli-name
notion` passes with 0 failures.

**Recurrence Prevention:** Never pass `child_page` through
`append_block_children`; create it through `POST /pages` under the duplicated
page and recurse. Recursive export/duplicate reads are all-or-nothing and must
never replace a failed subtree with `[]`.

### 8. Toggle-Flip Re-Parenting Destroyed Notion-Hosted Images

**Symptom:** `notion pages blocks update HEADING_ID --toggleable` (auto-nesting a
heading's section under the new toggle) destroyed any Notion-hosted `image` block
in that section. At depth-2 it failed with `400 -
body.children[N]...image.file_upload should be defined`; at depth-1 it silently
recreated the image with an empty URL, rendering `![]()`.

**Cause:** `_nest_section_under_heading` (in
`notion_cli/commands/page.py`) hydrated the section blocks with
`_fetch_children_parallel`, then ran them straight through
`client._clean_blocks_recursive`. For a Notion-hosted image (`image.type ==
"file"`), `_clean_block_for_creation` rewrites the block to `image.external`
using the signed, EXPIRING `prod-files-secure.s3…` URL. Notion rejects (or
empties) that expiring URL on create. The proven `pages duplicate` path already
calls `client._reupload_file_blocks(raw_blocks)` before cleaning; the toggle-flip
path never did.

**Fix:** `_nest_section_under_heading` now calls
`client._reupload_file_blocks(section_blocks, progress_callback)` AFTER hydrating
children and BEFORE cleaning, mirroring `duplicate`. Each hosted
`image`/`video`/`pdf`/`file` block is downloaded and re-uploaded via the File
Upload API and recreated as a native `file_upload` reference inside the toggle.
`_reupload_file_blocks` was also hardened to FAIL LOUD (raise `ClientError`)
instead of swallowing a download/upload error and degrading to a broken expiring
`external` URL — the original section blocks are never deleted when re-upload
fails, so no data is lost. One path, no fallback.

**Verification:** On a scratch page, an H2 section with a native `file` image was
flipped with `--toggleable`. Pre-fix (fix stashed) the image rendered `![]()`
(destroyed); post-fix the image survived as an `image.file` child of the toggle
with a valid hosted URL (freshly re-uploaded temp filename). Regression tests in
`notion/tests/test_toggle_nest_image_reupload.py` cover depth-1 and depth-2
re-upload-before-clean and the fail-loud-keeps-originals behavior. Notion suite:
137 passed; `test-cli-tool.sh --cli-name notion`: 315 passed, 0 failed.

**Recurrence Prevention:** Any path that re-creates existing blocks containing
Notion-hosted files (`image`/`video`/`pdf`/`file` with `type == "file"`) must
call `_reupload_file_blocks` BEFORE `_clean_blocks_recursive`, never rely on the
expiring `image.external` fallback, and must fail loud rather than silently
recreate a broken external file. (Block-scoped comments on re-parented blocks
still change IDs and drop — that is unchanged; use `--no-nest` to preserve them.)

### 9. `pages` Markdown Commands Silently Dropped Local Images

**Symptom:** `notion pages content set PAGE_ID --file article.md` exited 0 and
reported `blocks_created`, but every `![alt](/absolute/path.png)` in the input
landed as a `paragraph` block holding the literal markdown text instead of an
`image` block. `notion pages blocks list --page-id PAGE_ID --table` showed
`type=paragraph` rows beginning `![Scene 1:`. The same silent drop affected
`pages content append`, `pages blocks append`, `pages create --content-file`,
and `database page create --content-file`. A missing or misspelled image path
produced no error at all.

**Cause:** The image processor lived only in
`notion_cli/commands/database.py` and was wired into just three call sites
(`database page content append`, `database page content set`, and — via a lazy
`from .database import _process_markdown_images` — `pages content
replace-section`). Every other markdown path called
`text_to_blocks(content, is_toggleable=...)` with no `image_uploads` argument
(`page.py` lines 400, 1223, 1324, 2391, 2395; `database.py` line 1575). Without
that mapping `text_to_blocks` has no file_upload ID for a local src and takes
its verbatim-paragraph branch. The old processor also degraded on failure: a
missing file, unsupported extension, or failed upload printed a warning and
continued, which is exactly how the drop stayed silent.

**Fix:** The processor moved to a single shared module,
`notion_cli/markdown_images.py` (`process_markdown_images`), and every markdown
path now calls it and passes `image_uploads` into `text_to_blocks`:
`pages content set`, `pages content append`, `pages content replace-section`
(non-dry-run, now for `--text` as well as `--file`), `pages blocks append`
(`--text` and `--file`), `pages create --content-file`,
`database page content set`, `database page content append`, and
`database page create --content-file`. The processor is fail-loud: a referenced
local file that does not exist, or that is not a Notion-supported image type,
prints every bad reference and exits 1; an upload error propagates. Processing
always runs BEFORE the mutation, so `content set` never clears a page it cannot
repopulate, matching Known Issue-style pre-clear validation for oversize blocks.
The scanner matches `text_to_blocks` exactly: only a line that is entirely
`![alt](src)` counts, fenced code is skipped, `http(s)` srcs stay external, and
a src carrying a non-http URI scheme (a pipeline `IMAGE_PLACEHOLDER: …` marker)
is left alone so it still round-trips as a verbatim paragraph. `pages import`
(.docx only) and `pages duplicate` (Notion blocks only) parse no markdown and
were already correct.

**Verification:** Live on scratch page `3bf5d9c85b2b8137bc4eca93616b2d81`,
`pages content set --file` with two absolute PNG paths produced two `image`
blocks; `pages blocks get` on one returned `image.type == "file"` with a
`prod-files-secure.s3…` URL, while the `IMAGE_PLACEHOLDER:` line and a literal
`[IMAGE: …]` bracket line stayed paragraphs. The same page proved
`content append`, `blocks append`, `pages create --content-file`, and
`replace-section` each create image blocks. A missing-path run exited 1 with
`Local image file(s) referenced by the markdown do not exist` and left all 8
existing blocks in place. Notion unit suite: 238 passed;
`test-cli-tool.sh --cli-name notion`: 332 passed, 0 failed. Regression tests
live in `notion/tests/test_markdown_image_uploads.py`.

**Recurrence Prevention:** Any command that converts markdown to Notion blocks
must call `process_markdown_images` from `notion_cli/markdown_images.py` and
pass the result into `text_to_blocks(content, image_uploads=...)`. Never call
`text_to_blocks` on user markdown without that mapping, never warn-and-continue
on a missing or unuploadable local image, and always process images before the
command's first mutating API call.

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
