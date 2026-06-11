# WordPress CLI

## DESCRIPTION

The `wordpress` CLI provides a command-line interface for Wordpress API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
cd wordpress
pip install -e .
```

After installation, the `wordpress` command will be available in your terminal.

## Quick Start

### 1. Configure Your Environment

Create a `.env` file in the wordpress CLI directory with your WordPress credentials:

```bash
# WordPress site URL
URL=https://example.com

# WordPress username
USERNAME=your_username

# WordPress Application Password (NOT your account password)
# Generate this in WordPress admin: Users > Profile > Application Passwords
PASSWORD=your_application_password

# Optional secondary WordPress.com bundle for native Jetpack plugin upgrades.
WPCOM_CLIENT_ID=your_wpcom_oauth_client_id
WPCOM_CLIENT_SECRET=your_wpcom_oauth_client_secret
WPCOM_SITE=your-site.com
WPCOM_REDIRECT_URI=https://localhost.example/callback
WPCOM_ACCESS_TOKEN=auto_saved_by_wordpress_org_token
```

### 2. Verify Authentication

```bash
wordpress auth status
wordpress auth status
```

### 3. Create Your First Post

```bash
# Create a draft from manual HTML content
wordpress posts create --title "My First Post" --content "<p>Hello World!</p>" --status draft

# Create a draft from a DOCX file
wordpress posts create --from-docx ~/Downloads/my-article.docx --slug "my-article"

# Create from Markdown and publish
wordpress posts create --from-markdown ~/blog-post.md --status publish

# Add sponsored link attributes automatically
wordpress posts create --title "Review" --content "<p><a href='https://example.com'>Link</a></p>" --sponsored
```

### 4. List Your Posts

```bash
wordpress posts list
wordpress posts list
wordpress posts list --filter status=publish --limit 20
```

## Authentication

### Configuration

WordPress CLI requires the WordPress site credentials below. Native plugin version upgrades use a separate WordPress.com credential bundle and an auto-saved OAuth token for the Jetpack management API.

```env
URL=https://your-site.com
USERNAME=your_username
PASSWORD=your_application_password
WPCOM_CLIENT_ID=your_wpcom_oauth_client_id
WPCOM_CLIENT_SECRET=your_wpcom_oauth_client_secret
WPCOM_SITE=your-site.com
WPCOM_REDIRECT_URI=https://localhost.example/callback
WPCOM_ACCESS_TOKEN=auto_saved_by_wordpress_org_token
```

### WordPress.com Token Setup

Save the secondary WordPress.com credential bundle once:

```bash
wordpress org token save-credential \
  --client-id your-client-id \
  --client-secret your-client-secret \
  --site your-site.com \
  --redirect-uri https://localhost.example/callback
```

Acquire and save a WordPress.com OAuth token through browser approval:

```bash
wordpress org token
```

The command prints the authorization URL, opens it in your default browser, waits for you to approve access, then prompts you to paste the full redirect URL or the authorization code. It saves `WPCOM_ACCESS_TOKEN` into the active profile `.env` and does not print the raw token.

If any required WordPress.com fields are missing, the CLI fails with an exact missing-field list and tells you to rerun:

```bash
wordpress org token save-credential --client-id ... --client-secret ... --site ... --redirect-uri ...
```

### Setting Up Application Password

WordPress Application Passwords are separate from your account password and can be revoked without changing your main login:

1. Log in to WordPress Admin
2. Navigate to **Users** > **Your Profile**
3. Scroll to **Application Passwords**
4. Enter a name (e.g., "CLI Tool")
5. Click **Create Application Password**
6. Copy the generated password to your `.env` file

### Interactive Login

Configure WordPress credentials interactively:

```bash
# Login with prompts for URL, username, and application password
wordpress auth login

# Force re-authentication (clear existing credentials)
wordpress auth login --force
```

The login command will:
1. Prompt for your WordPress site URL
2. Prompt for your WordPress username
3. Prompt for your Application Password (input hidden)
4. Save credentials to `.env` file
5. Verify authentication with a test API call

### Check Authentication Status

```bash
# JSON output
wordpress auth status

# Table format
wordpress auth status
```

### Clear Credentials

To remove stored credentials:

```bash
wordpress auth logout
```

## Posts Commands

### List Posts

List all posts with filtering and output customization:

```bash
# Basic list (JSON format)
wordpress posts list

# Table format
wordpress posts list

# Limit results
wordpress posts list --limit 20

# Filter by status
wordpress posts list --filter status=publish

# Multiple filters
wordpress posts list --filter "status=draft,author=1"

# Select specific fields to display
wordpress posts list --output "id,title,status"

