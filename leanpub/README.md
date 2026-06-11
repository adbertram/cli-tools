# Leanpub CLI

## DESCRIPTION

The `leanpub` CLI provides a command-line interface for Leanpub API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
uv tool install -e . --force --refresh
```

## Quick Start

```bash
# Authenticate with a Leanpub API key
leanpub auth login

# Check authentication
leanpub auth status

# List per-book author stats
leanpub author stats list --slug my-book --table

# Aggregate stats across multiple books
leanpub author stats get --slug my-book --slug another-book
```

## Commands

### Authentication

```bash
# Configure API key
leanpub auth login

# Force a fresh login prompt
leanpub auth login --force

# Check authentication status
leanpub auth status

# Check authentication as a table
leanpub auth status --table

# Test authentication
leanpub auth test

# Clear stored credentials
leanpub auth logout
```

### Profiles

```bash
# List all auth profiles
leanpub auth profiles list

# Show a profile
leanpub auth profiles get default

# Create a profile
leanpub auth profiles create work

# Select the active profile
leanpub auth profiles select work

# Delete a profile
leanpub auth profiles delete work
```

### Author Stats

```bash
# List per-book stats as JSON
leanpub author stats list --slug my-book

# List per-book stats for several books
leanpub author stats list --slug my-book --slug another-book

# List configured books from BOOK_SLUGS
leanpub author stats list

# List stats in table format
leanpub author stats list --slug my-book --table

# Limit the number of supplied or configured slugs queried
leanpub author stats list --limit 5

# Filter the resulting rows client-side
leanpub author stats list --filter "total_revenue:gt:100"

# Select output fields
leanpub author stats list --properties "slug,title,total_revenue,total_royalties"

# Get aggregate totals across supplied or configured books
leanpub author stats get --slug my-book --slug another-book

# Show aggregate totals as a table
leanpub author stats get --table
```

### Cache

```bash
# Show cache status
leanpub cache status

# Clear cached responses
leanpub cache clear
```

## Output Formats

JSON is the default output format. Use `--table` or `-t` for table output.

```bash
leanpub author stats list --slug my-book
leanpub author stats list --slug my-book --table
```

## Options Reference

| Option | Short | Commands | Description |
|--------|-------|----------|-------------|
| `--slug` | `-s` | `author stats list`, `author stats get` | Leanpub book slug. Repeat for multiple books. |
| `--limit` | `-l` | `author stats list` | Maximum number of books to query. |
| `--filter` | `-f` | `author stats list` | Client-side filter using `field:op:value` syntax. |
| `--properties` | `-p` | `author stats list`, `author stats get` | Comma-separated fields to include. |
| `--table` | `-t` | output commands | Display output as a table. |
| `--version` | `-v` | root | Show version and exit. |

## Configuration

Credentials and defaults are stored in the active profile `.env` file.

```bash
ACTIVE=true
API_KEY=your_api_key
BOOK_SLUGS=my-book,another-book
BASE_URL=https://leanpub.com
```

`BOOK_SLUGS` is optional. When it is set, `leanpub author stats list` and `leanpub author stats get` can run without repeated `--slug` options.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication or credential error |
| 130 | User interrupted |

## Examples

```bash
# Export all configured book stats
leanpub author stats list > leanpub-author-stats.json

# Show only revenue columns
leanpub author stats list --properties "slug,total_revenue,total_royalties" --table

# Aggregate all configured books
leanpub author stats get --properties "book_count,total_revenue,total_royalties,total_copies_sold"
```

## Models

This CLI uses Pydantic models for typed API output.

| Model | Description |
|-------|-------------|
| `CurrentUser` | Authenticated Leanpub user |
| `BookSummary` | Book summary response |
| `RoyaltySummary` | Royalty response |
| `AuthorBookStats` | Per-book author stats row |
| `AuthorStatsSummary` | Aggregated author stats |

## Requirements

- Python 3.9+
- `typer`
- `requests`
- `pydantic`
- `python-dotenv`
- `cli-tools-shared`
