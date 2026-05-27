# OneDrive CLI

A command-line interface for [OneDrive for Business](https://learn.microsoft.com/en-us/graph/onedrive-concept-overview) via Microsoft Graph API.

## Features

- **Multi-profile support** - Manage multiple auth configurations (e.g., different tenants)
- **Dual auth methods** - Azure CLI auth or MSAL device code flow per profile
- **Drive management** - List and access drives available to you
- **File operations** - List, get, upload, download, and delete files/folders
- **Auto-detect upload strategy** - Uses simple upload for small files (<4MB), resumable upload for larger files
- **Path or ID access** - Reference items by path (`/Documents/file.txt`) or ID

## Prerequisites

- **Azure CLI** - [Install Azure CLI](https://aka.ms/installazurecli) (for `az_cli` auth method)
- **Azure AD account** - OneDrive for Business (work/school account)
- **Python 3.9+**

## Installation

```bash
cd onedrive
pip install -e .
```

After installation, the `onedrive` command will be available in your terminal.

## Quick Start

```bash
# 1. Authenticate via Azure CLI
onedrive auth login

# 2. List available drives
onedrive drives list

# 3. List files in a drive
onedrive items list DRIVE_ID

# 4. Upload a file
onedrive items upload DRIVE_ID ./local-file.pdf /Documents/file.pdf

# 5. Download a file
onedrive items download DRIVE_ID /Documents/file.pdf ./downloaded.pdf
```

## Commands

### Authentication

Authentication method depends on your profile's `AUTH_METHOD` setting:
- `az_cli` - Uses Azure CLI user credentials (must run `az login` with a user account; service principals cannot call the delegated `/me` endpoints this CLI uses)
- `msal_device_code` - Uses MSAL device code flow (enter a code at microsoft.com/devicelogin)

```bash
# Create a profile and choose its auth type
onedrive auth profiles create work --auth-type az_cli
onedrive auth profiles create lab --auth-type msal_device_code

# Login with a specific profile
onedrive auth login --profile progress_psdxautomation_az_cli_auth

# Force re-authentication
onedrive auth login --profile progress_psdxautomation_az_cli_auth --force

# Check authentication status
onedrive auth status
onedrive auth status --table

# Test authentication
onedrive auth test

# Logout
onedrive auth logout
```

### Profiles

Manage multiple authentication profiles (e.g., different tenants or auth methods).

```bash
# List all profiles
onedrive auth profiles list

# Create a new profile
onedrive auth profiles create my_profile --auth-type az_cli

# Select active profile
onedrive auth profiles select my_profile

# Remove a profile
onedrive auth profiles remove my_profile

# Delete alias
onedrive auth profiles delete my_profile
```

### Drives

List and get details about drives accessible to you.

```bash
# List all drives
onedrive drives list
onedrive drives list --table
onedrive drives list --properties "id,name,driveType"

# Get drive details
onedrive drives get DRIVE_ID
onedrive drives get DRIVE_ID --table
```

### Items (Files and Folders)

Manage files and folders in OneDrive drives.

```bash
# List items in drive root
onedrive items list DRIVE_ID
onedrive items list DRIVE_ID --table

# List items in a folder (by path)
onedrive items list DRIVE_ID /Documents
onedrive items list DRIVE_ID /Documents --limit 50

# Get item details (by ID or path)
onedrive items get DRIVE_ID ITEM_ID
onedrive items get DRIVE_ID /Documents/report.pdf
onedrive items get DRIVE_ID ITEM_ID --properties "id,name,size,webUrl"

# Upload a file
onedrive items upload DRIVE_ID ./local-file.pdf /Documents/file.pdf
onedrive items upload DRIVE_ID ./large-video.mp4 /Videos/video.mp4

# Download a file
onedrive items download DRIVE_ID ITEM_ID ./downloaded.pdf
onedrive items download DRIVE_ID /Documents/report.pdf ./report.pdf

# Delete an item (prompts for confirmation)
onedrive items delete DRIVE_ID ITEM_ID
onedrive items delete DRIVE_ID /Documents/old-file.txt

# Delete without confirmation
onedrive items delete DRIVE_ID ITEM_ID --force
```

## Output Formats

All list and get commands support JSON (default) and table output:

```bash
# JSON output (default) - for scripting
onedrive drives list | jq '.[0].id'

# Table output - for humans
onedrive drives list --table

# Select specific properties
onedrive items list DRIVE_ID --properties "id,name,size"
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display as formatted table |
| `--limit` | `-l` | Maximum number of results (default: 100) |
| `--filter` | `-f` | Filter results (field:op:value) |
| `--properties` | `-p` | Comma-separated fields to include |
| `--force` | `-F` | Skip confirmation prompts |
| `--version` | `-v` | Show version and exit |

## Path vs ID

Items can be referenced by either:

- **ID**: The unique OneDrive item ID (e.g., `01ABCDEFGHIJ1234567890`)
- **Path**: The folder path (e.g., `/Documents/Reports/2024/report.pdf`)

The CLI auto-detects which you're using - if the reference contains `/`, it's treated as a path.

## Upload Behavior

The CLI automatically chooses the upload method:

- **Simple upload**: Files < 4MB are uploaded in a single request
- **Resumable upload**: Files >= 4MB use a resumable upload session with 320KB chunks

This handles large files reliably without timeout issues.

## Examples

### Complete Workflow

```bash
# Authenticate
onedrive auth login

# Find your drive ID
DRIVE_ID=$(onedrive drives list | jq -r '.[0].id')

# List files in Documents folder
onedrive items list $DRIVE_ID /Documents --table

# Upload a file
onedrive items upload $DRIVE_ID ./report.pdf /Documents/report.pdf

# Get the uploaded file's web URL
onedrive items get $DRIVE_ID /Documents/report.pdf | jq -r '.web_url'

# Download it back
onedrive items download $DRIVE_ID /Documents/report.pdf ./downloaded-report.pdf

# Clean up
onedrive items delete $DRIVE_ID /Documents/report.pdf --force
```

### Export Items to JSON

```bash
onedrive items list $DRIVE_ID --limit 500 > items.json
```

### Find Large Files

```bash
onedrive items list $DRIVE_ID | jq '[.[] | select(.size > 10000000)] | sort_by(.size) | reverse'
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Permissions

This CLI requires the following Microsoft Graph permissions:

- `Files.Read.All` - Read all files user can access
- `Files.ReadWrite.All` - Read and write all files user can access

These permissions are requested through Azure CLI authentication.

## Requirements

- Python 3.9+
- Azure CLI (for `az_cli` auth method)
- Dependencies (installed automatically):
  - typer
  - requests
  - pydantic
  - python-dotenv
  - msal
  - cli-tools-shared

## License

MIT

## Additional Commands

### Link

```bash
onedrive link --help
```

### Cache

```bash
onedrive cache --help
```
