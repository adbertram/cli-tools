# Implementation Plan: Migrate Google CLI to cli-tools-shared Framework with Profiles Support

## Summary

The Google CLI uses a hand-rolled `Config` and `GoogleClient` with a global singleton pattern and no profile support. The goal is to migrate it to the `cli-tools-shared` `BaseConfig`/`create_auth_app` framework so users can maintain multiple named Google accounts (e.g., personal, work) each with their own OAuth credentials and tokens.

The work splits into two phases. Phase 1 is the foundational refactor: replace the custom `Config` class with a `BaseConfig` subclass, refactor `get_config()`/`get_client()` to accept a `profile` parameter, and plumb `--profile` through every command. Phase 2 completes the framework migration: replace the hand-rolled `auth.py` with `create_auth_app()`, use `auth profiles`, replace `filters.py` with the common library import, update `pyproject.toml`, create `.gitignore`, and update `.env.example`.

## Why This Approach

- Follows the existing Slack CLI pattern exactly — the closest analogue in the codebase.
- `CredentialType.CUSTOM` with empty `CUSTOM_REQUIRED_FIELDS` and a `has_credentials()` override that checks `token.json` existence is the correct fit for Google's file-based OAuth tokens.
- Replacing the `_client` / `_config` global singleton with a profile-keyed dict mirrors Slack's `_configs` dict, enabling concurrent profile use without state bleed.
- The simplicity gate question (can `--profile` be threaded via typer callback instead of per-function option?) was evaluated: typer callback context-passing requires `ctx.obj` plumbing and makes each command non-self-contained. The per-function `Optional[str]` option is 1 line per command and is consistent with what `create_auth_app()` itself generates — so the per-function approach is simpler and more consistent.

## What's NOT Included

- Auto-migration of existing `token.json` or `credentials.json` from the tool root — users must run a fresh login per profile.
- Any changes to API logic, filter translator, or command business logic beyond the `get_client()`/`get_config()` call sites.
- Unit or integration tests (separate task).

## Prerequisites

- `cli-tools-shared` package installable from `<cli-tools-root>/_repo/cli-tools-shared/` (already used by Slack, Cloudflare).
- Python 3.9+ (already required by `pyproject.toml`).
- `pyproject.toml` must be updated to add `cli-tools-shared` dependency before Phase 2 imports will work.

---

## Phase 1: Profile-Aware Config and Client

### Step 1: Add `.gitignore`

**File:** `google/.gitignore`

**Action:** Create new file:

```
.env
.env.*
.venv/
token.json
credentials.json
__pycache__/
*.egg-info/
authentication_profiles/
```

**Verify:** File exists at `google/.gitignore`.

---

### Step 2: Add `cli-tools-shared` to `pyproject.toml`

**File:** `google/pyproject.toml`

**Action:** Add `"cli-tools-shared"` to the `dependencies` list (after `python-dotenv`). The package is installed from the local path via `install.sh` (leave `install.sh` unchanged).

```toml
dependencies = [
    "typer>=0.9.0",
    "python-dotenv>=1.0.0",
    "cli-tools-shared",
    "google-api-python-client>=2.0.0",
    "google-auth-httplib2>=0.1.0",
    "google-auth-oauthlib>=1.0.0",
]
```

**Verify:** `pyproject.toml` contains `"cli-tools-shared"`.

---

### Step 3: Rewrite `google_cli/config.py` — BaseConfig subclass

**File:** `google/google_cli/config.py`

**Action:** Replace entire file. The new `Config` inherits from `BaseConfig`. Key decisions:

- `CREDENTIAL_TYPES = [CredentialType.CUSTOM]`
- `CUSTOM_REQUIRED_FIELDS = []` — empty because token existence (not an env var) determines auth
- `has_credentials()` overridden to check `token.json` in `get_profile_data_dir()`
- `credentials_path` property reads from profile data dir (falls back to `None` if file absent)
- `token_path` property reads from profile data dir
- `searchconsole_site` and `analytics_property_id` kept as env-var properties
- Profile-keyed `_configs` dict replaces the single `_config` global
- `get_missing_credentials()` kept for compatibility with `client.py`

