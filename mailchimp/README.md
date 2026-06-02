# Mailchimp CLI

A Python CLI tool for managing Mailchimp via the Marketing API v3.0.

## Features

- **Audiences/Lists Management**: Create and manage mailing lists
- **Signup Forms**: Create/customize and list audience signup forms
- **Members/Subscribers**: Add, update, remove, and search subscribers
- **Campaigns**: Create, send, and track email campaigns with optional sponsor-domain detection
- **Templates**: Browse and manage email templates
- **Reports**: View campaign analytics and performance metrics

## Installation

This CLI is already installed and available globally via the symlink:

```bash
mailchimp --help
```

### Setup

1. Get your API key from Mailchimp:
   - Log in to Mailchimp
   - Go to https://us1.admin.mailchimp.com/account/api/
   - Create or copy an existing API key
   - Format: `your-key-dc` (e.g., `abc123def456-us6`)

2. Configure authentication:
   ```bash
   mailchimp auth login --api-key YOUR_API_KEY
   # OR use interactive prompt:
   mailchimp auth login
   # OR provide the key on stdin:
   printf '%s\n' "$MAILCHIMP_API_KEY" | mailchimp auth login
   ```

3. Verify authentication:
   ```bash
   mailchimp auth status
   ```

## Usage

### Authentication

```bash
# Login with API key
mailchimp auth login --api-key YOUR_API_KEY

# Re-prompt and replace the stored key
mailchimp auth login --force

# Replace the stored key non-interactively
mailchimp auth login --force --api-key YOUR_API_KEY

# Check authentication status
mailchimp auth status

# Logout (clear credentials)
mailchimp auth logout
```

### Audiences/Lists

```bash
# List all audiences
mailchimp audiences list
mailchimp audiences list
mailchimp audiences list --count 20

# Get audience details
mailchimp audiences get LIST_ID
mailchimp audiences get LIST_ID

# Create a new audience
mailchimp audiences create \
  --name "Newsletter Subscribers" \
  --company "ACME Inc" \
  --address1 "123 Main St" \
  --city "New York" \
  --state "NY" \
  --zip "10001" \
  --country "US" \
  --from-email "newsletter@example.com" \
  --from-name "ACME Newsletter"
```

### Signup Forms

```bash
# List signup forms for an audience
mailchimp forms list LIST_ID
mailchimp forms list LIST_ID --table
mailchimp forms list LIST_ID --limit 1
mailchimp forms list LIST_ID --properties list_id,signup_form_url

# Get the default signup form for an audience
mailchimp forms get LIST_ID
mailchimp forms get LIST_ID --table

# Create or update the default signup form for an audience
mailchimp forms create LIST_ID \
  --header-text "Example beta" \
  --signup-message "Join the beta tester list." \
  --thank-you-title "You are on the list"
```

### Members/Subscribers

```bash
# List members in an audience
mailchimp members list LIST_ID
mailchimp members list LIST_ID
mailchimp members list LIST_ID --status subscribed
mailchimp members list LIST_ID --count 50

# Get member details
mailchimp members get LIST_ID user@example.com
mailchimp members get LIST_ID user@example.com

# Add a new member
mailchimp members add LIST_ID \
  --email user@example.com \
  --status subscribed \
  --first-name John \
  --last-name Doe

# Update a member
mailchimp members update LIST_ID user@example.com \
  --status unsubscribed

mailchimp members update LIST_ID user@example.com \
  --first-name Jane

# Remove a member
mailchimp members remove LIST_ID user@example.com
mailchimp members remove LIST_ID user@example.com --yes

# Search for members
mailchimp members search user@example.com
mailchimp members search user@example.com --list-id LIST_ID
mailchimp members search user@example.com
```

### Campaigns

