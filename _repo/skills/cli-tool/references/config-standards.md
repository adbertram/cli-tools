# Configuration Standards

**MANDATORY**: Every CLI tool **must** use `cli_tools_shared.config.BaseConfig` for user-data path resolution. Non-authentication configuration belongs in the root tool user-data `.env`; authentication-related runtime state belongs in the active authentication profile. No credentials or tokens should ever be hardcoded or stored in the CLI source repo.

| Rule | Description |
|------|-------------|
| **Root config `.env` file** | Non-authentication settings are stored in `~/.local/share/cli-tools/<tool>/.env` |
| **Per-authentication-profile `.env` file required** | CLI-managed auth runtime state and auth-specific config are stored in `authentication_profiles/<profile>/.env` |
| **`.env.example` file** | Template documenting all required variables (committed to git) |
| **`Config` inherits `BaseConfig`** | Use `cli_tools_shared.config.BaseConfig` for canonical user-data path resolution |
| **Singleton pattern** | Use `get_config()` to access configuration |
| **Token persistence** | OAuth tokens must be saved back to `.env` after refresh |
| **Secret manager for reusable CLI secrets** | Follow `references/secrets.md` |

## User Profile and .env Location

The user profile folder for a tool is:

```
~/.local/share/cli-tools/<tool>
```

All user-specific runtime configuration and state for that tool belongs under this folder, **NOT** in the cli-tools source repo.

Non-authentication configuration lives at the tool root:

```
~/.local/share/cli-tools/<tool>/.env
```

Authentication profiles live under the `authentication_profiles` directory:

```
~/.local/share/cli-tools/<tool>/
└── authentication_profiles/
    └── <profile-name>/
        ├── .env              ← auth data (active profile's ACTIVE=true)
        ├── browser-data/     ← persistent Chromium profile for browser auth
        ├── profile.json      ← auth marker
        └── cache/            ← cached responses
```

Each authentication profile is fully self-contained for auth-related state. The cli-tools source repo holds only `.env.example` (the template, no creds).

**Agent rule:** Reusable raw credentials do not belong in any `.env` file. Agents must store and retrieve them through the CLI-tools secret manager. The only `.env` writes an agent may rely on are non-secret config and CLI-managed runtime auth state written by the tool itself.

This layout is owned by `BaseConfig.__init__` in `cli-tools-shared`. Runtime code does not migrate legacy profile or source-tree `.env` data. A cutover must place state directly in the canonical user profile tree before the tool runs: non-authentication settings in the root tool `.env`, authentication state in `authentication_profiles/<profile>/`, and reusable raw secrets in the CLI-tools secret manager. Legacy locations such as `<repo>/.env`, `<repo>/.env.<name>`, `<repo>/authentication_profiles/`, and `~/.local/share/cli-tools/<tool>/.profiles/` are not read or moved by the package.

## Cross-Host Auth Profile Sync

When copying authentication profiles to `adam-server`, sync the files first and apply permissions in a separate remote step. Do not use `rsync --chmod=F600,D700`: openrsync accepts literal modes or `D`/`F`-prefixed relative modes, but not `D`/`F`-prefixed octal modes.

Use this shape for a single profile:

```bash
local_profile="$HOME/.local/share/cli-tools/<tool>/authentication_profiles/<profile>"
remote_profile="/Users/adam/.local/share/cli-tools/<tool>/authentication_profiles/<profile>"

ssh adam-server 'bash -s' -- "$remote_profile" <<'REMOTE'
set -euo pipefail
mkdir -p "$1"
REMOTE

rsync -a --human-readable --stats "$local_profile"/ "adam-server:$remote_profile"/

ssh adam-server 'bash -s' -- "$remote_profile" <<'REMOTE'
set -euo pipefail
profile=$1
find "$profile" -type d -exec chmod 700 {} +
find "$profile" -type f -exec chmod 600 {} +
REMOTE
```

## CLI-Tools Secret Manager Boundary

Reusable CLI-tool credentials are governed by `references/secrets.md`. That boundary does not replace `BaseConfig`: `auth login`, token refresh, and browser session state still write the active authentication profile's `.env` and related profile files. Agents must not instruct users to put reusable credentials into those files manually.

## Config Class Pattern

Every Config inherits `BaseConfig`. The minimal pattern:

```python
from typing import Optional
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType

class Config(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.API_KEY]  # or CUSTOM, OAUTH, BROWSER_SESSION
    DIST_NAME = "mytool-cli"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )
```

`BaseConfig.__init__` sets `self.config_env_file_path` to the tool-level config `.env`, sets `self.env_file_path` to the resolved authentication profile `.env`, and loads both via dotenv. Tools should never compute paths from `Path(__file__).resolve().parent.parent` — that pattern resolves to the source repo, which is wrong under the user profile layout.

