# WP Engine CLI

## DESCRIPTION

Command-line access to the WP Engine Hosting Platform API.
Use this CLI when agents or automation need JSON-first access to WP Engine accounts, sites, installs, cache purge operations, SSH keys, and documented SSH/SFTP connection details.

## Docs

- API overview: https://developers.wpengine.com/docs/managed-hosting-platform/api/
- API reference: https://api.wpengineapi.com/v1
- SSH/SFTP support: https://wpengine.com/support/ssh-gateway/

The CLI is JSON-first for automation. Add `--table` to commands that support a human-readable table.

## Installation

```bash
cd <cli-tools-root>/wpengine
uv tool install -e . --force --refresh
```

## Authentication

WP Engine API credentials come from WP Engine User Portal API Access. Use the API User ID as `USERNAME` and the API Password as `PASSWORD`.

```bash
wpengine auth login
wpengine auth status
wpengine auth test
wpengine auth logout
```

Profiles are supported through the repo-standard auth commands:

```bash
wpengine auth profiles list
wpengine auth profiles get default
wpengine auth profiles create staging
wpengine auth profiles select staging
wpengine auth profiles delete staging
```

## Commands

### API Status

```bash
wpengine api status
wpengine api status --table
wpengine api status --properties status,message
```

### Accounts

```bash
wpengine accounts list
wpengine accounts list --limit 25 --table
wpengine accounts list --filter "name:contains:ATA"
wpengine accounts list --properties "id,name"
wpengine accounts get ACCOUNT_ID
wpengine accounts get ACCOUNT_ID --table
wpengine accounts get ACCOUNT_ID --properties "id,name"
```

### Sites

```bash
wpengine sites list
wpengine sites list --limit 25 --table
wpengine sites list --filter "account_id:eq:ACCOUNT_ID"
wpengine sites list --filter "name:contains:ata"
wpengine sites list --properties "id,name,account_id"
wpengine sites get SITE_ID
wpengine sites get SITE_ID --table
wpengine sites get SITE_ID --properties "id,name"
```

### Environments

WP Engine documents these API resources as installs.

```bash
wpengine environments list
wpengine environments list --limit 25 --table
wpengine environments list --filter "account_id:eq:ACCOUNT_ID"
wpengine environments list --filter "name:contains:prod"
wpengine environments list --properties "id,name,environment,site_id,account_id"
wpengine environments get ENVIRONMENT_ID
wpengine environments get ENVIRONMENT_ID --table
wpengine environments get ENVIRONMENT_ID --properties "id,name,environment"
```

### Cache

```bash
wpengine cache purge ENVIRONMENT_ID --type all
wpengine cache purge ENVIRONMENT_ID --type object
wpengine cache purge ENVIRONMENT_ID --type page
wpengine cache purge ENVIRONMENT_ID --type cdn
wpengine cache purge ENVIRONMENT_ID --type all --table
```

### SSH

The connection and config commands derive documented SSH host, user, and remote path strings. They do not call the API or manage SSH login state.

```bash
wpengine ssh connection list
wpengine ssh connection get ENVIRONMENT_NAME
wpengine ssh connection get ENVIRONMENT_NAME --table
wpengine ssh connection get ENVIRONMENT_NAME --properties "host,user,remote_root,command"

wpengine ssh config list
wpengine ssh config get ENVIRONMENT_NAME
wpengine ssh config get ENVIRONMENT_NAME --properties "alias,config"
```

SSH key commands use the WP Engine API.

```bash
wpengine ssh keys list
wpengine ssh keys list --limit 25 --table
wpengine ssh keys list --filter "comment:contains:laptop"
wpengine ssh keys list --properties "id,fingerprint,comment"
wpengine ssh keys get SSH_KEY_ID
wpengine ssh keys add "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA..."
wpengine ssh keys delete SSH_KEY_ID --yes
```

### SFTP

The SFTP command derives documented host, port, and username patterns only. It does not create, update, test, or retrieve SFTP credentials.

```bash
wpengine sftp connection list
wpengine sftp connection get ENVIRONMENT_NAME
wpengine sftp connection get ENVIRONMENT_NAME --username adam
wpengine sftp connection get ENVIRONMENT_NAME --properties "host,port,user,command"
```

Without `--username`, the output includes the documented username pattern:

```json
{
  "environment_name": "ataprod",
  "host": "ataprod.sftp.wpengine.com",
  "remote_host": "ataprod.sftp.wpengine.com",
  "port": 2222,
  "protocol": "sftp",
  "user": null,
  "username_pattern": "ataprod-<username>",
  "command": "sftp -P 2222 ataprod-<username>@ataprod.sftp.wpengine.com",
  "password_source": "WP Engine User Portal SFTP user"
}
```

## Output

JSON output preserves the full API response fields by default. `--properties` is the only command-level field projection.

```bash
wpengine sites list --limit 2
wpengine environments get ENVIRONMENT_ID --properties "id,name,primary_domain"
wpengine ssh connection get ataprod --properties "host,user,remote_root"
```

Table output uses compact default columns:

```bash
wpengine accounts list --table
wpengine sites list --table
wpengine environments list --table
wpengine ssh keys list --table
```

## Filtering

List commands support the repo-standard `field:op:value` syntax:

```bash
wpengine sites list --filter "name:contains:ata"
wpengine environments list --filter "account_id:eq:ACCOUNT_ID"
wpengine ssh keys list --filter "comment:contains:work"
```

The `account_id:eq:...` filter is sent to the API for `sites list` and `environments list`. Other filters are applied client-side after API pagination.

## Configuration

Root configuration is stored in `~/.local/share/cli-tools/wpengine/.env`. CLI-managed runtime auth state is stored under `~/.local/share/cli-tools/wpengine/authentication_profiles/<profile>/.env`.

Root config variables:

```bash
BASE_URL=https://api.wpengineapi.com/v1
CACHE_ENABLED=true
CACHE_TTL=3600
```

Authentication profile variables:

```bash
ACTIVE=true
USERNAME=secret://wpengine-username
PASSWORD=secret://wpengine-password
```

Reusable raw credentials belong in the CLI-tools secret manager, not checked into repo files.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/config/authentication error |
| 130 | User interrupted |

## Requirements

- Python 3.11+
- Dependencies installed by `uv`: `typer`, `python-dotenv`, `requests`, `cli-tools-shared`
