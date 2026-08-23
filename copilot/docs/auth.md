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

## Service Principal (Non-Interactive) Authentication

Azure CLI delegated auth (`az login`) is subject to Entra conditional-access
sign-in-frequency policies — many tenants cap the refresh token lifetime at
~30 days (`AADSTS70043`), which requires a fresh interactive (MFA) `az login`
on a recurring basis. For unattended/automation profiles, a profile can opt
into **service principal (client-credentials) auth** instead, which has no
interactive user session and is not subject to that policy.

A profile opts in by setting all three of `AZURE_TENANT_ID`,
`AZURE_CLIENT_ID`, and `AZURE_CLIENT_SECRET` (in addition to the always
required `DATAVERSE_URL`). `Config.get_auth_method()` then returns
`service_principal` instead of `azure_cli`, and every Dataverse Web API
command (`connections`, `connection-references`, `agent-flow`, `solution`,
`agent` CRUD) uses an MSAL client-credentials token instead of `az account
get-access-token`. This is a per-profile, all-or-nothing choice — a profile
with only `DATAVERSE_URL` set keeps using `az login` exactly as before.

**Setup:**

1. Register (or reuse) an Azure AD app registration with a client secret.
   This app does **not** need the `Access Dynamics 365 as organization
   users` delegated permission for this path.
2. In the Power Platform admin center, open the target Dataverse
   environment → **Settings** → **Users + permissions** → **Application
   users** → **New app user** → search by the app's Application (client) ID
   → assign a security role. Without this step every call fails `HTTP 403:
   The user is not a member of the organization.` even though MSAL
   successfully issues a token — the Entra app registration and the
   Dataverse application user are two separate trust boundaries.
3. Store the client secret and wire the profile:
   ```bash
   copilot config set-secret AZURE_CLIENT_SECRET --profile <name>
   ```
   Then set `AZURE_TENANT_ID` and `AZURE_CLIENT_ID` in the profile's
   `.env` (non-secret values, plain text).
4. Verify:
   ```bash
   copilot auth status --profile <name>
   ```

**Scope:** this covers only the Dataverse Web API command surface. It does
**not** extend to `copilot agent prompt` (Copilot Studio Direct-to-Engine
conversations) — most environments have app-only S2S access disabled for
that surface and return HTTP 405; `agent prompt` needs delegated (user or
M365 SDK device-code) auth regardless of the profile's service-principal
configuration.

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