For tools that manage their own custom field set (instead of declaring `CREDENTIAL_TYPES`), set `CREDENTIAL_TYPES: list = []` and override `has_credentials` / `save_*` / `clear_credentials`. The path resolution still inherits from `BaseConfig`.

## Direct Python Probes

For ad-hoc Python imports outside the CLI entrypoint, use the installed CLI
interpreter and pass an explicit profile when auth state matters:

```bash
launcher="$(command -v mytool)"
interpreter="$(head -1 "$launcher" | sed 's/^#!//')"
"$interpreter" -c "from mytool_cli.config import get_config; print(get_config(profile='default').env_file_path)"
```

Profile resolution priority is:
1. Explicit `profile=...` / `Config(profile=...)`
2. Runtime command-profile override set by the CLI entrypoint
3. Active profile for the requested auth type
4. Single active profile for CLIs with one implicit auth type

`BaseConfig` does not read ad-hoc shell variables such as `JIRA_PROFILE` or
`CLI_TOOLS_PROFILE` to pick a profile for direct Python probes. If multiple
profiles are active and the probe does not pass `profile=...`, `ConfigError`
is the expected behavior.

When probing optional profile names, discover first and instantiate second.
Do not loop over candidate names with `Config(profile=name)` or
`get_config(profile=name)` unless absence is already ruled out; missing
profiles intentionally raise `ConfigError`. Use the CLI's data command:

```bash
mytool auth profiles list --properties name,active,auth_type
```

or the shared profile API from the installed launcher interpreter:

```python
from cli_tools_shared.profiles import ProfileStore, list_profiles
profiles = list_profiles(ProfileStore("mytool"))
profile_names = {profile["name"] for profile in profiles}
```

Treat a missing optional profile as evidence (`profile_absent`) and continue
the diagnostic instead of surfacing an unhandled `ConfigError`.

## What Goes in the Root `.env`
- API base URLs
- Cache enable/TTL settings
- Browser display settings such as `HEADLESS`
- Non-auth service behavior settings

## What Goes in the Authentication Profile `.env`
- OAuth access tokens and refresh tokens written by the CLI
- Token expiration timestamps
- Account/workspace IDs
- Authentication selectors, auth-method switches, and other auth-specific settings

Reusable raw credentials such as API keys, usernames, passwords, client secrets, and long-lived bearer tokens belong in the CLI-tools secret manager instead of `.env`.

## Environment Variable Naming
```bash
<NAME>_API_KEY=...
<NAME>_BASE_URL=...
<NAME>_ACCESS_TOKEN=...
<NAME>_REFRESH_TOKEN=...
<NAME>_TOKEN_EXPIRES_AT=...
<NAME>_ACCOUNT_ID=...
```

## Token Refresh Pattern (CRITICAL)

When OAuth tokens are refreshed, the new tokens must be saved back to `.env` using `python-dotenv`'s `set_key()`.

**CRITICAL:** `set_key()` only writes to the file - it does NOT update `os.environ`. You must manually update `os.environ` after calling `set_key()`, otherwise subsequent reads via `os.getenv()` will return stale values.

```python
import os
from dotenv import set_key

def save_tokens(self, access_token: str, refresh_token: str, expires_at: str):
    """Save OAuth tokens to .env file and update environment."""
    set_key(str(self.env_file_path), "MYTOOL_ACCESS_TOKEN", access_token)
    set_key(str(self.env_file_path), "MYTOOL_REFRESH_TOKEN", refresh_token)
    set_key(str(self.env_file_path), "MYTOOL_TOKEN_EXPIRES_AT", expires_at)
    # CRITICAL: Also update os.environ so subsequent reads get the new values
    os.environ["MYTOOL_ACCESS_TOKEN"] = access_token
    os.environ["MYTOOL_REFRESH_TOKEN"] = refresh_token
    os.environ["MYTOOL_TOKEN_EXPIRES_AT"] = expires_at

def clear_credentials(self):
    """Clear credentials from .env file and environment."""
    set_key(str(self.env_file_path), "MYTOOL_ACCESS_TOKEN", "")
    set_key(str(self.env_file_path), "MYTOOL_REFRESH_TOKEN", "")
    set_key(str(self.env_file_path), "MYTOOL_TOKEN_EXPIRES_AT", "")
    # CRITICAL: Also clear from os.environ
    os.environ.pop("MYTOOL_ACCESS_TOKEN", None)
    os.environ.pop("MYTOOL_REFRESH_TOKEN", None)
    os.environ.pop("MYTOOL_TOKEN_EXPIRES_AT", None)
```
