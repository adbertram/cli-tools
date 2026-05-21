# Technical Research: Migrate Google CLI to cli-tools-shared

## Files Analyzed

| File | Key Functions | Notes |
|------|---|---|
| `google_cli/config.py` | `Config.__init__()`, `get_config()`, credentials_path, token_path | Global singleton, manages .env + paths |
| `google_cli/client.py` | `GoogleClient.__init__()`, `_authenticate()`, `get_client()` | Global singleton, SCOPES at line 14-23 |
| `google_cli/main.py` | `callback()`, `main()`, app registration | 9 sub-apps, no --profile callback |
| `google_cli/filters.py` | `OPERATORS`, `validate_filters()`, `apply_filters()` | Local duplicate of cli_tools_shared.filters |
| `google_cli/filter_translator.py` | `parse_filter_with_aliases()`, service translators | Imports OPERATORS from local filters.py line 6 |
| `google_cli/output.py` | Re-exports from cli_tools_shared | Already correct |
| `google_cli/commands/auth.py` | `auth_login()`, `auth_status()`, `auth_logout()` | Hand-rolled; no --profile; OAuth flags at lines 15-16 |
| `google_cli/commands/drive.py` | list, get, search, download | get_client() at lines 20, 62, 91, 134 |
| `google_cli/commands/gmail.py` | Multiple email commands | get_client() at line 16+ |
| `google_cli/commands/sheets.py` | list, get, read, create, append, update | get_client() at lines 22, 92, 123, 170, 199, 253 |
| `google_cli/commands/calendar.py` | list, get, search, today | get_client() at lines 22, 98, 134, 196 |
| `google_cli/commands/docs.py` | list, get, read, create, update, export | get_client() at line 36+ |
| `google_cli/commands/analytics.py` | accounts, report, top-pages, traffic, realtime | get_config() at line 17 for property_id |
| `google_cli/commands/searchconsole.py` | index, sites | get_config() at line 9 for site |
| `google_cli/commands/cloud.py` | projects, credentials | get_client() at line 26+ |
| `pyproject.toml` | Dependencies, entry point | Missing cli-tools-shared |

### cli-tools-shared References

| File | Key Functions | Notes |
|------|---|---|
| `cli_tools_shared/config.py` | `BaseConfig`, profile resolution, get/set/clear | Lines 66-407 |
| `cli_tools_shared/auth_commands.py` | `create_auth_app()` | Line 103-108: signature takes get_config_fn, login_handler, test_handler |
| `cli_tools_shared/profiles_commands.py` | `create_profiles_app()` | Line 47: takes get_config_fn |
| `cli_tools_shared/credentials.py` | `CredentialType.CUSTOM` | Line 15: empty defaults, uses CUSTOM_* class vars |
| `cli_tools_shared/filters.py` | `OPERATORS`, `apply_filters()` | Has `contains`, `startswith`, `endswith` + `get_nested_value()` |

### Reference CLIs

| CLI | Config Pattern | Auth Pattern | Notes |
|-----|---|---|---|
| `slack` | `Config(BaseConfig)`, CUSTOM type, profile-keyed `_configs` | `create_auth_app(get_config, login_handler=slack_login_handler)` | Best reference for Google |
| `cloudflare` | `Config(BaseConfig)`, API_KEY type | `create_auth_app(get_config, test_handler=_test_handler)` | Simpler auth model |

## get_client() and get_config() Call Sites

| File | get_client() | get_config() | Notes |
|------|---|---|---|
| auth.py | 1 | 4 | Direct config access for login/status/logout |
| drive.py | 4 | 0 | |
| gmail.py | 8+ | 0 | Most call sites |
| sheets.py | 6 | 0 | |
| calendar.py | 4 | 0 | |
| docs.py | 6+ | 0 | |
| analytics.py | 5 | 1 | get_config() for analytics_property_id |
| searchconsole.py | 3+ | 1 | get_config() for searchconsole_site |
| cloud.py | 5+ | 0 | |

**Total**: ~40+ get_client() calls, ~6 get_config() calls across 9 command files.

## --profile Threading Pattern

### Phase 1: Profile-Aware Client

**Step 1: Config** — Add profile parameter, profile-keyed caching:
```python
_configs = {}
def get_config(profile: Optional[str] = None) -> Config:
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
```

**Step 2: Client** — Accept profile, profile-keyed caching:
```python
_clients = {}
def get_client(profile: Optional[str] = None) -> GoogleClient:
    key = profile or "_default"
    if key not in _clients:
        _clients[key] = GoogleClient(profile=profile)
    return _clients[key]
```

**Step 3: Commands** — Add --profile option to every command function:
```python
@app.command("list")
def drive_list(
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
    ...
):
    client = get_client(profile=profile)
```

### Per-Profile File Layout
```
authentication_profiles/
├── adam-personal/
│   ├── credentials.json    # OAuth app definition
│   ├── token.json          # Access/refresh tokens
│   └── (env vars in .env.adam-personal at tool root)
└── adam-work/
    ├── credentials.json
    ├── token.json
    └── (env vars in .env.adam-work at tool root)
```

## Filter Migration Map

| Current | New | Notes |
|---------|-----|-------|
| `from ..filters import OPERATORS` (filter_translator.py:6) | `from cli_tools_shared.filters import OPERATORS` | Same set + 3 extra (contains, startswith, endswith) |
| `google_cli/filters.py` (entire file) | DELETE | Replaced by cli_tools_shared.filters |
| filter_translator.py uses OPERATORS set | No change needed | Just change import source |

## Critical Implementation Details

### has_credentials() Override
```python
def has_credentials(self) -> bool:
    token_path = self.get_profile_data_dir() / "token.json"
    return token_path.exists()
```

### credentials_path and token_path Properties
Must change from tool-root to profile data dir:
```python
@property
def credentials_path(self) -> Optional[str]:
    profile_creds = self.get_profile_data_dir() / "credentials.json"
    if profile_creds.exists():
        return str(profile_creds)
    return None

@property
def token_path(self) -> str:
    return str(self.get_profile_data_dir() / "token.json")
```

### SCOPES Constant
Lines 14-24 in client.py. Must remain unchanged. All Google service permissions.

### create_auth_app() Key Signatures
- `get_config_fn`: `Callable(profile=None) -> Config`
- `login_handler`: `Callable(config, force: bool) -> None`
- `test_handler`: `Callable(config) -> dict` (returns {"api_test": "passed"})

### Slack login_handler Reference Pattern
```python
def slack_login_handler(config, force: bool):
    # 1. Get browser instance
    # 2. Perform login flow
    # 3. Save tokens via config.save_credentials()
```

For Google, login_handler would:
1. Check credentials.json exists in profile data dir
2. Run InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
3. flow.run_local_server(port=0)
4. Write token to profile data dir