```bash
# List campaigns
mailchimp campaigns list
mailchimp campaigns list --table
mailchimp campaigns list --status sent
mailchimp campaigns list --count 20

# List campaigns including RSS child campaigns (individual sends)
mailchimp campaigns list --include-rss-child-campaigns
mailchimp campaigns list --include-rss-child-campaigns --table

# List only child campaigns of a specific RSS campaign
mailchimp campaigns list --rss-parent-id RSS_CAMPAIGN_ID --table

# List child campaigns for an RSS campaign (dedicated command)
mailchimp campaigns children RSS_CAMPAIGN_ID
mailchimp campaigns children RSS_CAMPAIGN_ID --table

# Get campaign details
mailchimp campaigns get CAMPAIGN_ID
mailchimp campaigns get CAMPAIGN_ID --table

# Create a campaign
mailchimp campaigns create \
  --list-id LIST_ID \
  --subject "Monthly Newsletter" \
  --from-name "ACME Inc" \
  --reply-to "support@example.com" \
  --title "January Newsletter"

# Send a campaign
mailchimp campaigns send CAMPAIGN_ID
mailchimp campaigns send CAMPAIGN_ID --yes

# Pause/resume an RSS-Driven campaign
mailchimp campaigns pause RSS_CAMPAIGN_ID
mailchimp campaigns resume RSS_CAMPAIGN_ID

# Get campaign report/analytics
mailchimp campaigns report CAMPAIGN_ID
mailchimp campaigns report CAMPAIGN_ID --table
mailchimp campaigns report CAMPAIGN_ID --sponsor-domain specopssoft.com

# Get campaign content (HTML/text)
mailchimp campaigns content CAMPAIGN_ID
mailchimp campaigns content CAMPAIGN_ID --html
mailchimp campaigns content CAMPAIGN_ID --text
```

### Sponsor Domains

The CLI can detect domains in the "Messages from our Sponsors" section when domains are passed explicitly. Sponsor names and sponsor registries are owned by the calling project, not by this CLI.

```bash
mailchimp campaigns list --sponsor-domain specopssoft.com
mailchimp campaigns report CAMPAIGN_ID --sponsor-domain specopssoft.com
```

Matched domains appear as `sponsor_domains` in `campaigns list` and `campaigns report` output.

### Templates

```bash
# List templates
mailchimp templates list
mailchimp templates list
mailchimp templates list --type user
mailchimp templates list --count 20

# Get template details
mailchimp templates get TEMPLATE_ID
mailchimp templates get TEMPLATE_ID
```

## API Reference

### Authentication Methods

- **API Key**: HTTP Basic Auth with API key (recommended for personal use)
- **OAuth 2**: For apps that access other users' Mailchimp accounts

### Rate Limits

- **Concurrent Connections**: 10 simultaneous requests per user
- **Timeout**: 120 seconds per request
- **Error Code**: 429 when rate limit is exceeded

### Data Center Detection

The CLI automatically extracts the data center from your API key:
- API Key format: `key-dc` (e.g., `abc123-us6`)
- Base URL: `https://{dc}.api.mailchimp.com/3.0`

## Development

### Project Structure

```
mailchimp/
├── mailchimp_cli/
│   ├── __init__.py
│   ├── main.py           # CLI entry point
│   ├── client.py         # API client
│   ├── config.py         # Configuration management
│   ├── output.py         # Output formatting
│   ├── filters.py        # Filter validation
│   ├── filter_map.py     # Filter mappings
│   └── commands/
│       ├── __init__.py
│       ├── auth.py       # Authentication commands
│       ├── audiences.py  # Audience/list commands
│       ├── members.py    # Member/subscriber commands
│       ├── campaigns.py  # Campaign commands
│       └── templates.py  # Template commands
├── .env                  # Environment variables (gitignored)
├── .env.example          # Example environment file
├── pyproject.toml        # Project configuration
└── README.md             # This file
```

### Virtual Environment

The CLI uses a virtual environment at `venv/`:

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -e .

# Deactivate
deactivate
```

### Adding New Commands

1. Create a new command module in `mailchimp_cli/commands/`
2. Register it in `mailchimp_cli/main.py`
3. Add corresponding client methods in `mailchimp_cli/client.py`

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Troubleshooting

### Authentication Errors

If you get a 401 error:
1. Verify your API key is correct: `mailchimp auth status`
2. Check the data center in your API key matches your account
3. Re-login: `mailchimp auth login`

### Rate Limit Errors (429)

If you hit rate limits:
1. Reduce concurrent requests
2. Add delays between operations
3. Use pagination with smaller batch sizes

### Connection Errors

1. Check your internet connection
2. Verify the base URL is correct
3. Check Mailchimp service status

## Resources

- [Mailchimp Marketing API Documentation](https://mailchimp.com/developer/marketing/api/)
- [API Fundamentals](https://mailchimp.com/developer/marketing/docs/fundamentals/)
- [Get Your API Key](https://us1.admin.mailchimp.com/account/api/)
- [Quick Start Guide](https://mailchimp.com/developer/marketing/guides/quick-start/)

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests

## License

MIT

## Additional Commands

### Cache

```bash
mailchimp cache --help
```
