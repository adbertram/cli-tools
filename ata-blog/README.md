# ATA Blog CLI

A CLI wrapper for managing the ATA Blog (adamtheautomator.com) by combining `wordpress` and `notion` CLIs.

## Prerequisites

This CLI wraps two command-line tools:

```bash
# WordPress CLI must be installed and authenticated
wordpress auth status

# Notion CLI must be installed and authenticated
notion auth status
```

## Installation

```bash
cd ata-blog
pip install -e .
```

After installation, the `ata-blog` command will be available in your terminal.

## Quick Start

```bash
# Check if both CLIs are available and authenticated
ata-blog auth status

# List articles from Notion
ata-blog notion-page list

# List WordPress posts
ata-blog wordpress-post list

# Publish a Notion article to WordPress
ata-blog notion-page publish <notion_page_id> --status draft
```

## How It Works

This CLI is a **wrapper** around two command-line tools:

- **notion-page commands** manage Notion pages and publishing to WordPress
- **wordpress-post/media/categories/tags commands** pass through to the `wordpress` CLI
- **wordpress-admin commands** wrap approved WordPress admin operations for ATA Blog infrastructure maintenance
- **Configuration** is minimal - underlying CLIs handle credentials

### Passthrough Commands

WordPress-post, media, categories, and tags commands pass options directly to the `wordpress` CLI. Use `--` to separate ata-blog command from wordpress options:

```bash
# Pass options to wordpress CLI
ata-blog wordpress-post list -- --limit 5
ata-blog categories list --
ata-blog tags list -- --limit 10
```

## Commands

### Authentication

```bash
# Check status of both WordPress and Notion CLIs
ata-blog auth status

# Show how to login to underlying CLIs
ata-blog auth login
ata-blog auth login --force  # Clear and re-authenticate

# Test authentication connectivity
ata-blog auth test
```

### Profiles

Manage authentication profiles for multiple environments.

```bash
# List all profiles
ata-blog auth profiles list

# Create a new profile
ata-blog auth profiles create staging

# Set default profile
ata-blog auth profiles set-default staging

# Delete a profile
ata-blog auth profiles delete staging --force
```

### Notion Page

Manage pages in the Notion database and publish to WordPress.

```bash
# List articles from Notion
ata-blog notion-page list
ata-blog notion-page list
ata-blog notion-page list --status "Draft" --limit 10

# Get article details
ata-blog notion-page get <page_id>
ata-blog notion-page get <page_id>

# Search articles by title
ata-blog notion-page search "azure functions"
ata-blog notion-page search "powershell" --status "Draft"

# Update article properties
ata-blog notion-page update <page_id> --status "Draft"
ata-blog notion-page update <page_id> --status "Developmental Review"
ata-blog notion-page update <page_id> --property "Keywords:azure, cloud"
ata-blog notion-page update <page_id> -s "Draft" -p "Dev Review Iterations:2"

# Manage article content
ata-blog notion-page content get <page_id>                    # Output to stdout
ata-blog notion-page content get <page_id> --output ./post.md # Save to file
ata-blog notion-page content set <page_id> --file ./post.md   # Replace content
ata-blog notion-page content append <page_id> --file ./add.md # Append content

# List valid status values
ata-blog notion-page statuses
ata-blog notion-page statuses --json

# Publish article to WordPress
ata-blog notion-page publish <page_id>
ata-blog notion-page publish <page_id> --status publish
ata-blog notion-page publish <page_id> --auto-schedule  # Find next available slot
```

### WordPress Post (Passthrough)

Passthrough to `wordpress posts` commands.

```bash
# List posts
ata-blog wordpress-post list
ata-blog wordpress-post list -- --limit 10

# Get post details
ata-blog wordpress-post get <post_id>
ata-blog wordpress-post get <post_id> --

# Create post
ata-blog wordpress-post create -- --from-markdown content.md --status draft

# Update post
ata-blog wordpress-post update <post_id> -- --status publish

# Delete post
ata-blog wordpress-post delete <post_id>
```

### WordPress Admin

Manage ATA Blog WordPress admin operations without calling the underlying `wordpress` CLI directly.

```bash
# List installed plugins
ata-blog wordpress-admin plugins list
ata-blog wordpress-admin plugins list --status active --properties "name,status,version"

# Get plugin details
ata-blog wordpress-admin plugins get <plugin>
ata-blog wordpress-admin plugins get <plugin> --properties "name,status,version"

# Maintenance actions
ata-blog wordpress-admin plugins upgrade <plugin>
ata-blog wordpress-admin plugins activate <plugin>
ata-blog wordpress-admin plugins deactivate <plugin>
ata-blog wordpress-admin plugins install <slug> --activate
ata-blog wordpress-admin plugins delete <plugin>
```

### Media (WordPress Passthrough)

Passthrough to `wordpress media` commands.

```bash
# List media
ata-blog media list
ata-blog media list -- --limit 10

# Upload media
ata-blog media upload /path/to/image.png

# Delete media
ata-blog media delete <media_id>
```

### Categories (WordPress Passthrough)

Passthrough to `wordpress categories` commands.

```bash
# List categories
ata-blog categories list
ata-blog categories list -- --limit 20

# Get category details
ata-blog categories get <category_id>

# Create category
ata-blog categories create "New Category"
```

### Tags (WordPress Passthrough)

