# 10Web CLI

A command-line interface for the [10Web API](https://apidocs.10web.io).

## Installation

```bash
cd tenweb
pip install -e .
```

After installation, the `tenweb` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with your 10Web API key
tenweb auth login --api-key YOUR_10WEB_API_KEY

# List websites in your account
tenweb websites list

# Get instance information for a website
tenweb websites get 15354

# Check whether a subdomain is available
tenweb subdomains check my-site
```

## Commands

### Authentication

```bash
# Login with API key
tenweb auth login
tenweb auth login --api-key YOUR_API_KEY

tenweb auth status

# Clear stored credentials
tenweb auth logout
```

### Profiles

```bash
# List all profiles
tenweb auth profiles list

# Show default profile
tenweb auth profiles get default

# Switch default profile
tenweb auth profiles set-default PROFILE_NAME

# Create a new profile
tenweb auth profiles create PROFILE_NAME
```

### Cache

```bash
# Show cache status
tenweb cache status

# Clear cached responses
tenweb cache clear
```

### Websites

```bash
# List all websites (JSON output)
tenweb websites list

# List websites with table output
tenweb websites list --table

# Limit and filter the returned websites
tenweb websites list --limit 10 --filter "type:eq:live"

# Select only specific properties
tenweb websites list --properties "id,name,site_url,type"

# Get instance details for a specific website
tenweb websites get 15354
tenweb websites get 15354 --table
tenweb websites get 15354 --properties "website_id,status,region"
```

### Subdomains

```bash
# Check whether a subdomain is available
tenweb subdomains check my-site
tenweb subdomains check my-site --table
```

## Output Formats

All commands support JSON output by default. Commands with `--table` display human-readable tables.

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

### JSON Output Example

`tenweb` does not emit AI instructions in the initial command surface.

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results for list commands |
| `--filter` | `-f` | Client-side filter expression in `field:op:value` form |
| `--properties` | `-p` | Comma-separated fields to include in output |
| `--table` | `-t` | Display results as a table |
| `--version` | `-v` | Show version and exit |

## Configuration

Credentials are stored in a `.env` file in the package directory:

```bash
# API Key
TENWEB_API_KEY=your_api_key

# Optional: API base URL
TENWEB_BASE_URL=https://api.10web.io
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List website IDs with jq

```bash
tenweb websites list | jq '.[].id'
```

### Export websites to JSON

```bash
tenweb websites list --limit 200 > websites.json
```

## Models

This CLI uses typed Pydantic models for `Website`, `WebsiteDetail`, and `SubdomainCheckResult`.

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests
  - pydantic

## License

MIT