```python
"""Configuration management for Google CLI."""
import os
from pathlib import Path
from typing import Optional
from cli_tools_shared.config import BaseConfig
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Google CLI configuration - extends BaseConfig for profile support."""

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = []
    CUSTOM_ALL_FIELDS = []
    CUSTOM_LOGIN_PROMPTS = []
    CUSTOM_EPHEMERAL_FIELDS = []
    CUSTOM_SENSITIVE_FIELDS = []

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=Path(__file__).resolve().parent.parent,
            profile=profile,
        )

    def has_credentials(self) -> bool:
        """Credentials exist when token.json is present in the profile data dir."""
        return self.token_path_obj.exists()

    def get_missing_credentials(self) -> list[str]:
        """Return list of what's missing for client initialization."""
        missing = []
        if not self.credentials_path:
            missing.append("credentials.json in profile data dir")
        return missing

    @property
    def token_path_obj(self) -> Path:
        """Resolved Path for token.json in the active profile's data dir."""
        return self.get_profile_data_dir() / "token.json"

    @property
    def token_path(self) -> str:
        """String path to token.json (for GoogleClient compatibility)."""
        return str(self.token_path_obj)

    @property
    def credentials_path(self) -> Optional[str]:
        """String path to credentials.json in the active profile's data dir."""
        profile_creds = self.get_profile_data_dir() / "credentials.json"
        if profile_creds.exists():
            return str(profile_creds)
        return None

    @property
    def searchconsole_site(self) -> Optional[str]:
        """Get Search Console site URL from environment."""
        return os.getenv("GOOGLE_SEARCHCONSOLE_SITE")

    @property
    def analytics_property_id(self) -> Optional[str]:
        """Get default GA4 property ID from environment."""
        return os.getenv("GOOGLE_ANALYTICS_PROPERTY_ID")


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]


def reset_config():
    """Reset all config instances (for testing)."""
    global _configs
    _configs = {}
```

**Verify:** `python -c "from google_cli.config import get_config; print(get_config())"` succeeds.

---

### Step 4: Rewrite `google_cli/client.py` — profile-keyed client

**File:** `google/google_cli/client.py`

**Action:** Replace the global `_client` singleton and `get_client()` with a profile-keyed dict. The `GoogleClient.__init__` and `_authenticate()` now accept/use config passed in from `get_client(profile=...)`. `SCOPES` constant is unchanged (lines 14-24 in original).

Key changes:
- `GoogleClient.__init__(self, config)` — takes `Config` instance instead of calling `get_config()` internally
- `_authenticate()` uses `self.config.token_path` and `self.config.credentials_path` (same as before, just profile-resolved)
- `_clients` dict replaces `_client` global
- `get_client(profile=None)` creates a profile-keyed `Config` and `GoogleClient`

```python
_clients: dict = {}

def get_client(profile: Optional[str] = None) -> GoogleClient:
    """Get or create the client instance for the given profile."""
    key = profile or "_default"
    if key not in _clients:
        config = get_config(profile=profile)
        _clients[key] = GoogleClient(config)
    return _clients[key]


def reset_client():
    """Reset all client instances (for testing)."""
    global _clients
    _clients = {}
```

The `GoogleClient.__init__` signature changes from `def __init__(self)` to `def __init__(self, config: Config)`, with the body's first line changing from `self.config = get_config()` to `self.config = config`.

**Verify:** Import succeeds without error.

---

### CHECKPOINT: Verify Phase 1 core modules
**Run:** `cd <cli-tools-root>/google && python -c "from google_cli.config import get_config; from google_cli.client import get_client; print('ok')"`
**Expected:** `ok` printed, no import error.

---

### Step 5: Add `--profile` to all command files

**Files:** All 9 command files in `google/google_cli/commands/`:
- `analytics.py` — 5 `get_client()` + 1 `get_config()` (via `_get_property_id`)
- `auth.py` — will be replaced entirely in Phase 2; skip in Phase 1
- `calendar.py` — 4 `get_client()`
- `cloud.py` — 5+ `get_client()`
- `docs.py` — 6+ `get_client()`
- `drive.py` — 4 `get_client()`
- `gmail.py` — 14 `get_client()`
- `searchconsole.py` — 3 `get_client()` + 1 `get_config()` (via site resolution)
- `sheets.py` — 6 `get_client()`

**Pattern for every command function** (add `profile` parameter and pass to `get_client`/`get_config`):

