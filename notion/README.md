# Notion CLI Guide

## DESCRIPTION

The `notion` CLI provides a command-line interface for Notion API with database query filtering.

Use it when you need scriptable reads, exports, or evidence collection without opening the service UI.

## Overview

The Notion CLI provides access to:
- **Auth** - Manage Notion integration tokens
- **Database** - Query databases, get schemas, manage database pages
- **Template** - List and manage database page templates
- **Field** - Manage database field schemas (properties)
- **Pages** - Query and manage standalone pages (not in databases)
- **Page files** - Download Notion-hosted or external file attachments
- **Official skills** - Download Notion's published Skills for Claude ZIP files
- **Comments** - Manage comments on pages and blocks

## Authentication

Authentication uses Notion integration tokens.

### Login

```bash
notion auth login
notion auth login --token <secret_token>
```

### Check Status

```bash
notion auth status
notion auth status
```

### Logout

```bash
notion auth logout
```

---

## Database Commands

Query and inspect databases.

### List Pages (Query Database)

```bash
notion database page list -d <database-id>
notion database page list -d <database-id> --filter "Status:eq:Done" --table
notion database page list -d <database-id> --filter "Publish Date:gte:2026-07-20"
```

**Options:**
| Option | Description |
|--------|-------------|
| `-d, --database-id` | The database ID to query (required) |
| `-t, --table` | Display as formatted table |
| `-f, --filter` | Filter using `field:op:value` (repeatable, AND logic) |
| `-p, --properties` | Quoted comma-separated list of properties to include, for example `"id,Name,Website,Contact Email"` |
| `-l, --limit` | Maximum number of results |
| `--sort` | Sort by property (format: 'property' or 'property:asc/desc') |
| `--data-source` | Specific data_source ID when the database holds multiple data sources |

**Filter operators.** The command reads the database schema and builds a Notion
filter for the property's type. An unknown property name, or an operator the
property type does not support, fails locally before any API call. Omitting the
operator means `eq` (`--filter "Status:Done"`).

| Property type | Operators |
|---------------|-----------|
| Text, title, url, email, phone | `eq`, `ne`, `in`, `nin`, `like`, `ilike`, `contains`, `null`, `notnull` |
| Status, select, multi_select | `eq`, `ne`, `in`, `nin`, `contains`, `null`, `notnull` |
| Number | `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `nin`, `null`, `notnull` |
| People, files, relation | `null`, `notnull` |
| Created by, created time, last edited by, last edited time | `null`, `notnull` |
| Checkbox | `eq`, `ne` |
| Date | `equals`, `before`, `after`, `on_or_before`, `on_or_after`, `this_week`, `past_week`, `past_month`, `past_year`, `next_week`, `next_month`, `next_year`, `is_empty`, `is_not_empty` |

`null` and `notnull` become Notion's `is_empty` and `is_not_empty` conditions,
nested under the property's own type. A property type that has no such
condition, such as `checkbox`, `formula`, or `rollup`, fails locally and names
the operators it does support.

```bash
notion database page list -d DB_ID --filter "Keywords:null"
notion database page list -d DB_ID --filter "Category:notnull"
```

Date properties use Notion's own date operators. These aliases also work:
`eq`=`equals`, `gt`=`after`, `gte`=`on_or_after`, `lt`=`before`,
`lte`=`on_or_before`, `null`=`is_empty`, `notnull`=`is_not_empty`.

```bash
notion database page list -d DB_ID --filter "Publish Date:on_or_after:2026-07-20"
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

### Get Schema

Get database property definitions.

```bash
notion database schema <database-id>
notion database schema <database-id>
```

### Create Database

Create a new database under a parent page (API 2025-09-03). The parent must be
a page ID; Notion rejects database and data_source IDs as database parents. The
schema is supplied via raw JSON (`--properties`, the Notion
`initial_data_source.properties` object) and/or convenience flags. A title
property is always present: if `--properties` does not define one, a title
column named by `--title-property` (default `Name`) is added.

