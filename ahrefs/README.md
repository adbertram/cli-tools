# Ahrefs CLI

A command-line interface for [Ahrefs](https://app.ahrefs.com) Site Audit using browser automation and internal APIs.

## Installation

```bash
cd ahrefs
pip install -e .

# Install Playwright browsers (required once)
playwright install chromium
```

After installation, the `ahrefs` command will be available in your terminal.

## Quick Start

```bash
# Login to Ahrefs
ahrefs auth login

# Check login status
ahrefs auth status

# List site audits for a project
ahrefs site-audit list 2185593

# Get complete site audit report
ahrefs site-audit get 2185593
```

## Commands

### Authentication (`ahrefs auth`)

```bash
# Interactive login (opens browser)
ahrefs auth login

# Force re-login
ahrefs auth login --force

# Check authentication status
ahrefs auth status
ahrefs auth status

# Test authentication against real browser
ahrefs auth test

# Clear stored session
ahrefs auth logout
```

### Site Audit (`ahrefs site-audit`)

```bash
# List all crawls for a project
ahrefs site-audit list 2185593
ahrefs site-audit list 2185593
ahrefs site-audit list 2185593 --limit 5

# Filter crawls
ahrefs site-audit list 2185593 --filter "status:eq:completed"

# Get complete site audit report (cached)
ahrefs site-audit get 2185593

# Force fresh fetch (bypass cache)
ahrefs site-audit get 2185593 --refresh

# Show summary table
ahrefs site-audit get 2185593

# Select specific properties
ahrefs site-audit get 2185593 --properties "overview,issues"

# Manage cache
ahrefs site-audit cache list              # List cached projects
ahrefs site-audit cache clear             # Clear all cached reports
ahrefs site-audit cache clear -p 2185593  # Clear specific project cache
```

### Cache (`ahrefs cache`)

Manage the response cache. Cached responses speed up repeated commands by avoiding redundant browser/API calls.

```bash
# Clear all cached responses
ahrefs cache clear
```

### Profiles (`ahrefs auth profiles`)

Manage authentication profiles.

```bash
ahrefs auth profiles list
ahrefs auth profiles create <profile-name>
ahrefs auth profiles select <profile-name>
ahrefs auth profiles delete <profile-name>
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter: field:op:value (e.g., status:eq:completed) |
| `--properties` | `-p` | Comma-separated list of properties to display |
| `--refresh` | `-r` | Force fresh fetch, bypass cache |
| `--force` | `-F` | Force re-authentication (auth login) |
| `--version` | `-v` | Show version and exit |

## Configuration

Configuration is stored in `.env` file:

```bash
# Login credentials (optional - for automated login)
AHREFS_USERNAME=your_username
AHREFS_PASSWORD=your_password

# Base URL
AHREFS_BASE_URL=https://app.ahrefs.com

# Browser settings (true = invisible, false = visible browser)
AHREFS_HEADLESS=true

# Auth detection (CSS selector for logged-in state)
AHREFS_AUTH_INDICATOR_SELECTOR=.user-menu

# Login redirect pattern (URL pattern indicating redirect to login)
AHREFS_LOGIN_REDIRECT_PATTERN=/user/login
```

Browser session data is stored in `.browser-data/` directory for persistence between commands.
Site audit reports are cached in `.storage/site_audits/` for fast access.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Data Structure

The site audit report includes:

```json
{
  "project_id": 2185593,
  "crawl_id": "abc123",
  "crawl_date": "2025-01-11T20:57:35Z",
  "domain": "example.com",
  "overview": {
    "health_score": 85,
    "pages_crawled": 1500,
    "total_issues": 42,
    "errors_count": 5,
    "warnings_count": 37
  },
  "issues": {
    "html": [...],
    "meta": [...],
    "redirect": [...],
    "links": [...],
    "images": [...],
    "social": [...],
    "content": [...],
    "performance": [...],
    "resources": [...],
    "localization": [...],
    "other": [...]
  },
  "orphan_pages": [...],
  "redirect_chains": [...],
  "duplicate_content": [...],
  "errors": []
}
```

## Architecture

This CLI uses:

- **Browser Automation**: Playwright for authentication and session management
- **Internal v4 API**: Direct API calls using session cookies for data retrieval
- **Caching**: Local JSON cache for fast repeated access
- **Retry Logic**: Exponential backoff with jitter for resilient API calls

## Debugging

To debug browser automation issues:

```bash
# Run with visible browser
export AHREFS_HEADLESS=false
ahrefs auth login
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - playwright
  - pydantic
  - rich

## License

MIT
