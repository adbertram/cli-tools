# photos-app CLI

## DESCRIPTION

The `photos-app` CLI wraps sqlite3 with standardized cli-tools behavior.

Use it when you need the underlying command exposed through cli-tools JSON/table conventions for agents, automation, or terminal workflows.

## Installation

```bash
cd photos-app
pip install -e .
```

After installation, the `photos-app` command will be available in your terminal.

## Quick Start

```bash
# Check if Photos library is accessible
photos-app auth status

# List recent photos
photos-app photos list --limit 10

# List photos from a date range
photos-app photos list --from 2024-01-01 --to 2024-12-31

# Download photos to a folder
photos-app photos download ~/Desktop/export --limit 5
```

## Commands

### Authentication

No credentials needed - this CLI accesses the local Photos library database.

```bash
# Check if Photos library is accessible
photos-app auth status
photos-app auth status
```

### Photos

```bash
# List photos (JSON output)
photos-app photos list
photos-app photos list --limit 10

# List photos with date filtering
photos-app photos list --from 2024-01-01 --to 2024-12-31

# List photos from a specific album
photos-app photos list --album "Vacation 2024"
photos-app photos list --album "Family" --limit 10

# Output UUIDs only (for piping)
photos-app photos list --paths --limit 10

# Include videos
photos-app photos list --videos

# Include hidden photos
photos-app photos list --hidden

# Download/export photos to a folder
photos-app photos download ~/Desktop/export --limit 10
photos-app photos download /tmp/photos --from 2024-06-01

# Get total photo count
photos-app photos count
```

### Albums

```bash
# List all user albums
photos-app albums list

# Include system albums (imports, sync, etc.)
photos-app albums list --system

# Create a new album
photos-app albums create "Vacation 2024"
photos-app albums create "Family Photos"

# Add photos to an album
photos-app albums add-photos --album "Vacation 2024" --photo-ids "UUID1,UUID2,UUID3"
photos-app albums add-photos -a "Family" -p "UUID1"

# Move an album into a folder (auto-creates folder if needed)
photos-app albums move "ebay-listing-20240101" --folder "Completed eBay Listings"
photos-app albums move "Old Album" -f "Archive" --yes

# Auto-enhance all photos in an album (toggle — re-running removes enhancement)
photos-app albums enhance "ebaylisting-boxes"
photos-app albums enhance "ebaylisting-boxes" --limit 10
photos-app albums enhance "ebaylisting-boxes" --delay 2.0 --yes

# Delete an album (photos are not deleted)
photos-app albums delete "Old Album"
photos-app albums delete "Temp Album" --yes
```

### Profiles

```bash
# List all profiles
photos-app auth profiles list

# Create a new profile
photos-app auth profiles create "work"

# Select active profile
photos-app auth profiles select "work"

# Delete a profile
photos-app auth profiles delete "work"
```

## Output Formats

All list commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping
- **Paths** (`--paths` or `-p`): UUIDs only, one per line

```bash
# JSON output (default)
photos-app photos list --limit 3

# UUID output for piping
photos-app photos list --paths --limit 10
```

## How It Works

- **Queries**: Uses SQLite to directly query the Photos library database at `~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite`
- **Exports**: Uses AppleScript to export photos via Photos.app, which automatically handles downloading from iCloud
- **No credentials**: Local database access only

## Configuration

No configuration required. Optionally set a custom library path:

```bash
# In .env file
PHOTOS_LIBRARY_PATH=/path/to/Photos Library.photoslibrary
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Photos library not accessible |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Recent Photos and Filter with jq

```bash
photos-app photos list --limit 10 | jq '.[].filename'
```

### Export Photos from Date Range

```bash
photos-app photos download ~/Desktop/christmas-photos --from 2024-12-24 --to 2024-12-26
```

### Get Photo Count

```bash
photos-app photos count
```

### Add Recent Photos to an Album

```bash
# Get UUIDs of recent photos and add them to an album
UUIDS=$(photos-app photos list --limit 5 | jq -r '.[].uuid' | tr '\n' ',' | sed 's/,$//')
photos-app albums add-photos -a "My Album" -p "$UUIDS"
```

## Models

This CLI uses Pydantic models for type-safe data handling.

### Photo Model

| Field | Type | Description |
|-------|------|-------------|
| `uuid` | str | Unique identifier |
| `filename` | str | Original filename |
| `date_created` | datetime | When photo was taken |
| `date_added` | datetime | When added to library |
| `kind` | enum | `photo` or `video` |
| `file_type` | str | UTI (e.g., `public.jpeg`) |
| `width` | int | Image width in pixels |
| `height` | int | Image height in pixels |
| `cloud_status` | enum | `local` or `icloud` |
| `is_favorite` | bool | Marked as favorite |
| `is_hidden` | bool | Hidden in library |

### Album Model

| Field | Type | Description |
|-------|------|-------------|
| `uuid` | str | Unique identifier |
| `title` | str | Album name |
| `photo_count` | int | Number of photos |
| `video_count` | int | Number of videos |
| `date_created` | datetime | When album was created |

## Requirements

- macOS with Photos.app
- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - pydantic

## License

MIT

## Additional Commands

### Cache

```bash
photos-app cache --help
```