```python
from typing import Optional
import typer

@app.command("list")
def drive_list(
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
    # ... existing params unchanged ...
):
    client = get_client(profile=profile)
    # ... rest of function unchanged ...
```

**Special cases:**

- `analytics.py` has a helper `_get_property_id(property_opt)` that calls `get_config()`. Change its signature to `_get_property_id(property_opt, profile=None)` and pass `profile` through from each analytics command. Inside the helper: `config = get_config(profile=profile)`.

- `searchconsole.py` calls `get_config()` in three functions (`searchconsole_index`, `searchconsole_urls_list`, `searchconsole_urls_get`) to resolve `config.searchconsole_site`. Change each to `get_config(profile=profile)`.

- `auth.py`: Leave the existing `auth_login`, `auth_status`, `auth_logout` commands unchanged in Phase 1. They will be replaced entirely in Phase 2. This avoids breaking auth while the framework migration is in progress.

**Scope:** Every `@app.command` and `@<sub>_app.command` decorated function across the 8 non-auth command files gets `profile: Optional[str] = typer.Option(None, "--profile", help="Profile name")` added as the LAST optional parameter, and each `get_client()` call becomes `get_client(profile=profile)`.

**Sub-app commands** in `cloud.py` (e.g., `@projects_app.command`, `@credentials_app.command`) and `searchconsole.py` (`@sites_app.command`, `@urls_app.command`) and `docs.py` (`@tables_app.command`) must all receive `--profile` too.

### PARALLEL GROUP: Add --profile to 8 command files
**Steps 5a-5h can run concurrently — they modify independent files.**
**Execution:** Spawn 8 subagents in parallel.

#### Step 5a: drive.py
**File:** `google/google_cli/commands/drive.py`
**Action:** Add `profile: Optional[str] = typer.Option(None, "--profile", help="Profile name")` to `drive_list`, `drive_get`, `drive_search`, `drive_download`. Change each `get_client()` call to `get_client(profile=profile)`.
**Subagent prompt:** "In `<cli-tools-root>/google/google_cli/commands/drive.py`, add `profile: Optional[str] = typer.Option(None, '--profile', help='Profile name')` as the last optional parameter to ALL four @app.command functions (drive_list, drive_get, drive_search, drive_download). Change every `get_client()` call to `get_client(profile=profile)`. The `Optional` import already exists in `typing`. Do not change anything else."

#### Step 5b: calendar.py
**File:** `google/google_cli/commands/calendar.py`
**Action:** Add `--profile` to `calendar_list`, `calendar_get`, `calendar_search`, `calendar_today`. Change all `get_client()` to `get_client(profile=profile)`.
**Subagent prompt:** "In `<cli-tools-root>/google/google_cli/commands/calendar.py`, add `profile: Optional[str] = typer.Option(None, '--profile', help='Profile name')` as the last optional parameter to ALL four @app.command functions. Change every `get_client()` call to `get_client(profile=profile)`. Do not change anything else."

#### Step 5c: sheets.py
**File:** `google/google_cli/commands/sheets.py`
**Action:** Add `--profile` to `sheets_list`, `sheets_get`, `sheets_read`, `sheets_create`, `sheets_append`, `sheets_update`. Change all `get_client()` calls.
**Subagent prompt:** "In `<cli-tools-root>/google/google_cli/commands/sheets.py`, add `profile: Optional[str] = typer.Option(None, '--profile', help='Profile name')` as the last optional parameter to ALL six @app.command functions (sheets_list, sheets_get, sheets_read, sheets_create, sheets_append, sheets_update). Change every `get_client()` call to `get_client(profile=profile)`. Do not change anything else."

#### Step 5d: docs.py
**File:** `google/google_cli/commands/docs.py`
**Action:** Add `--profile` to `docs_list`, `docs_get`, `docs_read`, `docs_create`, `docs_export`, `docs_update`, and `tables_update` (the `@tables_app.command`). Change all `get_client()` calls.
**Subagent prompt:** "In `<cli-tools-root>/google/google_cli/commands/docs.py`, add `profile: Optional[str] = typer.Option(None, '--profile', help='Profile name')` as the last optional parameter to ALL @app.command and @tables_app.command decorated functions (docs_list, docs_get, docs_read, docs_create, docs_export, docs_update, tables_update). Change every `get_client()` call to `get_client(profile=profile)`. Do not change anything else."