# Nested field access (dot notation)
wordpress posts list --output "id,title.rendered,status"
```

**Output Format Options:**

- Default (JSON): Machine-readable output for scripting and piping

**Common Filters:**

| Filter | Values | Example |
|--------|--------|---------|
| `status` | publish, draft, pending, private | `status=publish` |
| `author` | user ID | `author=1` |
| `search` | search string | `search=wordpress` |

### Get Post Details

Retrieve full details for a specific post:

```bash
# JSON output
wordpress posts get 123

# Table format
wordpress posts get 123

# Select specific fields
wordpress posts get 123 --output "id,title,status,date"

# Nested fields
wordpress posts get 123 --output "title.rendered,content.rendered"
```

### Create Posts

Create new posts from various sources:

#### From Manual HTML Content

```bash
# Create draft
wordpress posts create --title "My Post" --content "<p>Content here</p>" --status draft

# With custom slug
wordpress posts create --title "My Post" --content "<p>Content here</p>" --slug "my-custom-slug"

# Publish immediately
wordpress posts create --title "My Post" --content "<p>Content here</p>" --status publish
```

#### From DOCX Files

Automatically extracts title from the first heading, uploads embedded images, and converts to WordPress block format:

```bash
# Create draft from DOCX
wordpress posts create --from-docx /path/to/article.docx --slug "article-slug"

# Publish immediately
wordpress posts create --from-docx ~/Documents/blog-post.docx --status publish --slug "blog-post"
```

**DOCX Processing:**
- Title is extracted from the first heading (h1) and removed from content
- All images are automatically uploaded to WordPress media library
- Content is converted from DOCX to WordPress block editor format
- All links automatically receive `rel="nofollow"` by default

#### From Markdown Files

Convert Markdown to WordPress block format:

```bash
# Create draft from Markdown
wordpress posts create --from-markdown ~/blog/post.md --slug "post-slug"

# Override title
wordpress posts create --from-markdown ~/blog/post.md --title "Custom Title" --status draft

# Publish immediately
wordpress posts create --from-markdown ~/blog/post.md --status publish
```

**Markdown Processing:**
- If no `--title` is provided, uses the filename (with formatting applied)
- Content is converted from Markdown to WordPress block format
- Title is required (auto-generated from filename if not provided)

#### Add Sponsored Links

Automatically add `rel="sponsored nofollow"` to all links in the post:

```bash
# For manual content
wordpress posts create --title "Review" --content "<p><a href='https://example.com'>Link</a></p>" --sponsored

# For DOCX files
wordpress posts create --from-docx ~/review.docx --slug "review" --sponsored

# For Markdown files
wordpress posts create --from-markdown ~/review.md --slug "review" --sponsored
```

### Update Posts

Update an existing post:

```bash
# Update title
wordpress posts update 123 --title "New Title"

# Update status
wordpress posts update 123 --status publish

# Update slug
wordpress posts update 123 --slug "new-slug"

# Multiple updates at once
wordpress posts update 123 --title "New Title" --status publish --slug "new-slug"

# Update content
wordpress posts update 123 --content "<p>New content here</p>"
```

### Delete Posts

Delete a post (move to trash or permanently delete):

```bash
# Move to trash
wordpress posts delete 123

# Permanently delete (skip trash)
wordpress posts delete 123 --force
```

## Media Commands

### List Media Items

List all media in your library with filtering and output customization:

```bash
# Basic list (JSON format)
wordpress media list

# Table format
wordpress media list

# Limit results
wordpress media list --limit 50

# Filter by MIME type
wordpress media list --filter "mime_type=image/png"

# Filter by multiple criteria
wordpress media list --filter "mime_type=image/jpeg,author=1"

# Select specific fields
wordpress media list --output "id,title,mime_type"

# Show source URLs
wordpress media list --output "id,title,source_url"
```

**Common Filters:**

| Filter | Example | Description |
|--------|---------|-------------|
| `mime_type` | `mime_type=image/png` | Filter by file type |
| `mime_type` | `mime_type=image/jpeg` | JPEG images |
| `mime_type` | `mime_type=application/pdf` | PDF documents |
| `search` | `search=logo` | Search media by title |

### Upload Media

Upload a local file to your WordPress media library:

```bash
# Upload image
wordpress media upload ~/Downloads/screenshot.png

# Upload document
wordpress media upload ./documents/whitepaper.pdf

# Upload any file
wordpress media upload /path/to/file.ext
```

**Features:**
- Automatically detects file type (MIME type)
- Supports images, documents, and any media type
- Returns media ID and URL after upload
- File size is displayed during upload

### Delete Media

Delete media from your library:

```bash
# Move to trash
wordpress media delete 456

# Permanently delete (skip trash)
wordpress media delete 456 --force
```

## Categories Commands

### List Categories

List all categories with filtering and output customization:

```bash
# Basic list (JSON format)
wordpress categories list

