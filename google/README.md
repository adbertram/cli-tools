# Google CLI

Command-line interface for Google Workspace APIs (Docs, Drive, Sheets, Gmail, Calendar, Chat), Google Analytics, Google Search Console, and Google Cloud.

## Features

- **Google Docs**: Create, read, and manage documents
- **Google Drive**: List, search, download files
- **Google Sheets**: Create, read, update spreadsheets
- **Gmail**: List, search, read, send, reply, draft, archive messages; download attachments
- **Google Calendar**: List, search calendar events (read-only)
- **Google Analytics**: GA4 reports, top pages, traffic sources, real-time data
- **Google Search Console**: Request URL indexing, list verified sites
- **Google Chat**: List spaces, read messages, send messages
- **Google Cloud**: Manage Cloud projects (list, get, create, update, delete) and credentials (service accounts, API keys, OAuth clients)
- **Chrome Web Store**: Package extensions, upload packages, publish submissions, cancel pending submissions, manage rollout percentage, and update Store Listing metadata through browser automation
- **Looker Studio**: Search report assets, generate Linking API report creation URLs, and manage report permissions

## Setup

### 1. Install Dependencies

```bash
cd <cli-tools-root>/google
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -e .
```

### 2. Get Google OAuth2 Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing project
3. Enable the following APIs:
   - Google Docs API
   - Google Drive API
   - Google Sheets API
   - Gmail API
   - Google Calendar API
   - Search Console API
   - Google Analytics Data API
   - Google Analytics Admin API
   - Google Chat API (see [Chat Setup](#google-chat-setup) below)
   - Cloud Resource Manager API
   - Chrome Web Store API
   - Looker Studio API
4. Go to **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
5. Select **Desktop app** as application type
6. Download the JSON file and save as `credentials.json` in this directory

### 3. Add Shell Alias

**~/.zshrc or ~/.bashrc:**
```bash
alias google="<cli-tools-root>/google/venv/bin/google"
```

**~/.config/powershell/Microsoft.PowerShell_profile.ps1:**
```powershell
function google { & "<cli-tools-root>/google/venv/bin/google" @args }
```

### 4. Install Shell Completion

```bash
# From zsh
google --install-completion

# From bash
bash
google --install-completion
exit

# From PowerShell
pwsh
google --install-completion
exit
```

## Usage

### Authentication

The first time you run any command, you'll be prompted to authenticate via your browser. The token will be saved to `token.json` for subsequent use.

**Option 1: Authenticate with OAuth credentials (Recommended)**

If you have OAuth 2.0 Client ID and Client Secret from Google Cloud Console:

```bash
google auth login --oauth-client-id YOUR_CLIENT_ID --oauth-client-secret YOUR_CLIENT_SECRET
```

This will automatically create the `credentials.json` file and start the authentication flow.

**Option 2: Manually download credentials.json**

Follow the setup instructions above to download `credentials.json`, then run:

```bash
google auth login
```

**Check authentication status:**

```bash
google auth status
```

**Log out (remove saved token):**

```bash
google auth logout
```

### Google Docs

```bash
# List documents
google docs list
google docs list --limit 20
google docs list --filter "folder:<folder-id>"

# Get a document
google docs get <document-id>

# Read document content (text only)
google docs read <document-id>

# Create a new document
google docs create --title "My Document"

# Update a document (replaces entire content)
google docs update <document-id> --content "New content"
google docs update <document-id> --file content.md

# Export a document to various formats
google docs export <document-id> --format txt          # Plain text (default)
google docs export <document-id> --format md           # Markdown
google docs export <document-id> --format pdf -o doc.pdf
google docs export <document-id> --format docx -o doc.docx

# Update table cells (preserves table structure and formatting)
google docs tables update <document-id> --list                    # List all tables
google docs tables update <document-id> -t 0 -r 1 -c 1 --content "New value"  # By index
google docs tables update <document-id> -t 0 -l "Row Label" -c 1 --content "New value"  # By label
google docs tables update <document-id> --data '[{"table":0,"row":1,"col":1,"content":"Value"}]'
google docs tables update <document-id> --file updates.json
```

### Google Drive

```bash
# List files
google drive list
google drive list --limit 20

# Search for files
google drive search "budget"
google drive search "budget"

# Get file metadata
google drive get <file-id>

# Download a file
google drive download <file-id>
google drive download <file-id> --output ~/Downloads
```

### Google Sheets

```bash
# List spreadsheets
google sheets list
google sheets list --limit 20
google sheets list --filter "folder:<folder-id>"

# Get spreadsheet metadata
google sheets get <spreadsheet-id>

# Read spreadsheet data
google sheets read <spreadsheet-id>
google sheets read <spreadsheet-id> --range "Sheet1!A1:D10"
google sheets read <spreadsheet-id>

# Create a new spreadsheet
google sheets create --title "My Spreadsheet"

# Append values to a spreadsheet
google sheets append <spreadsheet-id> --values "John,Doe,john@example.com"
```

### Gmail

```bash
# List messages (includes attachment metadata if present)
google gmail list
google gmail list --limit 20
google gmail list --label INBOX

# Search messages
google gmail search "from:boss@example.com"
google gmail search "is:unread"

# Get message metadata (includes attachment metadata if present)
google gmail get <message-id>
google gmail get <message-id> --raw  # Full API response

# Read message content
google gmail read <message-id>

# Download attachments
google gmail download-attachment <message-id> --filename "document.pdf"
google gmail download-attachment <message-id> --attachment-id <att-id>
google gmail download-attachment <message-id> --all
google gmail download-attachment <message-id> --all --output ~/Downloads

# Send email
google gmail send --to "user@example.com" --subject "Hello" --body "Message body"

# Send email with attachments
google gmail send --to "user@example.com" --subject "Files attached" --body "See attached files" \
  --attach /path/to/file1.pdf --attach /path/to/file2.docx

# Send with CC/BCC
google gmail send --to "user@example.com" --subject "Team update" --body "Content" \
  --cc "team@example.com" --bcc "manager@example.com"

# Reply to a message (sender only)
google gmail reply <message-id> --body "Thanks for the update!"
google gmail reply <message-id> --body "See attached" --attach /path/to/file.pdf

# Reply to all recipients
google gmail reply-all <message-id> --body "Thanks everyone!"

# Create a draft
google gmail draft --to "user@example.com" --subject "Draft email" --body "Message body"

# Create draft with attachments
google gmail draft --to "user@example.com" --subject "Files attached" --body "See attached files" \
  --attach /path/to/file1.pdf --attach /path/to/file2.docx

# Archive messages (remove from inbox)
google gmail archive <message-id>
google gmail archive <message-id1> <message-id2>

# Manage labels on messages
google gmail labels list <message-id>
google gmail labels add <message-id> --label STARRED
google gmail labels remove <message-id> --label UNREAD
```

**Note:** The `send`, `reply`, and `reply-all` commands show a preview by default. Add `--confirm` to actually send the email.

### Google Cloud Projects

```bash
# List projects
google cloud projects list
google cloud projects list --table
google cloud projects list --limit 10
google cloud projects list --filter "state:eq:ACTIVE"
google cloud projects list --filter "labels.env:eq:prod"

# Get project details
google cloud projects get <project-id>
google cloud projects get <project-id> --table

# Create a project
google cloud projects create --project-id my-new-project --display-name "My New Project"
google cloud projects create --project-id my-new-project --display-name "My New Project" --parent "organizations/123456"

# Update a project
google cloud projects update <project-id> --display-name "New Display Name"
google cloud projects update <project-id> --labels "env=prod" --labels "team=platform"

# Delete a project
google cloud projects delete <project-id>
google cloud projects delete <project-id> --confirm
```

**Note:** After adding the `cloud-platform` scope, you must re-authenticate by deleting `token.json` and running any command to trigger the OAuth flow.

### Google Cloud Credentials

```bash
# List all credentials for a project
google cloud credentials list --project <project-id>
google cloud credentials list --project <project-id> --table

# List by type
google cloud credentials list --project <project-id> --type service-account
google cloud credentials list --project <project-id> --type api-key
google cloud credentials list --project <project-id> --type oauth-client

# Get credential details
google cloud credentials get <credential-id> --project <project-id> --type service-account
google cloud credentials get <key-id> --project <project-id> --type api-key

# Create a service account
google cloud credentials create --project <project-id> --type service-account --account-id my-sa --display-name "My Service Account"

# Create an API key
google cloud credentials create --project <project-id> --type api-key --display-name "My API Key"

# Update a service account
google cloud credentials update <email> --project <project-id> --type service-account --display-name "New Name"

# Update an API key
google cloud credentials update <key-id> --project <project-id> --type api-key --display-name "New Name"

# Add a redirect URI to an OAuth client
google cloud credentials update <client-id> --project <project-id> --type oauth-client --add-redirect-uri "http://localhost:8080/callback"
```

**Note:** OAuth clients cannot be created via CLI. Use the [Google Cloud Console](https://console.cloud.google.com/apis/credentials) to create them. The `update` command supports adding redirect URIs to existing OAuth clients.

**Required APIs:** IAM API (`iam.googleapis.com`), API Keys API (`apikeys.googleapis.com`)

### Chrome Web Store

```bash
# Package an unpacked extension for Chrome Web Store upload
google webstore package . --output-dir dist/chrome-webstore
google webstore package . --output-dir dist/chrome-webstore --verify-command "npm test"
google webstore package . --output-dir dist/chrome-webstore --exclude "scripts/**"

# Fetch item status
google webstore status --publisher-id <publisher-id> --item-id <extension-id>
google webstore status --publisher-id <publisher-id> --item-id <extension-id> --table
google webstore status  # Uses CWS_PUBLISHER_ID and CWS_EXTENSION_ID when set
google webstore get --publisher-id <publisher-id> --item-id <extension-id>

# Upload a package to an existing item
google webstore upload --publisher-id <publisher-id> --item-id <extension-id> ./extension.zip

# Package and upload an unpacked extension without submitting it
google webstore upload-extension . --publisher-id <publisher-id> --item-id <extension-id>

# Submit for review and publish after approval
google webstore publish --publisher-id <publisher-id> --item-id <extension-id>

# Package, upload, and submit for review
google webstore release . --publisher-id <publisher-id> --item-id <extension-id>

# Stage after approval instead of publishing immediately
google webstore publish --publisher-id <publisher-id> --item-id <extension-id> --publish-type STAGED_PUBLISH
google webstore release . --publisher-id <publisher-id> --item-id <extension-id> --publish-type STAGED_PUBLISH

# Submit with initial rollout percentage or skip-review attempt
google webstore publish --publisher-id <publisher-id> --item-id <extension-id> --deploy-percentage 25
google webstore publish --publisher-id <publisher-id> --item-id <extension-id> --skip-review

# Cancel a pending submission
google webstore cancel-submission --publisher-id <publisher-id> --item-id <extension-id>

# Increase published rollout percentage
google webstore rollout --publisher-id <publisher-id> --item-id <extension-id> --deploy-percentage 100

# Update Store Listing overview fields and image assets through the Developer Dashboard
google auth login --credential-type browser_session
google webstore listing update --publisher-id <publisher-id> --item-id <extension-id> --listing-file store-assets/chrome-webstore-listing.md
```

`--publisher-id` and `--item-id` default to `CWS_PUBLISHER_ID` and `CWS_EXTENSION_ID` for all Web Store item commands. Packaging excludes repository-only files such as dotfiles, `node_modules`, `tests`, `dist`, build outputs, local agent files, and private keys. Use repeated `--exclude` options for project-specific paths that are not extension code. Packaging also rejects remote hosted script references in packaged HTML and JavaScript.

**Dashboard-only fields:** Store listing, Privacy, Distribution, visibility, and first-time item creation still require the Chrome Web Store Developer Dashboard. The public API v2 does not expose those operations. `google webstore listing update` uses a saved browser session to edit Store Listing overview fields and image assets in the dashboard. Title and summary are package-derived in the dashboard and are updated through the extension package. When an item is pending, submitted, or otherwise in review, the dashboard locks Store Listing fields; run listing updates before submitting for review or after review completes.
For screenshots, declare one `- Screenshots: \`path/to/folder/\`` line in the listing file; the command uploads every PNG in that folder in natural filename order, with the Chrome Web Store limit of 1-5 screenshots. Screenshots that are not 1280x800 or are not 24-bit RGB PNGs are converted to generated 1280x800 RGB PNG upload assets before the dashboard upload.

**Note:** After adding the `chromewebstore` scope, re-authenticate with `google auth login --force`.

### Google Analytics

```bash
# List GA4 accounts and properties
google analytics accounts
google analytics accounts --table

# List GA4 properties
google analytics properties
google analytics properties --table

# Top pages by pageviews (last 7 days)
google analytics top-pages --table
google analytics top-pages --days 30 --limit 20 --table

# Traffic sources breakdown
google analytics traffic --table
google analytics traffic --days 30 --table

# Real-time active users
google analytics realtime --table

# Custom report
google analytics report --metrics sessions,activeUsers --dimensions date --start 2026-03-01 --end 2026-03-12 --table
google analytics report --metrics screenPageViews --dimensions pagePath --days 7 --limit 20 --order-by screenPageViews --table
```

**Configuration:**

Set the `GOOGLE_ANALYTICS_PROPERTY_ID` environment variable to your GA4 property ID:

```bash
export GOOGLE_ANALYTICS_PROPERTY_ID="123456789"
```

Or use the `--property` flag to override per-command.

**Note:** After adding the `analytics.readonly` scope, you must re-authenticate: `google auth login --force`.

### Looker Studio

```bash
# List report assets
google lookerstudio reports list
google lookerstudio reports list --title "Example" --limit 25
google lookerstudio reports list --owner owner@example.com --order-by title --table

# Get a report asset by report ID
google lookerstudio reports get <report-id>
google lookerstudio reports get <report-id> --properties name,title,owner

# Generate a Linking API URL for creating a report from an existing report
google lookerstudio reports create-link --report-id <report-id> --report-name "Example Dashboard"

# Generate a Linking API URL with a Google Analytics data source configuration
google lookerstudio reports create-link \
  --report-id <report-id> \
  --report-name "Example Dashboard" \
  --ga-alias ds0 \
  --ga-account-id <ga-account-id> \
  --ga-property-id <ga4-property-id> \
  --ga-refresh-fields false

# Generate a Linking API URL that updates data source parameters at report creation time
google lookerstudio reports update-link <report-id> --data-source "ds0.propertyId=<ga4-property-id>"

# Manage report permissions
google lookerstudio reports permissions-get <report-id>
google lookerstudio reports permissions-add-members <report-id> --role VIEWER --member user:client@example.com
google lookerstudio reports permissions-patch <report-id> --permissions-json '{"VIEWER":{"members":["user:client@example.com"]}}'
google lookerstudio reports permissions-revoke-all <report-id> --member user:client@example.com
```

Looker Studio calls use the public Looker Studio API names. There is no API resource named `template`; a reusable template is a regular report used with the Linking API `c.reportId` parameter. `create-link` and `update-link` generate URLs for `https://lookerstudio.google.com/reporting/create`; they do not mutate the source report. Report data source parameters use the Linking API shape `alias.key=value`, for example `ds0.propertyId=213025502`.

**Workspace requirement:** The Looker Studio REST API is available only to users in Google Workspace or Cloud Identity organizations, and the organization admin must authorize the app for the `datastudio` scope. After adding the Looker Studio scope, re-authenticate with `google auth login --force`.

### Google Calendar

```bash
# List upcoming events (default: 7 days)
google calendar list
google calendar list --days 14

# List today's events
google calendar today
google calendar today

# Search events
google calendar search "meeting"
google calendar search "standup"

# Get specific event
google calendar get <event-id>
```

### Google Chat

#### Google Chat Setup

The Google Chat API requires a configured Chat app in your Google Cloud project, even when using user OAuth credentials. This is a one-time setup:

1. Go to the [Chat API Configuration](https://console.cloud.google.com/apis/api/chat.googleapis.com/hangouts-chat) page
2. Fill in **App name** (up to 25 characters), **Avatar URL** (HTTPS URL to a square PNG/JPEG), and **Description** (up to 40 characters)
3. Click **Save**

Without this configuration, all Chat commands will fail with a 404 "Google Chat app not found" error.

**Note:** After adding the chat scopes, you must re-authenticate: `google auth login --force`.

#### Chat Commands

```bash
# List spaces the user belongs to
google chat spaces list
google chat spaces list --table
google chat spaces list --limit 20
google chat spaces list --filter "type:eq:SPACE"
google chat spaces list --filter "type:eq:DM"

# Get details of a specific space
google chat spaces get <space-id>
google chat spaces get <space-id> --table

# List messages in a space
google chat messages list --space <space-id>
google chat messages list --space <space-id> --table
google chat messages list --space <space-id> --limit 50

# Get a specific message
google chat messages get <message-name>

# Send a message (preview by default)
google chat send --space <space-id> --text "Hello!"
google chat send --space <space-id> --text "Hello!" --confirm
```

### Google Search Console

```bash
# List verified sites
google searchconsole sites list
google searchconsole sites list

# Get details for a specific site
google searchconsole sites get https://example.com/

# Request URL indexing
google searchconsole index https://example.com/page
google searchconsole index https://example.com/new-article --site-url https://example.com/
```

**Configuration:**

Set the `GOOGLE_SEARCHCONSOLE_SITE` environment variable to your verified Search Console property URL:

```bash
export GOOGLE_SEARCHCONSOLE_SITE="https://example.com/"
```

Or use the `--site-url` flag to override per-command.

## Filter Syntax

All `list` commands support both standard CLI filter format and Google API-native query syntax.

### Standard Filter Format

Use `field:operator:value` syntax with these operators:

- `eq` - equals (default if operator omitted)
- `ne` - not equals
- `in` - value in list (use `|` to separate: `value1|value2`)
- `nin` - value not in list
- `gt`, `gte`, `lt`, `lte` - comparison operators
- `like`, `ilike` - pattern matching (case-sensitive/insensitive)

**Examples:**

```bash
# Gmail: Standard format
google gmail list --filter "from:eq:boss@example.com"
google gmail list --filter "unread:eq:true"
google gmail list --filter "from:in:user1@test.com|user2@test.com"

# Drive: Standard format
google drive list --filter "folder:eq:ABC123"
google drive list --filter "mimeType:eq:application/pdf"
google drive list --filter "name:like:%report%"

# Calendar: Standard format
google calendar list --filter "summary:eq:standup"
google calendar list --filter "after:gte:2024-01-01"
```

### Native Google API Format

You can also use Google's native query syntax for backward compatibility:

**Gmail native syntax:**
```bash
google gmail list --filter "from:boss@example.com"
google gmail list --filter "is:unread"
google gmail list --filter "has:attachment"
google gmail list --filter "subject:meeting"
```

**Drive native syntax:**
```bash
google drive list --filter "folder:ABC123"
google drive list --filter "mimeType:application/pdf"
google drive list --filter "name:report"
```

**Calendar native syntax:**
```bash
google calendar list --filter "q:standup"
```

Both formats work interchangeably and can be mixed in the same command.

## Output Formats

All commands output JSON by default to stdout (for piping to tools like `jq`):

```bash
# Get all document IDs
google drive list | jq '.[].id'

# Get message subjects
google gmail list | jq '.[].subject'
```


```bash
google drive list
google gmail list
google calendar list
```

## Cache

```bash
# Show cache commands
google cache --help

# Clear cached responses
google cache clear
```

## Troubleshooting

### Authentication Errors

If you encounter authentication issues:
1. Delete `token.json` to force re-authentication
2. Verify `credentials.json` is present and valid
3. Ensure all required APIs are enabled in Google Cloud Console

### Missing Credentials

If you see "Missing credentials" error:
1. Download credentials.json from Google Cloud Console
2. Place it in the `<cli-tools-root>/google/` directory
3. Or set `GOOGLE_CREDENTIALS_PATH` environment variable

## API Scopes

This CLI requests the following OAuth2 scopes:

- `https://www.googleapis.com/auth/documents` - Full access to Google Docs
- `https://www.googleapis.com/auth/drive` - Full access to Google Drive
- `https://www.googleapis.com/auth/spreadsheets` - Full access to Google Sheets
- `https://www.googleapis.com/auth/gmail.modify` - Read and modify Gmail messages and drafts
- `https://www.googleapis.com/auth/gmail.send` - Send Gmail messages
- `https://www.googleapis.com/auth/calendar.readonly` - Read-only Calendar access
- `https://www.googleapis.com/auth/webmasters` - Full access to Search Console
- `https://www.googleapis.com/auth/cloud-platform` - Full access to Google Cloud resources
- `https://www.googleapis.com/auth/analytics.readonly` - Read-only Google Analytics access
- `https://www.googleapis.com/auth/chat.spaces.readonly` - Read-only Chat spaces access
- `https://www.googleapis.com/auth/chat.messages.readonly` - Read-only Chat messages access
- `https://www.googleapis.com/auth/chat.messages` - Read/write Chat messages
- `https://www.googleapis.com/auth/chat.memberships.readonly` - Read-only Chat memberships access
- `https://www.googleapis.com/auth/chromewebstore` - Manage Chrome Web Store items through API v2
- `https://www.googleapis.com/auth/datastudio` - Manage Looker Studio assets and permissions