Passthrough to `wordpress tags` commands.

```bash
# List tags
ata-blog tags list
ata-blog tags list -- --limit 20

# Get tag details
ata-blog tags get <tag_id>

# Create tag
ata-blog tags create "New Tag"
```

### Raptive Ads

Manage Raptive (AdThrive) ad settings on WordPress posts.

```bash
# Disable all ads on a post
ata-blog raptive disable <post_id>

# Disable only content ads
ata-blog raptive disable <post_id> --content-only

# Disable only video auto-insert
ata-blog raptive disable <post_id> --video-only

# Disable with auto re-enable after 30 days
ata-blog raptive disable <post_id> --re-enable-days 30

# Disable with specific re-enable date
ata-blog raptive disable <post_id> --re-enable-date 2026-02-01

# Re-enable all ads on a post
ata-blog raptive enable <post_id>

# Re-enable only content ads
ata-blog raptive enable <post_id> --content-only

# Check ad status for a post
ata-blog raptive status <post_id>
ata-blog raptive status <post_id>

# List all Raptive meta field names
ata-blog raptive fields
```

#### Raptive Meta Fields

| Field | Meta Key | Description |
|-------|----------|-------------|
| all | `adthrive_ads_disable` | Disable ALL ads (display, sidebar, footer) |
| content | `adthrive_ads_disable_content_ads` | Disable only in-content/article ads |
| video | `adthrive_ads_disable_auto_insert_videos` | Disable auto-insert video players |
| metadata | `adthrive_ads_disable_metadata` | Disable video metadata |
| re_enable | `adthrive_ads_re_enable_ads_on` | Unix timestamp to auto re-enable ads |

### Schema (Rank Math)

Manage Rank Math schema markup on WordPress posts.

```bash
# List posts with schema information
ata-blog schema list
ata-blog schema list --limit 100

# Get schema for a specific post
ata-blog schema get <post_id>
ata-blog schema get <post_id>
ata-blog schema get <post_id> --json

# List available schema types
ata-blog schema types

# Set schema on a post
ata-blog schema set <post_id> Article
ata-blog schema set <post_id> TechArticle --proficiency Intermediate
ata-blog schema set <post_id> Review --rating 4.5 --item "Azure DevOps"

# Remove schema from a post
ata-blog schema remove <post_id>
```

### Earnings

Query Raptive ad earnings and revenue data for posts.

```bash
# List earnings for all posts
ata-blog earnings list
ata-blog earnings list
ata-blog earnings list --period last7d --limit 20

# Get earnings for a specific post
ata-blog earnings get <post_id>
ata-blog earnings get <slug>
ata-blog earnings get 26786 --period last7d

# Filter by post title or ID
ata-blog earnings list --post-id 26786
ata-blog earnings list --post-title "PowerShell"

# Filter by numeric thresholds
ata-blog earnings list --filter "earnings:gt:50"
ata-blog earnings list --filter "rpm:gt:20"

# Custom date range
ata-blog earnings list --start 2025-01-01 --end 2025-12-31
```

### Shoutouts

Manage sponsored shoutouts in WordPress posts.

```bash
# List shoutouts in a post
ata-blog shoutouts list <post_id>
ata-blog shoutouts list <post_id> --table
ata-blog shoutouts list <post_id> --limit 5

# List shoutouts for an ATABlogger sponsor
export ATABLOGGER_SPONSORS_FILE=/path/to/sponsors.json
ata-blog shoutouts list --sponsor Specops
ata-blog shoutouts list --sponsor Specops --properties post_id,slug,position,preview
```

## Output Formats

Commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

For passthrough commands, use `--` to pass the table flag to the wordpress CLI.

## Configuration

The wrapper stores configuration in `.env`:

```bash
# Notion Database ID for articles
NOTION_DATABASE_ID=2a317112-d9c8-42ee-a4d4-a2b8a5a20818

# Default values
DEFAULT_AUTHOR=Adam Bertram
DEFAULT_STATUS=draft
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/CLI not available error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Search and Update Article Status

```bash
# Find articles about Azure
ata-blog notion-page search "azure"

# Update an article's status in the pipeline
ata-blog notion-page update abc123def456 --status "Developmental Review"
```

### Export Article Content

```bash
# Export article to markdown file
ata-blog notion-page content get abc123def456 --output ./draft.md

# Edit locally, then push back
ata-blog notion-page content set abc123def456 --file ./draft.md
```

### List Articles Ready for Publishing

```bash
ata-blog notion-page list --status "Ready to Publish"
```

### Publish an Article as Draft

```bash
ata-blog notion-page publish abc123def456 --status draft
```

### Auto-Schedule Publication

```bash
# Automatically find next available slot (respects 2/day limit, 4hr gaps, no weekends)
ata-blog notion-page publish abc123def456 --auto-schedule
```

### List Recent Posts with jq

```bash
ata-blog wordpress-post list | jq '.[0:5] | .[].title'
```

### Export Categories to JSON

```bash
ata-blog categories list > categories.json
```

## Requirements

- Python 3.9+
- `wordpress` CLI installed and authenticated
- `notion` CLI installed and authenticated
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - pydantic

## License

MIT

## Additional Commands

### Cache

```bash
ata-blog cache --help
```

### Wordpress Page

```bash
ata-blog wordpress-page --help
```