# Table format
wordpress categories list

# Limit results
wordpress categories list --limit 20

# Filter by search term
wordpress categories list --filter search=wordpress

# Select specific fields
wordpress categories list --output "id,name,slug,count"
```

### Get Category Details

Retrieve full details for a specific category:

```bash
# JSON output
wordpress categories get 123

# Table format
wordpress categories get 123

# Select specific fields
wordpress categories get 123 --output "id,name,slug,description"
```

### Create Categories

Create new categories:

```bash
# Basic category
wordpress categories create --name "Technology"

# With custom slug
wordpress categories create --name "Programming" --slug "programming"

# With parent category
wordpress categories create --name "Python" --parent 123

# With description
wordpress categories create --name "News" --description "Latest news articles"
```

### Update Categories

Update existing categories:

```bash
# Update name
wordpress categories update 123 --name "Updated Name"

# Update slug
wordpress categories update 123 --slug "new-slug"

# Update description
wordpress categories update 123 --description "New description"

# Change parent category
wordpress categories update 123 --parent 456
```

### Delete Categories

Delete a category permanently:

```bash
# Permanently delete (no trash)
wordpress categories delete 123
```

**Note:** Categories are permanently deleted (no trash support).

## Tags Commands

### List Tags

List all tags with filtering and output customization:

```bash
# Basic list (JSON format)
wordpress tags list

# Table format
wordpress tags list

# Limit results
wordpress tags list --limit 20

# Filter by search term
wordpress tags list --filter search=python

# Select specific fields
wordpress tags list --output "id,name,slug,count"
```

### Get Tag Details

Retrieve full details for a specific tag:

```bash
# JSON output
wordpress tags get 123

# Table format
wordpress tags get 123

# Select specific fields
wordpress tags get 123 --output "id,name,slug,description"
```

### Create Tags

Create new tags:

```bash
# Basic tag
wordpress tags create --name "Python"

# With custom slug
wordpress tags create --name "JavaScript" --slug "javascript"

# With description
wordpress tags create --name "Tutorial" --description "Step-by-step guides"
```

### Update Tags

Update existing tags:

```bash
# Update name
wordpress tags update 123 --name "Updated Name"

# Update slug
wordpress tags update 123 --slug "new-slug"

# Update description
wordpress tags update 123 --description "New description"
```

### Delete Tags

Delete a tag permanently:

```bash
# Permanently delete (no trash)
wordpress tags delete 123
```

**Note:** Tags are permanently deleted (no trash support).

## Profiles Commands

### List Profiles

```bash
wordpress auth profiles list
wordpress auth profiles list --table
```

### Create Profile

```bash
wordpress auth profiles create staging
```

### Select Active Profile

```bash
wordpress auth profiles select staging
```

### Delete Profile

```bash
wordpress auth profiles delete staging
```

## Output Formats

All commands support two output formats:

### JSON Output (Default)

Machine-readable format suitable for scripting and piping to other tools:

```bash
wordpress posts list
wordpress posts get 123
wordpress media list
```

Use with `jq` for powerful filtering:

```bash
# Get all published post IDs
wordpress posts list --filter status=publish | jq '.[] | .id'

# Filter media by MIME type
wordpress media list | jq '.[] | select(.mime_type == "image/png")'

# Extract and format data
wordpress posts list | jq '.[] | {id, title: .title.rendered, status}'
```

### Table Output

Human-readable formatted tables:

```bash
# Posts table
wordpress posts list

# Media table
wordpress media list

# Filtered results in table
wordpress posts list --filter status=draft --limit 10
```

**Field Selection with Tables:**

Use `--output` to customize columns:

```bash
# Custom columns
wordpress posts list --output "id,title,status,date"

# Media with specific fields
wordpress media list --output "id,title,source_url"
```

## Options Reference

### Global Options

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results (default: 100) |
| `--filter` | `-f` | Filter results (format: key=value, comma-separated) |
| `--output` | `-o`, `-p` | Comma-separated fields to display (supports dot-notation for nested fields) |
| `--version` | `-v` | Show version and exit |

### Posts Create Options

| Option | Description |
|--------|-------------|
| `--title` | Post title (required for manual content) |
| `--content` | Post content HTML (required for manual content) |
| `--from-docx` | Path to DOCX file to convert |
| `--from-markdown` | Path to Markdown file to convert |
| `--slug` | URL slug (auto-generated if not provided) |
| `--status` | Post status: publish, draft, pending, private (default: draft) |
| `--sponsored` | Add `rel="sponsored nofollow"` to all links |

### Posts Update Options

| Option | Description |
|--------|-------------|
| `--title` | New post title |
| `--content` | New post content |
| `--status` | New post status |
| `--slug` | New URL slug |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Content Creation Workflows

**Convert a blog post from Word to WordPress:**

```bash
# 1. Convert DOCX to draft post
wordpress posts create --from-docx ~/blog/my-article.docx --slug "my-article"

