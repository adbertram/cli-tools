# Buttondown CLI

Command-line access to the Buttondown REST API for subscribers, emails, and tags.

## Installation

```bash
uv tool install -e <cli-tools-root>/buttondown --force --refresh
```

## Quick Start

```bash
buttondown auth login
buttondown auth status
buttondown subscribers list --limit 25 --table
buttondown emails list --filter "status:eq:draft" --properties "id,subject,status"
buttondown tags list --table
```

## Profiles

Profiles store separate Buttondown credentials and settings.

```bash
buttondown auth profiles list
buttondown auth profiles create work
buttondown --profile work auth login
buttondown --profile work subscribers list --limit 10
buttondown auth profiles select work
```

## Commands

### Authentication

```bash
buttondown auth login
buttondown auth login --force
buttondown auth status
buttondown auth status --table
buttondown auth logout
buttondown auth refresh
buttondown auth profiles list
buttondown auth profiles create PROFILE
buttondown auth profiles get PROFILE
buttondown auth profiles select PROFILE
```

### Subscribers

```bash
buttondown subscribers list
buttondown subscribers list --limit 50 --filter "email_address:ilike:example.com"
buttondown subscribers list --filter "type:eq:regular" --properties "id,email_address,type"
buttondown subscribers list --table

buttondown subscribers get SUBSCRIBER_ID_OR_EMAIL
buttondown subscribers get SUBSCRIBER_ID_OR_EMAIL --table

buttondown subscribers create --email reader@example.com
buttondown subscribers create --email reader@example.com --tag vip --metadata '{"source":"cli"}'

buttondown subscribers update SUBSCRIBER_ID_OR_EMAIL --notes "Requested updates"
buttondown subscribers update SUBSCRIBER_ID_OR_EMAIL --type unsubscribed

buttondown subscribers delete SUBSCRIBER_ID_OR_EMAIL --force
buttondown subscribers send-link SUBSCRIBER_ID_OR_EMAIL
buttondown subscribers remind SUBSCRIBER_ID_OR_EMAIL
```

Supported subscriber filters include `email_address`, `domain`, `tag`, `type`, `source`, `creation_date`, `open_rate`, `click_rate`, `risk_score`, `utm_campaign`, `utm_medium`, and `utm_source`.

### Emails

```bash
buttondown emails list
buttondown emails list --limit 25 --filter "status:eq:draft"
buttondown emails list --filter "subject:ilike:launch" --properties "id,subject,status"
buttondown emails list --table

buttondown emails get EMAIL_ID
buttondown emails get EMAIL_ID --properties "id,subject,body"

buttondown emails create --subject "Newsletter draft" --body "Hello readers"
buttondown emails create --subject "Newsletter draft" --body-file ./draft.md

buttondown emails update EMAIL_ID --subject "Updated subject"
buttondown emails update EMAIL_ID --body-file ./updated.md

buttondown emails delete EMAIL_ID --force
buttondown emails send-draft EMAIL_ID --recipient test@example.com
buttondown emails send-draft EMAIL_ID --subscriber SUBSCRIBER_ID
```

Supported email filters include `status`, `source`, `subject`, `archival_mode`, `email_type`, `creation_date`, `publish_date`, `deliveries`, `open_rate`, and `click_rate`.

### Tags

```bash
buttondown tags list
buttondown tags list --limit 50 --filter "id:eq:tag_123"
buttondown tags list --properties "id,name,color"
buttondown tags list --table

buttondown tags get TAG_ID
buttondown tags get TAG_ID --table

buttondown tags create --name VIP --color "#FFD700"
buttondown tags create --name VIP --color "#FFD700" --subscriber-editable

buttondown tags update TAG_ID --name "Paid readers"
buttondown tags update TAG_ID --color "#00AAFF"

buttondown tags delete TAG_ID --force
buttondown tags analytics TAG_ID
buttondown tags analytics TAG_ID --table
```

Supported tag filters include `id` and `ids`.

## Output Formats

JSON is the default output format.

```bash
buttondown subscribers list --limit 2
buttondown subscribers list --limit 2 --table
buttondown subscribers list --properties "id,email_address,type"
```

List and get commands support dot-notation with `--properties`.

```bash
buttondown subscribers get reader@example.com --properties "id,email_address,metadata.source"
```

## Filtering

List commands use standard `field:op:value` filters.

```bash
buttondown subscribers list --filter "type:eq:regular"
buttondown subscribers list --filter "tag:in:vip|customers"
buttondown emails list --filter "status:ne:sent"
buttondown emails list --filter "creation_date:gte:2026-01-01"
```

Unsupported filters fail with a clear error instead of fetching all data and filtering locally.

## Configuration

Credentials are stored in profile `.env` files managed by `buttondown auth login`.

```bash
API_KEY=your_buttondown_api_key
BASE_URL=https://api.buttondown.com/v1
```

Buttondown expects API key authentication with this header:

```text
Authorization: Token <API_KEY>
```

## Options Reference

| Option | Short | Description |
| --- | --- | --- |
| `--version` | `-v` | Show version and exit |
| `--no-cache` | | Bypass response cache |
| `--profile` | | Use a specific authentication profile |
| `--table` | `-t` | Display output as a table |
| `--limit` | `-l` | Maximum list results |
| `--filter` | `-f` | Filter list results |
| `--properties` | `-p` | Comma-separated fields to include |
| `--force` | `-F` | Skip confirmation or force auth refresh |

## Models

The client returns Pydantic models for all API resources.

| Model | Purpose |
| --- | --- |
| `Subscriber` | Subscriber list, get, create, and update responses |
| `Email` | Email list, get, create, and update responses |
| `Tag` | Tag list, get, create, and update responses |
| `TagAnalytics` | Tag analytics responses |
| `ActionResult` | Delete and send-action acknowledgements |

Models preserve extra API response fields so JSON output includes Buttondown fields that are added after this CLI version.

## Exit Codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | General error |
| 2 | Authentication or credential error |
| 130 | User interrupted |

## Requirements

- Python 3.9+
- `typer`
- `requests`
- `pydantic`
- `cli-tools-shared`

## Additional Commands

### Automations

```bash
buttondown automations --help
```

### Feeds

```bash
buttondown feeds --help
```
