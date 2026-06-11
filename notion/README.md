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
notion database list <database-id>
notion database list <database-id>
notion database list <database-id> --filter-status "Done"
```

**Options:**
| Option | Description |
|--------|-------------|
| `-s, --filter-status` | Filter by status (format: 'value' or 'property:value') |
| `--filter-select` | Filter by select property (format: 'property:value') |
| `--filter-checkbox` | Filter by checkbox property (format: 'property:true/false') |
| `--filter-text` | Filter by text contains (format: 'property:value') |
| `-f, --filter` | Raw JSON filter object |
| `-p, --properties` | Comma-separated list of properties to include |
| `-l, --limit` | Maximum number of results |
| `--sort` | Sort by property (format: 'property' or 'property:asc/desc') |

### Get Schema

Get database property definitions.

```bash
notion database schema <database-id>
notion database schema <database-id>
```

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
| `-o, --out-file` | Write markdown to file |

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
```

**Options:**
| Option | Description |
|--------|-------------|
| `-t, --type` | **(Required)** Field type (rich_text, number, select, multi_select, status, date, etc.) |
| `-o, --options` | Comma-separated options for select/multi_select/status types |
| `--formula-expression` | Expression for formula type |
| `--relation-database` | Database ID for relation type |
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
```

**Options:**
| Option | Description |
|--------|-------------|
| `-n, --name` | New name for the field |
| `-o, --options` | Replace options for select/multi_select/status |
| `--number-format` | Format for number type |
| `--formula-expression` | Expression for formula type |

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
| `-o, --out-file` | Write markdown to file |

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

**Options:**
| Option | Description |
|--------|-------------|
| `-t, --text` | Text/markdown content to set |
| `-f, --file` | File containing markdown content |
| `--json-file` | Notion JSON blocks file (from `export --format notion-json`) |
| `--is-toggleable` | Make every `heading_1`/`2`/`3` produced from markdown into a toggle heading (markdown input only; ignored with `--json-file`) |

Note: `--text`, `--file`, and `--json-file` are mutually exclusive.

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
| `-t, --text` | Markdown content for the replacement section |
| `-f, --file` | File containing markdown content for the replacement section |
| `--dry-run` | Show the section replacement plan without editing Notion |

### Clear Content

```bash
notion pages content clear <page-id>
notion pages content clear <page-id> --force
```

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

---

## Comment Commands

Manage comments on pages and blocks.

### List Comments

```bash
notion comments list --page-id <page-id>
notion comments list --page-id <page-id> --with-context
notion comments list --block-id <block-id>
notion comments list --discussion-id <discussion-id>
notion comments list --page-id <page-id> --limit 10
```

By default, `--page-id` lists comments attached directly to the page. Use
`--with-context` when you need to scan page blocks for inline block comments and
include the parent block text each comment is attached to, plus nearby block
context in JSON output. JSON output reports the parent block as `selected_block`.

**Options:**
| Option | Description |
|--------|-------------|
| `-p, --page-id` | Page ID to get comments for |
| `-b, --block-id` | Block ID to get comments for |
| `-d, --discussion-id` | Discussion thread ID to get comments for |
| `-c, --with-context` | Include parent block text (only with --page-id) |
| `-l, --limit` | Maximum number of comments to return |
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
notion comments create "Comment on this block" --block-id <block-id>
notion comments create "My reply" --discussion-id <discussion-id>
```

**Options:**
| Option | Description |
|--------|-------------|
| `-p, --page-id` | Page ID to add comment to |
| `-b, --block-id` | Block ID to add comment to |
| `-d, --discussion-id` | Discussion thread ID to reply to |

**Note:** Exactly one of --page-id, --block-id, or --discussion-id must be provided.

## Additional Commands

### Cache

```bash
notion cache --help
```