# 2. Verify the post was created
wordpress posts get <post_id>

# 3. Publish when ready
wordpress posts update <post_id> --status publish
```

**Create a product review with affiliate links:**

```bash
# DOCX files process links automatically, but force sponsored tags
wordpress posts create \
  --from-docx ~/reviews/product-review.docx \
  --slug "product-review" \
  --sponsored
```

**Convert Markdown blog posts:**

```bash
# Process all markdown files in a directory
for file in ~/blog/*.md; do
  slug=$(basename "$file" .md)
  wordpress posts create --from-markdown "$file" --slug "$slug" --status draft
done
```

### Content Management

**List and export all draft posts:**

```bash
# List drafts
wordpress posts list --filter status=draft

# Export to JSON
wordpress posts list --filter status=draft > drafts.json

# Get specific fields for all posts
wordpress posts list --output "id,title,status,date" --limit 200
```

**Find and update posts:**

```bash
# Find a post by searching
wordpress posts list --filter "search=wordpress"

# Update the post
wordpress posts update <post_id> --status publish --title "Updated Title"

# Verify the update
wordpress posts get <post_id>
```

### Media Management

**Bulk upload images:**

```bash
# Upload all PNG files from a directory
for image in ~/downloads/*.png; do
  wordpress media upload "$image"
done
```

**List specific image types:**

```bash
# Find all JPEG images
wordpress media list --filter "mime_type=image/jpeg"

# Get URLs of all images
wordpress media list --output "title,source_url" --filter "mime_type=image/png"
```

**Organize by size:**

```bash
# Upload and track media
wordpress media list --output "id,title,source_url" > media-library.json
```

## Document Conversion Details

### DOCX to WordPress Conversion

When creating posts from DOCX files:

1. **Title extraction**: Extracts title from first heading (h1), removes it from content
2. **Image handling**: All embedded images are automatically uploaded to WordPress media library
3. **Link processing**: Links are converted to HTML with proper formatting
4. **Block conversion**: Content is converted to WordPress Block Editor (Gutenberg) format
5. **Link attributes**: Links receive `rel="nofollow"` by default (use `--sponsored` for `rel="sponsored nofollow"`)

### Markdown to WordPress Conversion

When creating posts from Markdown files:

1. **Title handling**: Uses provided `--title` or derives from filename
2. **Format conversion**: Markdown is converted to HTML with proper structure
3. **Block conversion**: HTML is converted to WordPress Block Editor format
4. **Link attributes**: Links receive default processing (use `--sponsored` for sponsored links)

### WordPress Block Editor Format

All content (both DOCX and Markdown) is automatically converted to WordPress Block Editor format:

- Paragraphs → `<!-- wp:paragraph -->` blocks
- Headings → `<!-- wp:heading -->` blocks with level attributes
- Lists → `<!-- wp:list -->` blocks
- Blockquotes → `<!-- wp:quote -->` blocks
- Code blocks → `<!-- wp:code -->` blocks with syntax highlighting

This ensures posts work seamlessly with WordPress's modern block editor.

## Configuration Files

### .env File Location

Profile `.env` files live under the CLI data directory:

```
~/.local/share/cli-tools/wordpress/authentication_profiles/<profile>/.env
```

### .env Format

```bash
# Required: WordPress site URL
URL=https://example.com

# Required: WordPress username
USERNAME=your_username

# Required: Application Password
# Generate in WordPress: Users > Profile > Application Passwords
PASSWORD=your_application_password

# Optional secondary WordPress.com bundle for native Jetpack plugin upgrades
WPCOM_CLIENT_ID=your_wpcom_oauth_client_id
WPCOM_CLIENT_SECRET=your_wpcom_oauth_client_secret
WPCOM_SITE=your-site.com
WPCOM_REDIRECT_URI=https://localhost.example/callback
WPCOM_ACCESS_TOKEN=auto_saved_by_wordpress_org_token
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer - CLI framework
  - python-dotenv - Environment variable management
  - requests - HTTP client
  - pydantic - Data validation
  - mammoth - DOCX to HTML conversion
  - markdown2 - Markdown to HTML conversion

## License

MIT

## Additional Commands

### Pages

```bash
wordpress pages --help
```

## Cache

```bash
wordpress cache status
wordpress cache clear
```

## Admin

```bash
wordpress admin plugins list
wordpress admin plugins get akismet
wordpress admin plugins upgrade akismet/akismet
wordpress org token --help
wordpress org token save-credential --help
```