#### Step 5e: gmail.py
**File:** `google/google_cli/commands/gmail.py`
**Action:** Add `--profile` to all 14 command functions. Change all `get_client()` calls.
**Subagent prompt:** "In `<cli-tools-root>/google/google_cli/commands/gmail.py`, add `profile: Optional[str] = typer.Option(None, '--profile', help='Profile name')` as the last optional parameter to EVERY @app.command decorated function. Change every `get_client()` call to `get_client(profile=profile)`. Do not change anything else."

#### Step 5f: cloud.py
**File:** `google/google_cli/commands/cloud.py`
**Action:** Add `--profile` to all functions decorated with `@projects_app.command` and `@credentials_app.command`: `projects_list`, `projects_get`, `projects_create`, `projects_update`, `projects_delete`, `credentials_list`, `credentials_create`, `credentials_update`. Change all `get_client()` calls, including those inside helper functions `_list_service_accounts`, `_list_api_keys`, `_list_oauth_clients` — note these helpers receive `client` as a parameter already, so only the callers (`credentials_list`, `credentials_create`, `credentials_update`) need the client call changed.
**Subagent prompt:** "In `<cli-tools-root>/google/google_cli/commands/cloud.py`, add `profile: Optional[str] = typer.Option(None, '--profile', help='Profile name')` as the last optional parameter to ALL decorated command functions: projects_list, projects_get, projects_create, projects_update, projects_delete, credentials_list, credentials_create, credentials_update. Change every `get_client()` call within those functions to `get_client(profile=profile)`. The helper functions _list_service_accounts, _list_api_keys, _list_oauth_clients already receive `client` as an argument — do not modify them. Do not change anything else."

#### Step 5g: searchconsole.py
**File:** `google/google_cli/commands/searchconsole.py`
**Action:** Add `--profile` to `searchconsole_index`, `searchconsole_sites_list`, `searchconsole_sites_get`, `searchconsole_urls_list`, `searchconsole_urls_get`. Change all `get_client()` calls. Change all `get_config()` calls to `get_config(profile=profile)`.
**Subagent prompt:** "In `<cli-tools-root>/google/google_cli/commands/searchconsole.py`, add `profile: Optional[str] = typer.Option(None, '--profile', help='Profile name')` as the last optional parameter to ALL @app.command and @sites_app.command and @urls_app.command decorated functions (searchconsole_index, searchconsole_sites_list, searchconsole_sites_get, searchconsole_urls_list, searchconsole_urls_get). Change every `get_client()` call to `get_client(profile=profile)` and every `get_config()` call to `get_config(profile=profile)`. Do not change anything else."

#### Step 5h: analytics.py
**File:** `google/google_cli/commands/analytics.py`
**Action:** Change `_get_property_id(property_opt)` to `_get_property_id(property_opt, profile=None)` with `get_config(profile=profile)` inside. Add `--profile` to `analytics_accounts`, `analytics_report`, `analytics_top_pages`, `analytics_traffic`, `analytics_realtime`. Change all `get_client()` calls. Pass `profile=profile` to `_get_property_id` from each command.
**Subagent prompt:** "In `<cli-tools-root>/google/google_cli/commands/analytics.py`: (1) Change `_get_property_id(property_opt)` to `_get_property_id(property_opt, profile=None)` and change the `get_config()` call inside it to `get_config(profile=profile)`. (2) Add `profile: Optional[str] = typer.Option(None, '--profile', help='Profile name')` as the last optional parameter to all five @app.command functions. (3) Change every `get_client()` call to `get_client(profile=profile)`. (4) Change every `_get_property_id(property)` call (in analytics_report, analytics_top_pages, analytics_traffic, analytics_realtime) to `_get_property_id(property, profile=profile)`. Do not change anything else."

### CHECKPOINT: Verify Phase 1 complete
**Run:** `cd <cli-tools-root>/google && python -c "from google_cli import main; print('import ok')"`
**Expected:** `import ok` — confirms all 9 command modules import without error after the profile changes.

---

## Phase 2: Full Framework Migration

### Step 6: Replace `auth.py` with `create_auth_app()`

**File:** `google/google_cli/commands/auth.py`

