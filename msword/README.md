# Msword CLI

## DESCRIPTION

The `msword` CLI lets you read Word docs, convert to markdown, and extract comments with context.

Use it when you need scriptable reads, exports, or evidence collection without opening the service UI.

## Installation

```bash
cd msword
pip install -e .
```

After installation, the `msword` command will be available in your terminal.

## Quick Start

```bash
# Read a Word document
msword docs read document.docx

# Convert to Markdown
msword docs convert document.docx

# Extract comments with context
msword docs comments list document.docx --table

# Apply a batch of edits as tracked changes
msword docs edit-tracked document.docx --edits edits.json --author "Adam Bertram"
```

## Commands

### Read

Read text content from a Word document.

```bash
# Output as JSON
msword docs read document.docx

# Output as table
msword docs read document.docx --table
```

### Convert

Convert a Word document to Markdown.

```bash
# Output markdown to stdout (JSON with metadata)
msword docs convert document.docx

# Write markdown to a file
msword docs convert document.docx --output document.md
```

### Comments

Extract comments with the text they reference.

```bash
# Output as JSON
msword docs comments list document.docx

# Output as table
msword docs comments list document.docx --table

# Limit results
msword docs comments list document.docx --limit 5

# Filter by author
msword docs comments list document.docx --filter "author:eq:Jane"

# Select specific fields
msword docs comments list document.docx --properties "author,text,context"

# Fetch one comment by ID
msword docs comments get document.docx 0

# Add an inline comment anchored to text
msword docs comments add document.docx --text "Please clarify" --author "Adam Bertram" --reference-text "the quarterly rollout plan"
```

### Edit Tracked

Apply a batch of text edits to a `.docx` file **in place**, inserting each one as a genuine Word tracked change (`w:ins`/`w:del`) attributed to `--author`, without disturbing any existing comment or existing tracked change already in the file.

`--edits` points to a JSON file containing a list of edit objects:

```json
[
  {"old_text": "quick brown fox", "new_text": "swift red fox"},
  {"old_text": "lazy dog", "new_text": "sleepy cat", "occurrence": 1}
]
```

- `old_text` (required): the exact text to locate and replace.
- `new_text` (required): the replacement text (may be an empty string for a pure deletion).
- `occurrence` (optional, default `1`): which match of `old_text` to target, resolved against the document as it stands after any earlier edits in the same batch. If two edits in one batch share the same `old_text`, order them from the highest occurrence to the lowest.

```bash
msword docs edit-tracked document.docx --edits edits.json --author "Adam Bertram"
```

Before saving, every pre-existing comment and every pre-existing tracked change is verified byte-for-byte unchanged. If `old_text` for any edit cannot be found, or if verification detects that existing markup would be altered, the command fails with a clear error and the file on disk is left untouched.

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping
- **Table** (`--table`/`-t`): Human-readable formatted table

### JSON Output Example

```bash
msword docs comments list document.docx
```

### Table Output Example

```bash
msword docs comments list document.docx --table
```

## Options Reference

| Option | Short | Description | Commands |
|--------|-------|-------------|----------|
| `--table` | `-t` | Display as table | read, comments |
| `--limit` | `-l` | Maximum number of results | comments |
| `--filter` | `-f` | Filter results (field:op:value) | comments |
| `--properties` | `-p` | Comma-separated fields to include | comments |
| `--output` | `-o` | Output file path | convert |
| `--edits` | | Path to a JSON edit-list file | edit-tracked |
| `--author` | | Name attributed to inserted comment/tracked change | comments add, edit-tracked |
| `--version` | `-v` | Show version and exit | (global) |

## Piping Examples

```bash
# Get all comment texts as a list
msword docs comments list document.docx | jq '.[].text'

# Get comments by a specific author
msword docs comments list document.docx | jq '[.[] | select(.author == "Eve Turzillo")]'

# Convert and save markdown
msword docs convert document.docx | jq -r '.markdown' > output.md
```

## Models

| Model | Description | Fields |
|-------|-------------|--------|
| `Comment` | Extracted comment | `id`, `author`, `date`, `text`, `context` |
| `DocumentContent` | Document text | `file`, `paragraphs`, `content` |
| `ConvertedDocument` | Markdown output | `file`, `markdown`, `messages` |
| `AddCommentResult` | Result of adding a comment | `file`, `comment_id`, `author`, `text`, `reference_text` |
| `TrackedEditApplied` | One applied tracked-change edit | `old_text`, `new_text`, `occurrence`, `del_id`, `ins_id` |
| `EditTrackedChangesResult` | Result of a tracked-edit batch | `file`, `author`, `edits_applied`, `edits` |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client error (file not found, invalid format) |
| 130 | User interrupted (Ctrl+C) |

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-docx
  - mammoth
  - pydantic

## License

MIT
