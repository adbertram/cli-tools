# Authentication

The Copilot CLI uses Azure CLI authentication to obtain tokens for the Dataverse API. This document covers login/logout, status checks, prerequisites, and managing CLI profiles for multiple environments or tenants.

## Quick Start

```bash
# Check authentication status
copilot auth status

# Set up authentication (guides you through the process)
copilot auth login

# Log out
copilot auth logout
```

## Auth Commands

| Command | Description |
|---------|-------------|
| `copilot auth login` | Set up authentication (Azure CLI + Dataverse config) |
| `copilot auth status` | Check authentication status (exit 0 if authenticated, 2 if not) |
| `copilot auth logout` | Log out and clear credentials |

### Check Auth Status

```bash
copilot auth status              # JSON output
copilot auth status      # Human-readable table
```

**JSON Output:**
```json
{
  "authenticated": true,
  "azure_cli_installed": true,
  "azure_cli_logged_in": true,
  "azure_cli_user": "user@example.com",
  "azure_cli_tenant": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "dataverse_url": "https://yourorg.crm.dynamics.com",
  "dataverse_accessible": true,
  "environment_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "auth_method": "azure_cli"
}
```

**Exit Codes:**
- `0` - Authenticated and ready to use
- `2` - Not authenticated (Azure CLI not logged in, Dataverse not accessible, or missing config)

### Set Up Authentication

```bash
copilot auth login
```

This command guides you through:
1. Checking Azure CLI is installed
2. Running `az login` if not logged in
3. Verifying DATAVERSE_URL is configured and accessible

### Log Out

```bash
copilot auth logout              # Log out from Azure CLI
copilot auth logout --clear-env  # Also clear DATAVERSE_URL from .env
copilot auth logout --force      # Skip confirmation prompt
```

## Prerequisites

1. Install Azure CLI and authenticate:
```bash
az login
```

2. Set the Dataverse URL environment variable:
```bash
export DATAVERSE_URL=https://yourorg.api.crm.dynamics.com
```

Or add to your shell profile (`~/.zshrc`, `~/.bashrc`):
```bash
export DATAVERSE_URL=https://yourorg.api.crm.dynamics.com
```

## Auth Profile Commands

Manage CLI profiles for multiple environments or tenants. All commands live under `copilot auth profiles`.

### List Profiles

```bash
copilot auth profiles list                   # List all profiles (JSON)
copilot auth profiles list --table           # List all profiles (table)
```

### Get Profile

```bash
copilot auth profiles get default            # Get details for a profile
copilot auth profiles get my-tenant --table  # Get profile as table
```

### Create Profile

```bash
copilot auth profiles create staging         # Create a new profile from template
```

### Select Active Profile

```bash
copilot auth profiles select staging    # Select the active profile
```

### Delete Profile

```bash
copilot auth profiles delete old-profile     # Delete a profile
```

## User Commands

### Who Am I

Get information about the current authenticated user.

```bash
copilot whoami
```

Returns the current user's ID, business unit, and organization information from the Dataverse environment.

### User Licenses

Check Microsoft 365 license assignments for a user through Microsoft Graph.

```bash
copilot user-licenses list user@domain.com
copilot user-licenses list user@domain.com --table
copilot user-licenses get user@domain.com
```

### Cache

Manage the local response cache used by cached CLI operations.

```bash
copilot cache status
copilot cache clear
```