**Action:** Replace entire file. The Google `login_handler` must:
1. Check that `credentials.json` exists in `config.get_profile_data_dir()`
2. If not, print a helpful error and exit
3. If `--force`, delete `token.json` from the profile data dir
4. Run `InstalledAppFlow.from_client_secrets_file(config.credentials_path, SCOPES)` then `flow.run_local_server(port=0)`
5. Write the resulting token to `config.token_path`

The `test_handler` verifies the token by calling the Drive `about().get()` API and returns `{"api_test": "passed", "email": ...}`.

```python
"""Authentication commands for Google CLI."""
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config
from ..client import SCOPES, reset_client
from ..output import print_error


def _google_login_handler(config, force: bool):
    """Handle Google OAuth2 flow using credentials.json from profile data dir."""
    import os
    from pathlib import Path
    from google_auth_oauthlib.flow import InstalledAppFlow

    # Check credentials.json exists
    if not config.credentials_path:
        print_error(
            f"credentials.json not found in profile data dir: {config.get_profile_data_dir()}\n"
            "Place your OAuth credentials.json file there before logging in."
        )
        import typer
        raise typer.Exit(2)

    # Force: clear existing token
    token_path = config.token_path_obj
    if force and token_path.exists():
        token_path.unlink()
        reset_client()

    # Run OAuth flow
    flow = InstalledAppFlow.from_client_secrets_file(config.credentials_path, SCOPES)
    creds = flow.run_local_server(port=0)

    # Save token to profile data dir
    with open(config.token_path, "w") as f:
        f.write(creds.to_json())


def _google_test_handler(config) -> dict:
    """Test Google authentication by calling Drive API."""
    from ..client import get_client
    from googleapiclient.errors import HttpError
    try:
        client = get_client(profile=config.get_active_profile_name())
        service = client.get_drive_service()
        about = service.about().get(fields="user").execute()
        email = about.get("user", {}).get("emailAddress", "unknown")
        return {"api_test": "passed", "email": email}
    except HttpError as e:
        return {"api_test": f"failed: {e}"}


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="google",
    login_handler=_google_login_handler,
    test_handler=_google_test_handler,
)
```

**Note on `reset_client()`:** The `--force` path in the login handler needs to evict the cached `GoogleClient` for the profile so the next `get_client()` call re-authenticates with the new token. Add `reset_client()` to `client.py` (Step 4 already specifies this function).

**Verify:** `google auth --help` shows `login`, `logout`, `status`, `refresh`, `test` commands.

---

### Step 7: Use `auth profiles`

**File:** `google/google_cli/main.py`

**Action:** Use the `profiles` group mounted by `create_auth_app()`. Do not register a top-level `profiles` app.

```python
app.add_typer(auth.app, name="auth", help="Manage authentication")
```

**Verify:** `google auth profiles --help` shows `list`, `get`, `create`, `set-default`, `delete`.

---

### Step 8: Replace `google_cli/filters.py` with common import

**File:** `google/google_cli/filters.py`

**Action:** Replace the entire file with a single re-export line that mirrors `output.py`'s pattern. All existing callers in `filter_translator.py` import `OPERATORS` from `..filters` — this keeps the import path unchanged.

```python
"""Filter module — re-exports from cli_tools_shared.filters."""
from cli_tools_shared.filters import OPERATORS, apply_filters, validate_filters  # noqa: F401
```

**Note:** `cli_tools_shared.filters` has `OPERATORS` as a set with the same members as the local version plus `contains`, `startswith`, `endswith`. The `filter_translator.py` only uses `OPERATORS` as a set for membership testing, so the extra operators are harmless. The local `parse_filter_string`, `validate_filters`, `apply_filters`, `_matches_condition` etc. are used only in `filters.py` itself and not imported by any other module — they can be dropped.

**Verify:** `python -c "from google_cli.filters import OPERATORS; print(len(OPERATORS))"` succeeds.

---

### Step 9: Update `.env.example`

**File:** `google/.env.example`

**Action:** Replace current content to reflect profile-based setup:

