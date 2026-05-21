# Configuration Standards

**MANDATORY**: Every CLI tool **must** use `cli_tools_shared.config.BaseConfig` and the per-profile `.env` layout for runtime configuration. No credentials or tokens should ever be hardcoded or stored in the CLI source repo.

| Rule | Description |
|------|-------------|
| **Per-profile `.env` file required** | Runtime credentials, OAuth tokens, API keys, and config are stored in the user-data profile `.env` managed by `BaseConfig` |
| **`.env.example` file** | Template documenting all required variables (committed to git) |
| **`Config` inherits `BaseConfig`** | Use `cli_tools_shared.config.BaseConfig` for path resolution + migration |
| **Singleton pattern** | Use `get_config()` to access configuration |
| **Token persistence** | OAuth tokens must be saved back to `.env` after refresh |
| **Secret manager for reusable CLI secrets** | Follow `references/secrets.md` |

## .env File Location

`.env` files live in the per-account user-data directory, **NOT** in the cli-tools source repo:

```
~/.local/share/cli-tools/<tool>/.profiles/
└── <profile-name>/
    ├── .env              ← credentials (active profile's IS_DEFAULT_PROFILE=1)
    ├── auth-state.json   ← Playwright cookies / localStorage (browser auth)
    ├── profile.json      ← session marker
    └── cache/            ← cached responses
```

Each profile is fully self-contained in its own directory. The cli-tools source repo holds only `.env.example` (the template, no creds).

This layout is enforced by `BaseConfig.__init__` in `cli-tools-shared`. On first instantiation per tool, it migrates any pre-existing `<repo>/.env` and `<repo>/.env.<name>` files into the per-profile dirs (idempotent). After migration the source repo contains no per-account state.

## CLI-Tools Secret Manager Boundary

Reusable CLI-tool credentials are governed by `references/secrets.md`. That boundary does not replace `BaseConfig`: `auth login`, token refresh, and browser session state still write the active profile's `.env` and related profile files.

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

`BaseConfig.__init__` sets `self.env_file_path` to the resolved profile's `.env` and loads it via dotenv. Tools should never compute paths from `Path(__file__).resolve().parent.parent` — that pattern resolves to the source repo, which is wrong under the new layout.

For tools that manage their own custom field set (instead of declaring `CREDENTIAL_TYPES`), set `CREDENTIAL_TYPES: list = []` and override `has_credentials` / `save_*` / `clear_credentials`. The path resolution and migration still inherit from `BaseConfig`.

## What Goes in the Profile `.env`
- API keys and secrets
- OAuth client IDs and secrets
- OAuth access tokens and refresh tokens
- Token expiration timestamps
- Account/workspace IDs
- Any other service-specific configuration

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
