# Grammarly CLI

Command-line interface for Grammarly plagiarism and docs workflows.

## Features

- Check documents for plagiarism
- List, inspect, and read Grammarly docs with browser-session cookies
- Support for multiple file formats (.doc, .docx, .odt, .txt, .rtf)
- Text input via stdin or command argument
- Separate auth paths for plagiarism OAuth credentials and docs cookies
- Rich table output formatting

## Installation

```bash
cd <cli-tools-root>/grammarly
./install.sh
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Authentication

Grammarly uses two credential paths:

1. Plagiarism API commands use OAuth client credentials from the
   [Grammarly Developer Portal](https://developer.grammarly.com/).
2. Docs commands use cookies from a logged-in `app.grammarly.com` session.

Configure plagiarism credentials:
```bash
grammarly auth login
```

Configure only the docs cookie path after seeding a cookie source:
```bash
export GRAMMARLY_COOKIES='grauth=xxx; csrf-token=xxx; ...'
grammarly auth login --credential-type browser_session
```

The docs cookie import also accepts the legacy file path:
```bash
echo 'grauth=xxx; csrf-token=xxx; ...' > ~/.grammarly_cookies
grammarly auth login --credential-type browser_session
```

Check authentication status:
```bash
grammarly auth status
```

## Commands

### Plagiarism Detection

#### Check a File

```bash
# Check a document file
grammarly plagiarism check document.docx

# With table output
grammarly plagiarism check document.txt

# Without waiting for result
grammarly plagiarism check document.docx --no-wait
```

#### Check Text

```bash
# Check text directly
grammarly plagiarism check --text "Your text to check for plagiarism here"

# From stdin
echo "Text to check" | grammarly plagiarism check --text -

# From a pipe
cat essay.txt | grammarly plagiarism check --text -
```

#### Check Status

```bash
# Get status of a previous check
grammarly plagiarism status <score_request_id>

# With table output
grammarly plagiarism status abc-123-def
```

### Authentication

```bash
# Configure plagiarism OAuth credentials
grammarly auth login

# Import docs cookies into the active profile
grammarly auth login --credential-type browser_session

# Re-authenticate one credential path
grammarly auth login --credential-type custom --force
grammarly auth login --credential-type browser_session --force

# Check status
grammarly auth status

# Clear all saved auth state
grammarly auth logout
```

### Docs

```bash
# List recent Grammarly docs
grammarly docs list --limit 10

# Get doc metadata
grammarly docs get 123456

# Read doc content
grammarly docs read 123456

# Generate a new doc URL
grammarly docs new --title "Draft title"
```

## Examples

### Basic Usage

```bash
# Check a Word document
grammarly plagiarism check report.docx
```

Output (JSON):
```json
{
  "score_request_id": "abc-123-def",
  "status": "COMPLETED",
  "updated_at": "2024-01-15T10:30:00Z",
  "score": {
    "originality": 0.89
  }
}
```

### Table Output

```bash
grammarly plagiarism check essay.txt
```

### Piping Text

```bash
# Check clipboard content (macOS)
pbpaste | grammarly plagiarism check --text -

# Check file content
cat document.txt | grammarly plagiarism check --text -
```

### Async Check

```bash
# Submit without waiting
grammarly plagiarism check large_document.docx --no-wait
# Returns: score_request_id: xyz-789-abc

# Check status later
grammarly plagiarism status xyz-789-abc
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--text` | | Text to check (use - for stdin) |
| `--wait/--no-wait` | | Wait for result (default: wait) |
| `--poll-interval` | | Seconds between status checks (default: 5) |
| `--max-wait` | | Maximum seconds to wait (default: 120) |
| `--version` | `-v` | Show version and exit |

## Models

### PlagiarismResult

| Field | Type | Description |
|-------|------|-------------|
| `score_request_id` | string | Unique identifier for the check |
| `status` | string | PENDING, FAILED, or COMPLETED |
| `updated_at` | string | ISO timestamp of last update |
| `score.originality` | float | 0-1 (higher = more original) |

### PlagiarismTransaction

| Field | Type | Description |
|-------|------|-------------|
| `score_request_id` | string | Unique identifier for the check |
| `file_upload_url` | string | Pre-signed S3 URL for file upload |

## Supported File Formats

| Extension | MIME Type |
|-----------|-----------|
| .doc | application/msword |
| .docx | application/vnd.openxmlformats-officedocument.wordprocessingml.document |
| .odt | application/vnd.oasis.opendocument.text |
| .txt | text/plain |
| .rtf | application/rtf |

## Configuration

Authentication is stored in the CLI-tools user data directory under:

```bash
~/.local/share/cli-tools/grammarly/
```

Legacy docs cookies in `~/.grammarly_cookies` are still accepted and can be
imported into the active auth profile with:

```bash
grammarly auth login --credential-type browser_session
```

## Constraints

- **Max file size**: 4 MB
- **Max text length**: 100,000 characters
- **Min text length**: 30 words
- **Score retention**: 30 days

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## API Reference

- [Grammarly Developer Documentation](https://developer.grammarly.com/)
- [Plagiarism Detection API](https://developer.grammarly.com/plagiarism-detection-api.html)

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests
  - pydantic

## Additional Commands

### Docs

```bash
grammarly docs --help
```

### Cache

```bash
grammarly cache --help
```