```bash
notion database create <parent-page-id> --title "Tasks"
notion database create <parent-page-id> --title "Tasks" \
    --status "Phase:Todo|Doing|Done" --select "Priority:High|Low" --date "Due"
notion database create <parent-page-id> --title "Tasks" --inline \
    --relation "Project:TARGET_DATA_SOURCE_ID"
notion database create <parent-page-id> --title "Tasks" \
    --properties '{"Name": {"title": {}}, "Notes": {"rich_text": {}}}'
```

**Options:**
| Option | Description |
|--------|-------------|
| `-t, --title` | The database title (required) |
| `--title-property` | Name of the title property to create (default `Name`) |
| `--inline / --no-inline` | Create the database inline in the parent page |
| `-p, --properties` | Raw JSON for `initial_data_source.properties` (merged with flags) |
| `--text`, `--number`, `--date`, `--checkbox`, `--url`, `--email`, `--phone`, `--people`, `--files` | Add a simple property (format: `Name`; repeatable) |
| `--select`, `--multi-select`, `--status` | Add a choice property (format: `Name` or `Name:Opt1\|Opt2`; repeatable) |
| `--relation` | Add a relation property (format: `Name:target_data_source_id`; repeatable) |
| `--relation-type` | `dual_property` (default) or `single_property` for `--relation` |

Relation properties use the **target's data_source ID** (not a database container
ID), per Notion API 2025-09-03. The command prints the new database container
`id`, its `data_sources` (id + name), the `data_source_ids`, and the `url`.

### Delete Database

Move a whole database container to the trash, or restore it. Notion does not
hard-delete a database; this sends `PATCH /databases/{id}` with `in_trash`.
`notion pages delete` cannot do this, because the page-retrieve endpoint
rejects a database ID. To archive one row instead, use
`notion database page delete <page-id>`.

```bash
notion database delete <database-id>
notion database delete <database-id> --force
notion database delete <database-id> --restore --force
```

**Options:**
| Option | Description |
|--------|-------------|
| `--restore` | Restore the database from the trash instead of trashing it |
| `-F, --force` | Skip the confirmation prompt |

Accepts a database container ID or a data_source ID (the IDs that
`notion database list` prints); a data_source ID resolves to its parent
container. The command prints the container `id`, `title`, `in_trash`,
`archived`, and `url`.

---

## Page Commands

Manage individual pages.

### Get Page

```bash
notion database page get <page-id>
notion database page get <page-id> --include-blocks --markdown
```

**Options:**
| Option | Description |
|--------|-------------|
| `-b, --include-blocks` | Include page content blocks |
| `-m, --markdown` | Output blocks as markdown (requires --include-blocks) |
| `-o, --out-file` | Write markdown to file (requires `--include-blocks --markdown`) |

### Create Page

```bash
notion database page create <database-id> --title "New Page"
notion database page create <database-id> -t "Task" -s "In Progress"
notion database page create <database-id> -t "Bug Report" --from-template default
notion database page create <database-id> -t "Bug Report" --from-template TEMPLATE_ID
```

**Options:**
| Option | Description |
|--------|-------------|
| `-t, --title` | **(Required)** Page title |
| `-s, --status` | Set status property |
| `--select` | Set select property |
| `-f, --content-file` | File containing markdown content for body |
| `--blocks-file` | Notion JSON blocks file (from `export --format notion-json`) |
| `--from-template` | Create from template (use template ID or 'default') |
| `-p, --properties` | Raw JSON properties object |

**Note:** `--content-file`, `--blocks-file`, and `--from-template` are mutually exclusive.

### Update Page

```bash
notion database page update <page-id> --status "Done"
notion database page update <page-id> --archive
```

**Options:**
| Option | Description |
|--------|-------------|
| `-s, --status` | Set status property |
| `--select` | Set select property |
| `--text` | Set rich_text property |
| `--checkbox` | Set checkbox property |
| `--number` | Set number property |
| `--url` | Set url property |
| `--archive/--restore` | Archive or restore the page |

### Delete Page

