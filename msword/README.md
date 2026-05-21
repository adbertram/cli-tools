# Msword CLI

Read Word documents, convert to Markdown, and extract comments with context.

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
```

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