```bash
# Google CLI Profile Configuration
# Copy to .env.<profile-name> (e.g., .env.personal, .env.work)

# Mark this as the default profile (only one profile should have this set to 1)
IS_DEFAULT_PROFILE=0

# Google Analytics: Default GA4 property ID (numeric, e.g., 123456789)
# GOOGLE_ANALYTICS_PROPERTY_ID=

# Google Search Console: Default site URL
# GOOGLE_SEARCHCONSOLE_SITE=

# credentials.json and token.json are stored in the profile data directory:
# Linux/macOS: ~/.local/share/cli-tools/google/authentication_profiles/<profile-name>/
# Windows: %APPDATA%/cli-tools/google/authentication_profiles/<profile-name>/
#
# Place your OAuth credentials.json in that directory before running: google auth login
```

**Verify:** File contains `IS_DEFAULT_PROFILE`.

---

### Step 10: Verify `main.py` entry point

**File:** `google/google_cli/main.py`

**Action:** Confirm `pyproject.toml` entry point `google = "google_cli.main:app"` still works. The existing `main()` function wraps `app()`. No changes needed to `main()` itself. The `ClientError` catch in `main()` still applies because the login handler and data commands can still raise it.

**Verify:** `google --help` lists all top-level sub-apps and does not list `profiles`. `google auth --help` lists `profiles`.

---

### CHECKPOINT: Verify Phase 2 complete
**Run:** `cd <cli-tools-root>/google && google --help`
**Expected:** Top-level commands exclude `profiles`. Then run: `google auth --help` — expect `login`, `logout`, `status`, `refresh`, `test`, and `profiles`.

---

## Testing Strategy

**Manual smoke test (no credentials needed):**
```bash
google --help                        # All 10 sub-commands present
google auth --help                   # login/logout/status/refresh/test
google auth profiles --help               # list/get/create/set-default/delete
google drive list --help             # --profile option present
google analytics report --help       # --profile option present
google searchconsole index --help    # --profile option present
```

**Auth flow test (requires credentials.json):**
1. `google auth profiles create personal` — creates `.env.personal`
2. Place `credentials.json` in the profile data dir (`~/.local/share/cli-tools/google/authentication_profiles/personal/`)
3. `google auth login --profile personal` — runs OAuth flow, writes `token.json`
4. `google auth status --profile personal` — should show `authenticated: true`
5. `google drive list --profile personal` — should return files

---

## Traceability Matrix

| Requirement | Steps | Verification |
|---|---|---|
| Per-profile authentication_profiles/ isolation | 3, 4 | token_path uses get_profile_data_dir() |
| credentials.json per-profile | 3, 6 | credentials_path reads from profile data dir |
| --profile on ALL commands | 5a-5h | Every command has --profile option |
| CredentialType.CUSTOM + has_credentials() override | 3 | has_credentials() checks token.json |
| create_auth_app() with login_handler | 6 | auth.py uses create_auth_app() |
| Drop --oauth-client-id/--oauth-client-secret | 6 | auth.py replacement has no such flags |
| create_auth_app() profiles | 7 | profiles group mounted under auth |
| Replace filters.py with common import | 8 | filters.py is 3 lines |
| IS_DEFAULT_PROFILE in .env.example | 9 | .env.example updated |
| cli-tools-shared in pyproject.toml | 2 | dependency added |
| .gitignore covering credentials | 1 | .gitignore created |
| No auto-migration of token.json | N/A | login handler only writes to profile dir |

## Risk Mitigation

| Risk | Mitigation | Rollback |
|---|---|---|
| `get_profile_data_dir()` creates directory on import | `BaseConfig.__init__` only calls it when needed; `token_path` is a property, not called at init | Wrap in lazy property |
| Existing `credentials.json`/`token.json` at tool root stop working | Expected — users must re-auth per profile. Document in `.env.example`. | Old files remain on disk; user can manually copy into profile data dir |
| `cli-tools-shared` not installed when command files import it | `install.sh` handles this; `pyproject.toml` declares it as a dependency | Run `install.sh` |
| Phase 1 leaves old `auth.py` in place with `credentials_file_path` attribute that no longer exists on new Config | `auth.py` auth_login accesses `config.credentials_file_path` (line 42). Since `auth.py` is not changed in Phase 1, this path will break if someone calls `google auth login --oauth-client-id ...`. To prevent this: skip changing auth.py in Phase 1 is fine because the `--oauth-client-id` flags are being dropped entirely in Phase 2 and users should not be using them after the migration. | Complete Phase 2 immediately after Phase 1. |
| `reset_client()` not thread-safe | Acceptable — CLI tools are single-process | N/A |