Archive a page (Notion's equivalent of delete).

```bash
notion database page delete <page-id>
```

---

## Page Content Commands

Manage blocks within pages.

### Append Content

```bash
notion database page content append <page-id> --text "Hello World"
notion database page content append <page-id> --file content.md
```

**Options:**
| Option | Description |
|--------|-------------|
| `-t, --text` | Text/markdown content to append |
| `-f, --file` | File containing content to append |
| `-p, --paragraph` | Add a simple paragraph block |

### Set Content (Replace)

Clears existing content and replaces it.

```bash
notion database page content set <page-id> --file content.md
notion database page content set <page-id> --json-file blocks.json
```

**Options:**
| Option | Description |
|--------|-------------|
| `-t, --text` | Text/markdown content to set |
| `-f, --file` | File containing markdown content |
| `--json-file` | Notion JSON blocks file (from `export --format notion-json`) |

Note: `--text`, `--file`, and `--json-file` are mutually exclusive.

### Clear Content

```bash
notion database page content clear <page-id>
```

---

## Template Commands

Manage database page templates.

### List Templates

```bash
notion database template list <database-id>
notion database template list <database-id>
notion database template list <database-id> --name "Bug"
```

**Options:**
| Option | Description |
|--------|-------------|
| `-n, --name` | Filter templates by name (case-insensitive) |
| `-l, --limit` | Maximum number of results (default: 100) |

### Get Template

```bash
notion database template get <database-id> <template-id>
```

---

## Field Commands

Manage database field schemas (properties).

### List Fields

```bash
notion field list <database-id>
notion field list <database-id>
notion field list <database-id> --filter "type:select"
```

**Options:**
| Option | Description |
|--------|-------------|
| `-l, --limit` | Maximum number of fields to return (default: 100) |
| `-f, --filter` | Filter fields (e.g., type:select, name:like:%Status%) |

### Add Field

```bash
notion field add <database-id> "Priority" --type select --options "High,Medium,Low"
notion field add <database-id> "Notes" --type rich_text
notion field add <database-id> "Due Date" --type date
notion field add <database-id> "Score" --type number --number-format percent
notion field add <database-id> "Imports" --type relation --relation-database <target-id>
```

**Options:**
| Option | Description |
|--------|-------------|
| `-t, --type` | **(Required)** Field type (rich_text, number, select, multi_select, status, date, etc.) |
| `-o, --options` | Comma-separated options for select/multi_select/status types |
| `--formula-expression` | Expression for formula type |
| `--relation-database` / `--relation-data-source` | For relation type: the TARGET's database container ID OR data_source ID. Resolved to the target's `data_source_id` (API 2025-09-03). |
| `--relation-type` | `dual_property` (default) or `single_property` for relation fields |
| `--number-format` | Format for number type |

### Rename Field

```bash
notion field rename <database-id> "Old Name" "New Name"
```

### Update Field

```bash
notion field update <database-id> "Priority" --name "Urgency"
notion field update <database-id> "Score" --number-format percent
notion field update <database-id> "Status" --options "Todo,In Progress,Done"
notion field update <database-id> "Imports" --relation-database <new-target-id>
```

**Options:**
| Option | Description |
|--------|-------------|
| `-n, --name` | New name for the field |
| `-o, --options` | Replace options for select/multi_select/status |
| `--number-format` | Format for number type |
| `--formula-expression` | Expression for formula type |
| `--relation-database` / `--relation-data-source` | For relation fields: repoint to the TARGET's container/data_source ID (resolved to `data_source_id`) |
| `--relation-type` | Change a relation field's type (`dual_property` or `single_property`) |

### Add Option to Field

Add an option to a select, multi_select, or status field.

```bash
notion field option add <database-id> "Priority" "Critical"
notion field option add <database-id> "Status" "Blocked" --color red
```

**Options:**
| Option | Description |
|--------|-------------|
| `-c, --color` | Color for the option (default, gray, brown, orange, yellow, green, blue, purple, pink, red) |

### Delete Field

```bash
notion field delete <database-id> "Field Name"
notion field delete <database-id> "Field Name" --force
```

**Warning:** This deletes all data in this field across all pages!

---

## Official Notion Skills

List, inspect, and download the ZIP attachments published on Notion's official
`Notion Skills for Claude` page. These commands are anonymous and do not require
the page to be shared with your integration.

```bash
notion skills list --table
notion skills list --filter "name:contains:meeting" --properties id,name
notion skills get 28ea4445-d271-8016-8a2c-d0b69f68ad6b
notion skills download 28ea4445-d271-8016-8a2c-d0b69f68ad6b --output ./notion-skills
```

`skills list` supports the standard `--filter/-f`, `--limit/-l`,
`--properties/-p`, and `--table/-t` options. `skills get` supports
`--table/-t`. `skills download` requires `--output/-o` and supports
`--force/-F` and `--table/-t`.

The skill ID is the UUID of the skill's file block on the live Notion page.
Notion uses that same UUID as the attachment signing permission record. The CLI
rejects duplicate IDs while parsing the catalog, so each ID resolves to exactly
one attachment. `skills download` signs and downloads only the requested ID.

Notion's documented public API has no skills catalog or page-export endpoint.
These commands read the public page through Notion's anonymous web JSON endpoints
and resolves its attachment references through `getSignedFileUrls`. Those
endpoints are not part of Notion's documented public API; schema changes fail
the command clearly instead of producing partial or guessed downloads.

---

## Pages Commands

Query and manage standalone pages (not in databases).

### Search Pages

```bash
notion pages search "meeting notes"
notion pages search "project"
notion pages search "draft" --sort desc --limit 10
```

**Options:**
| Option | Description |
|--------|-------------|
| `--sort` | Sort direction by last edited time (asc/desc) |
| `-l, --limit` | Maximum number of results (default: 100) |

### List All Pages

```bash
notion pages list
notion pages list
notion pages list --sort desc --limit 20
```

**Options:**
| Option | Description |
|--------|-------------|
| `--sort` | Sort direction by last edited time (asc/desc) |
| `-l, --limit` | Maximum number of results (default: 100) |

### Get Page

```bash
notion pages get <page-id>
notion pages get <page-id> --include-blocks --markdown
notion pages get <page-id> -b -m --out-file content.md
```

**Options:**
| Option | Description |
|--------|-------------|
| `-b, --include-blocks` | Include page content blocks |
| `-m, --markdown` | Output blocks as markdown (requires --include-blocks) |
| `-o, --out-file` | Write markdown to file (requires `--include-blocks --markdown`) |

### Create Page

Create a new page under an existing parent page.

```bash
notion pages create <parent-page-id> --title "New Page"
notion pages create <parent-page-id> -t "Notes" --content-file notes.md
notion pages create <parent-page-id> -t "Project" --icon "emoji:rocket"
```

**Options:**
| Option | Description |
|--------|-------------|
| `-t, --title` | **(Required)** Page title |
| `-f, --content-file` | File containing markdown content for body |
| `--icon` | Page icon (format: `emoji:rocket` or `url:https://...`) |

### Update Page

```bash
notion pages update <page-id> --title "New Title"
notion pages update <page-id> --icon "emoji:star"
notion pages update <page-id> --archive
notion pages update <page-id> --restore
```

**Options:**
| Option | Description |
|--------|-------------|
| `-t, --title` | New page title |
| `--icon` | Page icon (format: `emoji:rocket` or `url:https://...`) |
| `--archive/--restore` | Archive or restore the page |

### Duplicate Page

Duplicate a page including all blocks and rich formatting (callouts, columns, colors, bold).

```bash
notion pages duplicate <page-id>
notion pages duplicate <page-id> --title "New Copy"
notion pages duplicate <page-id> --title "2026 Contract" --replace "2025:2026" --replace "$99,400:$84,000"
notion pages duplicate <page-id> --to-database <target-db-id>
notion pages duplicate <page-id> --properties '{"Status": {"status": {"name": "Draft"}}}'
```

**Options:**
| Option | Description |
|--------|-------------|
| `-t, --title` | New page title (defaults to "Copy of {original}") |
| `-p, --properties` | Raw JSON property overrides (Notion API format) |
| `--to-database` | Target database ID (defaults to same database) |
| `-r, --replace` | Find/replace in block text (format: `old:new`). Repeatable. |

### Export Page

Export a page to PDF, HTML, Markdown, or Notion JSON.

```bash
notion pages export <page-id> -o document.pdf
notion pages export <page-id> -o content.md --format md
notion pages export <page-id> -o blocks.json --format notion-json
```

**Options:**
| Option | Description |
|--------|-------------|
| `-o, --output` | **(Required)** Output file path |
| `-f, --format` | Export format: `pdf`, `html`, `md`, or `notion-json` (default: pdf) |

The `notion-json` format exports raw Notion block structures preserving all formatting. The exported JSON can be re-imported with `content set --json-file` or `blocks append --json-file`.

### Download Page Files

Download every file block attached to a page, including nested file blocks.
This is the supported API path for downloadable Notion-hosted attachments such
as skill `.zip` files. Notion-hosted URLs are refreshed immediately before the
download because the API signs them for one hour.

```bash
notion pages files download <page-id> --output ./skills
notion pages files download <page-id> -o ./skills --table
notion pages files download <page-id> -o ./skills --force
```

| Option | Description |
|--------|-------------|
| `-o, --output` | **(Required)** Destination directory |
| `-t, --table` | Display downloaded-file metadata as a table |
| `-F, --force` | Overwrite files that already exist |

The page must be shared with the configured Notion integration. A page being
public on the web does not grant API access to an integration. The Notion API
does not expose a skills catalog or a page-export/download endpoint; this
command follows file-block URLs returned by `GET /v1/blocks/{block_id}/children`.

### Delete Page

Archive a page (Notion's equivalent of delete).

```bash
notion pages delete <page-id>
notion pages delete <page-id> --force
```

---

## Pages Content Commands

Manage blocks within standalone pages.

### Append Content

```bash
notion pages content append <page-id> --text "Hello World"
notion pages content append <page-id> --file content.md
notion pages content append <page-id> --file outline.md --is-toggleable
```

**Options:**
| Option | Description |
|--------|-------------|
| `-t, --text` | Text/markdown content to append |
| `-f, --file` | File containing content to append |
| `-p, --paragraph` | Add a simple paragraph block |
| `--is-toggleable` | Make every `heading_1`/`2`/`3` produced from markdown into a toggle heading |

### Set Content (Replace)

Clears existing content and replaces it.

```bash
notion pages content set <page-id> --file content.md
notion pages content set <page-id> --json-file blocks.json
notion pages content set <page-id> --file outline.md --is-toggleable
```

The new payload is transformed and validated **before** the page is cleared, so a
rejected block can never leave the page empty. Notion limits each rich-text value
to 2000 characters and each rich-text array to 100 elements; any oversize
paragraph, heading, list item, quote, callout, or code block is automatically
split on word boundaries (and overflowed into sibling blocks when needed) so the
original text is preserved. This applies to `--text`, `--file`, and `--json-file`
input. Content larger than Notion's 100-block-per-request limit is still chunked
and uploaded sequentially.

**Options:**
| Option | Description |
|--------|-------------|
| `-t, --text` | Text/markdown content to set |
| `-f, --file` | File containing markdown content |
| `--json-file` | Notion JSON blocks file (from `export --format notion-json`) |
| `--is-toggleable` | Make every `heading_1`/`2`/`3` produced from markdown into a toggle heading (markdown input only; ignored with `--json-file`) |

Note: `--text`, `--file`, and `--json-file` are mutually exclusive.

### Markdown Round-Trip Fidelity

Writing markdown with `content set` and reading it back with `get --markdown`
returns the same markdown. These constructs have no direct Notion equivalent and
are handled explicitly instead of being degraded:

| Construct | Notion storage | Read back as |
|-----------|----------------|--------------|
| `![alt](url)` with an `http(s)` src | external `image` block, `caption` = alt text | `![alt](url)` |
| `![alt](path)` with a local filesystem src (absolute, or relative to the `--file` argument) | the file is uploaded through Notion's File Upload API and stored as a Notion-hosted `image` block, `caption` = alt text | `![alt](hosted-url)` |
| `![alt](src)` with a src that is neither a URL nor a filesystem path (for example a pipeline `IMAGE_PLACEHOLDER: ...` marker) | `paragraph` holding the original markdown line verbatim | the identical `![alt](src)` line |
| Code fence language | Notion's enum value (`text` is stored as `plain text`) | a single-token markdown info-string (`plain text` -> `text`) |
| Table column alignment (`&#124; :--- &#124; ---: &#124;`) | a `<!-- notion-table-align: ... -->` marker paragraph immediately before the `table` block | the original separator row |

Local images are uploaded by every markdown-accepting command (`pages content
set`, `pages content append`, `pages content replace-section`, `pages blocks
append`, `pages create --content-file`, `database page content set`, `database
page content append`, `database page create --content-file`). Only a line that
is entirely `![alt](src)` counts as an image; fenced code blocks and inline
references are left untouched. If a referenced local file does not exist, or is
not a Notion-supported image type, the command prints every bad reference and
exits 1 **before** any page mutation — `content set` never clears a page it
cannot repopulate.

The table alignment marker is written **only** when at least one column declares
an explicit alignment, so a table with a plain `&#124; --- &#124;` separator
produces no extra block. The exporter consumes the marker, so it never appears in exported
markdown. A marker left without its table (the table was deleted in the Notion
UI) fails the export with an explicit error rather than being dropped.

A Notion code language that is not a single-token markdown identifier and has no
entry in `MARKDOWN_FENCE_LANGUAGE_ALIASES` also fails the export, because
writing it verbatim would produce a fence a highlighter mis-reads.

### Replace Section

Replaces one section matched by an exact markdown heading. The command only
replaces blocks from the matched heading through the block before the next
heading at the same or higher level. It does not rebuild following page
content, including when the matched section is the first block on the page.

```bash
notion pages content replace-section <page-id> --heading "## My Section" --file section.md
notion pages content replace-section <page-id> --heading "# Introduction" --text "# Introduction\n\nUpdated body"
notion pages content replace-section <page-id> --heading "### Details" --file details.md --dry-run
```

**Options:**
| Option | Description |
|--------|-------------|
| `-h, --heading` | Exact markdown heading to replace, including `#`, `##`, or `###` |
| `-n, --occurrence` | Which match to target when the heading repeats (1-based, page order) |
| `-u, --under` | Scope the search to the section under this higher-level heading |
| `-t, --text` | Markdown content for the replacement section |
| `-f, --file` | File containing markdown content for the replacement section |
| `--dry-run` | Show the section replacement plan without editing Notion |

#### Repeated headings

A page can carry the same heading text in several places — `### Your Actions`
under four different `## Phase N` headings, for example. When the heading matches
more than once and the call did not disambiguate, the command **exits 1 without
touching the page** and lists every candidate with its block range and the
enclosing higher-level heading:

```
Warning: '### Your Actions' matches 4 sections on page 2de5d9c8.... Refusing to guess which one to replace:
  --occurrence 1: blocks 12-18 of 96, under ## Phase 1: Topic Intake
  --occurrence 2: blocks 27-34 of 96, under ## Phase 2: AI Review
  --occurrence 3: blocks 51-57 of 96, under ## Phase 3: Writer Assignment
  --occurrence 4: blocks 70-79 of 96, under ## Phase 4: Draft Submission
Re-run with --occurrence N, or --under '<parent heading>' to scope the search to one parent section.
```

Pick one of the two disambiguators:

```bash
notion pages content replace-section <page-id> --heading "### Your Actions" --occurrence 4 --file new.md
notion pages content replace-section <page-id> --heading "### Your Actions" --under "## Phase 4: Draft Submission" --file new.md
```

`--under` must name a heading at a *higher* level than `--heading`, and must
itself appear only once; otherwise the command exits 1. With `--under`,
`--occurrence` counts matches inside that parent section only.

The resolved target is reported in the JSON output of both the real run and
`--dry-run` as `occurrence`, `total_matches`, `section_start_block`, and
`section_end_block` (1-based, inclusive).

### Clear Content

```bash
notion pages content clear <page-id>
notion pages content clear <page-id> --force
```

### Delete a Block

```bash
notion pages blocks delete <block-id>
notion pages blocks delete <block-id> --force
notion pages blocks delete <block-id> --recursive --force
```

Interactive terminals prompt for confirmation. Non-interactive callers such as
agent Bash tools, CI, cron jobs, and pipes must pass `--force`; otherwise the
command refuses before deletion and prints the required non-interactive syntax.

### Toggle Headings (collapsible sections)

The right-arrow ▶ in the Notion UI is the `is_toggleable: true` flag on a
heading block. Three ways to manage it from the CLI:

```bash
#: 1. Promote ALL headings from markdown to toggleable in one shot
notion pages content append PAGE_ID -f chapter.md --is-toggleable

#: 2. Use raw JSON when you need PER-heading control (markdown can't express that)
notion pages blocks append PAGE_ID --json-file blocks.json    # supports any nesting depth

#: 3. Flip an existing heading on or off
notion pages blocks update BLOCK_ID --toggleable
notion pages blocks update BLOCK_ID --no-toggleable
notion pages blocks update BLOCK_ID --text "New title" --toggleable   # combine
```

When reading blocks back, `pages blocks list` exposes `is_toggleable` in JSON
output and as a column in `--table` view; markdown rendering prefixes toggle
headings with `▶ ` (e.g. `# ▶ Section Title`).

### Synced Blocks

```bash
notion pages blocks append PAGE_ID --file reusable.md --synced
notion pages blocks append PAGE_ID --synced-from ORIGINAL_SYNCED_BLOCK_ID
```

`--synced` wraps one content input (`--text`, `--file`, `--json`, or
`--json-file`) in a new original synced block. `--synced-from` appends a
duplicate synced block and cannot be combined with content inputs.

---

## Comment Commands

Manage comments on pages and blocks.

### List Comments

Notion's public List comments endpoint returns only **open/unresolved** comments;
it cannot enumerate resolved comments. To prevent a successful but silently
incomplete result, the CLI fails unless you explicitly accept that API scope with
`--open-only`:

```bash
notion comments list --page-id <page-id> --open-only
notion comments list --page-id <page-id> --with-context --open-only
notion comments list --block-id <block-id> --open-only
notion comments list --discussion-id <discussion-id> --open-only
notion comments list --page-id <page-id> --open-only --limit 10
```

By default, `--page-id` lists open comments attached directly to the page. Use
`--with-context` to recursively scan every page block for open inline comments
and include the parent block text each comment is attached to, plus nearby block
context in JSON output. JSON output reports the parent block as `selected_block`.
Every page/block comment source is fully paginated before results are merged and
the global `--limit` is applied. Any traversal, lookup, or malformed-pagination
failure exits nonzero rather than returning a partial array.

A comment retrievable by `comments get COMMENT_ID` can still be absent from an
`--open-only` list when its discussion is resolved. The public API provides no
endpoint for discovering those resolved comment IDs.

**Options:**
| Option | Description |
|--------|-------------|
| `-p, --page-id` | Page ID to get comments for |
| `-b, --block-id` | Block ID to get comments for |
| `-d, --discussion-id` | Discussion thread ID to get comments for |
| `-c, --with-context` | Include parent block text (only with --page-id) |
| `--open-only` | Explicitly accept the API's open/unresolved-only listing scope (required) |
| `-l, --limit` | Maximum number of comments to return after complete source pagination |
| `--max-workers` | Maximum concurrent block comment lookups when using `--with-context` (default: 25) |
| `-f, --filter` | Filter comments with `field:op:value` syntax |

### Get Comment

```bash
notion comments get <comment-id>
notion comments get <comment-id>
```

### Create Comment

```bash
notion comments create "This is my comment" --page-id <page-id>
notion comments create "My reply" --discussion-id <discussion-id>
notion comments create --text-file reply.md --discussion-id <discussion-id>

#: Notify a real person with a real Notion mention
notion comments create "please review" --page-id <page-id> --mention someone@example.com
notion comments create "please review" --page-id <page-id> --mention <user-uuid>

#: Repeatable; mentions lead the comment in the order given
notion comments create "handoff" --discussion-id <discussion-id> \
  -m first@example.com -m second@example.com
```

The public API can add a page comment or reply to an existing inline discussion,
but it cannot start a new inline discussion on a block. The CLI retains
`--block-id` only to produce a clear compatibility error before making a request.
Some Notion API versions accept that unsupported payload and return a comment
object that `comments get` can retrieve but `comments list` cannot enumerate.
The CLI refuses to create that inaccessible state.

**Options:**
| Option | Description |
|--------|-------------|
| `-f, --text-file` | File containing comment text content |
| `-p, --page-id` | Page ID to add comment to |
| `-b, --block-id` | Unsupported for creation; fails before any API request |
| `-d, --discussion-id` | Discussion thread ID to reply to |
| `-m, --mention` | Mention a workspace user by email or user UUID (repeatable) |

Use `--text-file` for comment bodies that contain shell-sensitive text such as
backticks, `$()`, angle-bracket placeholders, quotes, or newlines.

**Note:** Exactly one target must be provided. Use `--page-id` or
`--discussion-id`; `--block-id` always fails loud.

#### Mentions Notify, Plain `@Name` Text Does Not

A Notion mention is its own `rich_text` object. Typing `@Mandy Mowers` into the
comment body stores plain text and sends **no** notification. `--mention` is the
only way to notify someone.

`--mention` accepts an email address or a user UUID and works with `--page-id`,
`--block-id`, and `--discussion-id` alike. Resolved mentions are placed at the
front of the comment, in the order given, each followed by a single space, then
the body text.

Resolution is fail-fast — nothing is posted when it fails, and the command never
degrades a mention into plain text:

| Condition | Result |
|-----------|--------|
| Email matches no user | Error naming the email; no comment created |
| Email matches more than one user | Error listing every match; no comment created |
| Resolved user is a `bot` | Error before the API call; only person users can be mentioned |
| Value is neither UUID nor email | Error before any API call |

Email resolution requires the integration's **read user information** capability
(for `GET /v1/users`) and the **email** capability (to populate `person.email`).
Without the email capability, resolve by user UUID from `notion users list`.

## User Commands

### List Users

```bash
notion users list --table
notion users list --filter "type:eq:person" --table
notion users list --filter "person.email:eq:someone@example.com"
notion users list --properties "id,name,email" --limit 10
```

Walks every `GET /v1/users` cursor page — there is no first-page truncation.
Notion has no server-side name or email filter, so `--filter` is applied
client-side against the returned records.

**Options:**
| Option | Description |
|--------|-------------|
| `-t, --table` | Display as formatted table |
| `-l, --limit` | Maximum users to return (default: all users) |
| `-f, --filter` | Filter: `field:op:value` (e.g., `type:eq:person`, `person.email:eq:a@b.com`) |
| `-p, --properties` | Comma-separated fields to include (e.g., `id,name,email`) |

Each record carries `id`, `name`, `type` (`person` or `bot`), a flat `email`
convenience field, `avatar_url`, and the raw `person` / `bot` sub-object, so
dot-notation filters such as `person.email:eq:...` resolve against the same
shape the API returned.

### Get User

```bash
notion users get <user-id>
notion users get <user-id> --table
```

**Options:**
| Option | Description |
|--------|-------------|
| `-t, --table` | Display as formatted table |

## Additional Commands

### Cache

```bash
notion cache --help
```
