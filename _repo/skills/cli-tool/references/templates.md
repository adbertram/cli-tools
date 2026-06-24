# CLI Tool Templates

Three template types are available. Each creates a complete CLI structure with different core implementations.

## Template Locations

```
<cli-tools-root>/_repo/skills/cli-tool/templates/
├── api/                 # REST API clients
├── browser/             # Browser automation
├── wrapper/             # CLI wrappers
└── README_TEMPLATE.md   # README template for new CLIs
```

---

## API Template (`--type api`)

**Purpose:** REST/JSON API clients

**Best for:**
- Services with documented REST APIs
- JSON-based APIs
- OAuth, API key, or personal access token authentication

### Structure
```
<name>/
├── <name>_cli/
│   ├── __init__.py
│   ├── main.py           # Typer app setup and default items command group
│   ├── client.py         # HTTP requests, auth, retry, normalization
│   ├── config.py         # Configuration & .env
│   ├── models.py         # Optional: only when local models earn their cost
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

The generated API scaffold keeps the initial `items` command group in `main.py`.
Create `commands/<group>.py` modules only after multiple command groups or file
size justify the split. Do not leave a single-module `commands/` directory in
place; `test_flat_module_layout.py` fails that layout.

Reusable human-supplied secrets do not belong in any `.env` file shown here. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. The source tree carries `.env.example` only as a shape template.

When login needs required non-secret setup such as `BASE_URL`, declare `AUTH_CONFIG_PROMPTS` on `Config` instead of telling the user to edit `.env` manually. When the user must create a token or app first, declare `AUTH_SETUP_INSTRUCTIONS` with the canonical setup URL and brief steps.

### Key Components

**client.py:**
- `_make_request()` - HTTP requests with auth headers
- `_make_request_with_retry()` - Exponential backoff
- Resource methods (list_items, get_item, etc.)
- Token refresh logic (OAuth)

**Shared modules from `cli_tools_shared`:**
- `cli_tools_shared.filters` — `validate_filters()`, `apply_filters()`, `parse_filter_string()`, `apply_properties_filter()`, `apply_limit()`
- `cli_tools_shared.filter_map` — `FilterMap` class with `add_argument_mapping()`, `to_api_params()`
- `cli_tools_shared.bulk` — `BulkProcessor` for concurrent item processing
- `cli_tools_shared.models` — `CLIModel` and `AIInstruction` only when a local model or AI handoff earns its cost

### AI Instruction Results

All template types support AI instruction results for non-deterministic boundaries. Use the shared `AIInstruction` model and `print_ai_instruction()` helper when the CLI can gather context and define the objective but cannot choose or perform the next action deterministically.

The instruction result may allow the agent to use CLI commands, browser automation, file edits, screenshots, web search, or other tools. Tool choice belongs to the AI agent unless the instruction constraints narrow it. `verification_commands` and `follow_up_commands` are allowed only after the agent completes the instruction.

Do not add a required command path to the payload. `required_commands` is forbidden because the command is returning an AI instruction specifically when the next action is not deterministic.

### Exponential Retry Support

**API-type CLIs include built-in exponential retry** for transient errors. This improves reliability when dealing with rate limits, temporary server issues, or network problems.

**Retryable Conditions:**
| Type | Conditions |
|------|------------|
| HTTP Status Codes | 429 (Rate Limit), 500, 502, 503, 504 (Server Errors) |
| Network Errors | Connection errors, timeouts, chunked encoding errors |

**Default Configuration:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_retries` | `3` | Maximum retry attempts |
| `base_delay` | `1.0s` | Initial delay before first retry |
| `max_delay` | `30.0s` | Maximum delay between retries |
| `jitter` | `0.1` | Random jitter factor (+-10%) to prevent thundering herd |

**Backoff Formula:** `delay = min(base_delay * 2^attempt + jitter, max_delay)`

**Example delays:** 1s -> 2s -> 4s -> 8s -> ... (capped at 30s)

**Features:**
- Honors `Retry-After` header when present (common with 429 responses)
- Jitter prevents synchronized retries from multiple clients
- Authentication errors (401) trigger token refresh, not retry counting
- Disable retry per-request with `retry=False` parameter

**Customizing Retry Behavior:**

```python
# In client.py - customize at initialization
class MyToolClient:
    def __init__(self):
        # ... existing init code ...

        # Custom retry settings
        self.max_retries = 5       # More retries for flaky APIs
        self.base_delay = 0.5      # Faster initial retry
        self.max_delay = 60.0      # Allow longer waits
        self.jitter = 0.2          # More jitter (+-20%)
```

**Disabling Retry for Specific Requests:**

```python
# Skip retry for time-sensitive operations
response = self._make_request("POST", "/urgent-action", data=payload, retry=False)
```

### Dependencies
```
typer>=0.9.0
python-dotenv>=1.0.0
requests>=2.31.0
```

---

## Browser Template (`--type browser`)

**Purpose:** Web automation for sites without APIs, driven by
`BrowserAutomation` from `cli_tools_shared` (backed by `browser-harness`).

**Best for:**
- Sites with no public API
- Data extraction from rendered pages via JavaScript / DOM
- Form submission and browser-based automation
- Hybrid CLIs with both API and browser session auth

**IMPORTANT:** Only use after confirming no public or internal API exists and
Adam explicitly approves making the command browser-driven.

**Requires:** Nothing in PATH. `browser-harness` is a transitive dependency
of `cli-tools-shared`; it drives Chrome via CDP and manages its own browser
binary. There is no separate "install playwright" step.

### Architecture

The browser template integrates with the shared `cli-tools-shared`
infrastructure:

- **`config.py`** extends `BaseConfig` — profiles, runtime auth state, `.env` management
- **`browser.py`** subclasses `BrowserAutomation` and declares hooks only
  (no methods beyond `__init__`). The base class handles every auth lifecycle
  step using those hooks.
- **Auth** uses `create_auth_app()` from `cli_tools_shared.auth_commands`
  (no custom `auth.py`).
- **Named sessions** — each CLI gets an isolated browser-harness session
  via `SESSION_NAME` on the `BrowserAutomation` subclass.
- **`ClientError`** imported from `cli_tools_shared.exceptions` (not defined
  locally).

**Default auth:** `browser_session` (scaffolding script defaults browser
type to `--auth-type browser_session`).

### Structure
```
<name>/                          # <cli-tools-root>/<name>/
├── <name>_cli/
│   ├── __init__.py
│   ├── main.py           # Typer app (create_auth_app + cache + search)
│   ├── client.py         # Uses BrowserAutomation subclass via config.get_browser()
│   ├── browser.py        # BrowserAutomation subclass — declarative hooks only
│   ├── parsers.py        # Normalizers for DOM data returned by page.evaluate(...)
│   ├── config.py         # BaseConfig subclass with get_browser()
│   ├── models.py         # Optional: only when validation/serialization needs it
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md

# User profile data lives outside the tool dir (auto-managed by BaseConfig):
~/.local/share/cli-tools/<name>/
└── authentication_profiles/
    └── default/
        ├── .env              # CLI-managed runtime auth state / config
        ├── cache/            # Cached responses
        ├── browser-data/     # Storage state snapshot + session marker
        └── profile.json      # Auth marker
```

**Note:** No `commands/auth.py` — auth is handled by `create_auth_app()`
from `cli-tools-shared`.

The generated browser scaffold keeps its default search commands in `main.py`.
Split into `commands/<group>.py` only when the CLI grows beyond a single
resource group.

Reusable human-supplied secrets do not belong in any `.env` file shown here. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. The user-data `.env` files are limited to non-secret config and CLI-managed runtime auth state.

### Key Components

**config.py — BaseConfig subclass:**
```python
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "mysite-cli"
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://example.com"
    AUTH_CONFIG_PROMPTS = [("BASE_URL", "Site base URL", False)]
    AUTH_SETUP_INSTRUCTIONS = (
        "Before logging in:\n"
        "  1. Create the required token/app at https://example.com/settings/api\n"
        "  2. Follow the site's instructions, then continue here."
    )

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        return self.get_profile_data_dir()

    def get_browser(self):
        """Return the BrowserAutomation subclass for this CLI."""
        from .browser import MySiteBrowser
        return MySiteBrowser(self)
```

**browser.py — declarative hooks only:**
```python
from cli_tools_shared.auth import BrowserAutomation

from .config import get_config


class MySiteBrowser(BrowserAutomation):
    SESSION_NAME = "mysite"
    LOGIN_URL = "https://example.com/login"
    AUTH_CHECK_URL = "https://example.com/dashboard"
    AUTH_URL_PATTERN = r"/login|/register"
    AUTH_SUCCESS_SELECTOR = ""  # optional, prefer AUTH_LOGIN_FORM_SELECTOR
    AUTH_LOGIN_FORM_SELECTOR = 'input[type="password"], form[action*="login"]'

    def __init__(self, config=None):
        config = config or get_config()
        super().__init__(config)
```

If `browser.py` ever grows methods beyond `__init__`, something is wrong —
the auth lifecycle is the base class's responsibility. See the
`cli-tool-browser-expert` skill for the full hook reference.

**Hybrid auth example** (OAuth API + browser session):
```python
class Config(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.OAUTH, CredentialType.BROWSER_SESSION]
    # ... rest is the same
```

**main.py — uses create_auth_app():**
```python
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app

app.add_typer(create_auth_app(get_config, tool_name="mysite"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")
```

This gives the CLI: `auth login/logout/status/test/refresh/profiles`, and
`cache clear/status`.

**client.py — uses BrowserAutomation:**
```python
from cli_tools_shared.exceptions import ClientError

from .browser import MySiteBrowser
from .config import get_config


class MySiteClient:
    def __init__(self):
        self.config = get_config()
        self._browser: MySiteBrowser | None = None

    def _get_browser(self) -> MySiteBrowser:
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None
```

CLIs MUST NOT call browser binaries via `subprocess`/`Popen`, and MUST NOT
import `BrowserHarnessService` directly. All browser interaction goes
through `self._get_browser()` → `BrowserAutomation` → `BrowserHarnessService`
→ `browser-harness` daemon.

**parsers.py — normalize page-derived data (CRITICAL):**

**MANDATORY: Never write parsers from guesswork.** Capture real DOM data
first, then write a normalizer against actual structure:

```python
# In a debug helper or REPL, drive the page through the browser:
browser = config.get_browser()
page = browser.get_page("https://example.com/items")
raw = page.evaluate("""
    () => Array.from(document.querySelectorAll('.item')).map(el => ({
        id: el.dataset.id,
        title: el.querySelector('.title')?.textContent?.trim(),
        url:  el.querySelector('a')?.href,
    }))
""")
# Examine `raw`, then write parsers/normalizers against the real shape.
```

Then in `parsers.py`:
```python
def normalize_items(raw_items):
    return [
        {"id": r["id"], "title": r["title"], "url": r.get("url")}
        for r in raw_items
        if r.get("id") and r.get("title")
    ]
```

### Auth Flow

```
[User: mysite auth login]
    → create_auth_app() detects BROWSER_SESSION credential type
    → calls config.get_browser() → BrowserAutomation subclass instance
    → BrowserAutomation.authenticate() opens persistent browser to LOGIN_URL
    → User logs in manually in visible browser
    → persistent Chromium profile is written under
      get_profile_data_dir()/browser-data/chromium-profile/  → has_session() returns True

[User: mysite auth login --credential-type browser_session]  (hybrid CLIs)
    → skips API credential prompts, goes directly to browser login

[User: mysite auth status]
    → AuthVerifier inspects on-disk session files only — does NOT launch a
      browser. Returns canonical {profiles: [...]} JSON with per-credential
      type results under credential_types.<type>. For browser CLIs the
      browser_session / browser_available flags land inside
      credential_types.browser_session.
```

`auth status` reports the standard profile/credential JSON. If a CLI needs a
live browser check, use `mysite auth test` or the domain command that exercises
the authenticated page.

### Session Isolation

Each browser CLI gets its own named browser-harness session via
`SESSION_NAME` on the `BrowserAutomation` subclass. Two CLIs running with
different `SESSION_NAME` values do not share daemons, profile dirs, or
cookies.

### Dependencies
```
typer>=0.9.0
python-dotenv>=1.0.0
cli-tools-shared
```

`browser-harness` is pulled in transitively through `cli-tools-shared` and
is pinned to a specific commit. Do NOT add it as a direct dependency.

### Reference Implementation

See `<cli-tools-root>/brickfreedom/` for a complete working
example built on `BrowserAutomation` from `cli_tools_shared`.

---

## Wrapper Template (`--type wrapper`)

**Purpose:** Standardize existing CLI tools

**Best for:**
- Well-maintained existing CLIs (lpass, aws, gh, etc.)
- When you want JSON/table output from text-based CLIs
- Standardizing inconsistent interfaces

### Structure
```
<name>/
├── <name>_cli/
│   ├── __init__.py
│   ├── main.py           # Typer app setup
│   ├── client.py         # Subprocess wrapper and normalization
│   ├── parsers.py        # Output parsing (CRITICAL)
│   ├── config.py         # Configuration
│   ├── models.py         # Optional: only when local models earn their cost
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

The generated wrapper scaffold also starts flat: default commands live in
`main.py`, and `commands/<group>.py` is optional when multiple groups justify
it.

Reusable human-supplied secrets do not belong in any `.env` file shown here. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. The source tree carries `.env.example` only as a shape template.

### Key Components

**client.py:**
```python
def run_cli(self, *args) -> str:
    result = subprocess.run(
        [self.config.cli_command, *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ClientError(result.stderr)
    return result.stdout
```

**parsers.py (CRITICAL):**
Custom parsers for each output format:
```python
def parse_list_output(output: str) -> List[Dict]:
    """Parse 'Name [id: 123]' format."""
    items = []
    for line in output.strip().split('\n'):
        match = re.match(r'^(.+) \[id: (\d+)\]$', line)
        if match:
            items.append({"name": match.group(1), "id": match.group(2)})
    return items
```

**auth.py (optional split-out `create_auth_app` mount):**

**Hard rule:** wrapper CLIs MUST mount `create_auth_app` just like API CLIs — no hand-rolled `@app.command("status")` / `@app.command("login")` / `@app.command("logout")` functions. The upstream-CLI delegation happens inside `Config.test_connection()` (for status) and a `login_handler` passed to `create_auth_app` (for login). If the underlying CLI has no auth, skip auth entirely with `--auth-type none` when scaffolding.

If you split auth out of `main.py`, the entire `commands/auth.py` is ~4 lines:

```python
"""Authentication commands for MyWrapper CLI."""
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config


def _upstream_login_handler(config, force: bool):
    """Delegate login to upstream CLI."""
    import subprocess, typer
    args = ["underlying-cli", "auth"]
    if force:
        subprocess.run(args + ["logout"], capture_output=True, text=True, timeout=60)
    result = subprocess.run(args + ["login"], text=True, timeout=300)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="mywrapper",
    login_handler=_upstream_login_handler,
)
```

`Config.test_connection()` (in `config.py`) handles the `auth status` side — it subprocesses `underlying-cli auth status`, parses the `{profiles: [...]}` JSON, and returns a dict that `create_auth_app` merges into `credential_types.<type>` on the wrapper's own status output. See `references/auth-standards.md` ("`auth status` JSON Shape") for the full canonical shape.

**When to include wrapper auth:**
- The underlying CLI requires authentication (API keys, login, etc.)
- Users expect `<cli> auth status` to work on the wrapper
- The wrapper adds additional config beyond underlying CLI auth

**When to skip wrapper auth (use `--auth-type none`):**
- The underlying CLI is a local tool with no auth (e.g., `cliclick`, `ffmpeg`)
- The wrapper is a convenience layer that adds no credentials

**Reference implementation:** See `n8n-cli-tool-node-converter` once its migration to `create_auth_app` lands for the canonical wrapper-subprocess pattern. Until then, `notion_cli/commands/auth.py` (4 lines, no `login_handler`) is the minimal `create_auth_app` mount.

### Dependencies
```
typer>=0.9.0
python-dotenv>=1.0.0
```

### Automatic CLI Installation
Wrapper CLIs must provision the official upstream binary named by
`CLI_COMMAND`. A completed wrapper cannot leave the wrapped binary as a manual
user prerequisite or report it as a live API smoke-test/auth blocker.

The `new-cli-tool` script automatically:
1. Checks if the underlying CLI is in PATH
2. If not found, installs known Homebrew-distributed CLIs
3. Uses package mapping for non-standard Homebrew names

| CLI Command | Brew Package |
|-------------|--------------|
| `lpass` | `lastpass-cli` |
| `aws` | `awscli` |
| `gcloud` | `google-cloud-sdk` |
| `az` | `azure-cli` |
| `kubectl` | `kubernetes-cli` |
| `rg` | `ripgrep` |

If the official upstream CLI is distributed through npm, pipx, uv, or a vendor
installer instead of Homebrew, add that official bootstrap to the wrapper source
or repo-owned install workflow before marking the wrapper complete. API-key auth
may remain user-configured only after the upstream binary is present and
`<cli-command> --help` exits `0`.

---

## File Responsibilities

### `pyproject.toml`
Project metadata and entry point configuration:

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "mytool-cli"
version = "0.1.0"
description = "CLI interface for MyTool API"
requires-python = ">=3.9"
dependencies = [
    "typer>=0.9.0",
    "python-dotenv>=1.0.0",
    "requests>=2.31.0",
]

[project.scripts]
mytool = "mytool_cli.main:app"

[tool.setuptools.packages.find]
where = ["."]
include = ["mytool_cli*"]
```

### `__init__.py`
Package initialization with warning suppression:

```python
"""MyTool CLI - Command-line interface for MyTool API."""
# Suppress urllib3 SSL warnings (LibreSSL compatibility) - must be before urllib3 import
import warnings
warnings.filterwarnings("ignore", module="urllib3")

__version__ = "0.1.0"
```

### `main.py`
Main Typer application that registers command groups:

```python
"""Main entry point for MyTool CLI."""
import typer
from typing import Optional
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = typer.Typer(
    name="mytool",
    help="CLI interface for MyTool API",
    add_completion=True,  # Enables --install-completion
)

# Register command modules
from .commands import resource1, resource2
register_commands(app, get_config, resource1, name="resource1", help="Manage resource1")
register_commands(app, get_config, resource2, name="resource2", help="Manage resource2")

@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", help="Show version and exit", is_eager=True
    ),
):
    """MyTool CLI - Manage MyTool from the command line."""
    if version:
        typer.echo("mytool-cli version 0.1.0")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()

def main():
    """Main entry point."""
    try:
        app()
    except ClientError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2)
    except KeyboardInterrupt:
        typer.echo("\nAborted!", err=True)
        raise typer.Exit(130)

if __name__ == "__main__":
    main()
```

### `config.py`
Configuration management using environment variables:

**CRITICAL**: Always use `.resolve()` when computing the config directory path.

```python
"""Configuration management for MyTool CLI."""
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv, set_key

class Config:
    def __init__(self):
        # IMPORTANT: Use resolve() to get absolute path - ensures .env is found regardless of cwd
        config_dir = Path(__file__).resolve().parent.parent
        self.env_file_path = config_dir / ".env"
        if self.env_file_path.exists():
            load_dotenv(self.env_file_path, override=True)

    @property
    def api_key(self) -> Optional[str]:
        return os.getenv("MYTOOL_API_KEY")

    def get_missing_credentials(self) -> list[str]:
        missing = []
        if not self.api_key:
            missing.append("MYTOOL_API_KEY")
        return missing

_config: Optional[Config] = None

def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
```

### `client.py` (API Type)
Service client with error handling:

```python
"""MyTool service client."""
from typing import Any, Dict, List, Optional
from .config import get_config
from cli_tools_shared.filter_map import FilterMap

class ClientError(Exception):
    """Custom exception for client errors."""
    pass

class MyToolClient:
    def __init__(self):
        self.config = get_config()
        missing = self.config.get_missing_credentials()
        if missing:
            raise ClientError(f"Missing credentials: {', '.join(missing)}")
        self._setup_filters()

    def _setup_filters(self):
        """Configure filter mappings for API translation."""
        self.filter_map = FilterMap()
        self.filter_map.register_api_translator(
            'status', lambda op, val: {'status': val}
        )

    def list_items(
        self,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Dict]:
        """List items with limit and filtering.

        Limiting: API-level (uses 'per_page' query param)
        Filtering:
            API-level: status, type, created_after
            Client-side: name (API doesn't support text search)
        """
        params = {"per_page": limit}
        if filters:
            api_params = self.filter_map.to_api_params(filters)
            params.update(api_params)

        response = self._make_request("GET", "/items", params=params)

        # Extract array from wrapped response if needed
        items = response.get("data", response) if isinstance(response, dict) else response

        # Apply client-side filters for fields API doesn't support
        if filters:
            items = self.filter_map.apply_client_filters(items, filters)

        return items

    def get_item(self, item_id: str) -> Dict:
        """Get a specific item - returns only the resource object."""
        response = self._make_request("GET", f"/items/{item_id}")
        return response.get("data", response) if isinstance(response, dict) and "data" in response else response

_client: Optional[MyToolClient] = None

def get_client() -> MyToolClient:
    """Get or create the global client instance."""
    global _client
    if _client is None:
        _client = MyToolClient()
    return _client
```

### `client.py` (Wrapper Type)

For wrapper CLIs, the client uses subprocess instead of HTTP requests:

```python
"""MyTool wrapper client."""
import subprocess
from typing import Dict, List, Optional
from .config import get_config
from .parsers import parse_cli_output
from cli_tools_shared.filter_map import FilterMap

class ClientError(Exception):
    pass

class MyToolClient:
    def __init__(self):
        self.config = get_config()
        if not self.config.is_cli_available():
            raise ClientError(f"CLI '{self.config.cli_command}' not found in PATH")
        self._setup_filters()

    def _setup_filters(self):
        """Configure filter mappings."""
        self.filter_map = FilterMap()

    def _run_command(self, args: List[str], check: bool = True) -> subprocess.CompletedProcess:
        """Run underlying CLI command."""
        cmd = [self.config.get_cli_executable()] + args
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if check and result.returncode != 0:
            raise ClientError(f"Command failed: {result.stderr}")
        return result

    def auth_login(self) -> Dict:
        """Delegate login to underlying CLI."""
        result = self._run_command(["login"], check=False)
        return {"success": result.returncode == 0, "message": result.stdout.strip()}

    def auth_status(self) -> Dict:
        """Check auth via underlying CLI's status command."""
        result = self._run_command(["status"], check=False)
        return {
            "authenticated": result.returncode == 0,
            "cli_command": self.config.cli_command,
            "cli_version": self.config.get_cli_version(),
        }

    def list_items(
        self,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Dict]:
        """List items from underlying CLI.

        Limiting: CLI-level if supported, otherwise client-side
        Filtering: Client-side (underlying CLI doesn't support filtering)
        """
        args = ["ls"]
        if hasattr(self, '_cli_supports_limit') and self._cli_supports_limit:
            args.extend(["--limit", str(limit)])

        result = self._run_command(args)
        items = parse_cli_output(result.stdout)

        # Client-side limiting if CLI doesn't support it
        if not hasattr(self, '_cli_supports_limit') or not self._cli_supports_limit:
            items = items[:limit]

        # Client-side filtering (most CLIs don't support filtering)
        if filters:
            items = self.filter_map.apply_client_filters(items, filters)

        return items
```

### Output Functions

Output functions are provided by `cli_tools_shared.output`. Import them directly:

```python
from cli_tools_shared.output import print_json, print_table, print_error, print_success, print_info, handle_error
```

No local `output.py` file is needed in CLIs.

### Optional `commands/<resource>.py`
Use a command module only when the CLI already has multiple command groups or
`main.py` has grown large enough that the split earns its complexity. Fresh
scaffolds keep the first resource group in `main.py`.

```python
"""Item commands for MyTool CLI."""
import typer
from typing import List, Optional
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error, print_success

app = typer.Typer(help="Manage items")


def extract_field(item: dict, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    parts = field.split(".")
    value = item
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items, supporting dot-notation."""
    result = []
    for item in items:
        extracted = {}
        for field in fields:
            value = extract_field(item, field)
            extracted[field] = value
        result.append(extracted)
    return result


@app.command("list")
def item_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display (supports dot-notation)"),
):
    """List all items."""
    try:
        client = get_client()
        items = client.list_items(limit=limit, filters=filter)

        # Apply output field selection with dot-notation support
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            items = extract_fields(items, fields)

        if table:
            columns = fields if properties else ["id", "name"]
            print_table(items, columns, columns)
        else:
            print_json(items)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def item_get(
    item_id: str = typer.Argument(..., help="Item ID"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display (supports dot-notation)"),
):
    """Get a specific item."""
    try:
        client = get_client()
        item = client.get_item(item_id)

        # Apply output field selection with dot-notation support
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            item = extract_fields([item], fields)[0]

        if table:
            columns = list(item.keys())
            print_table([item], columns, columns)
        else:
            print_json(item)
    except Exception as e:
        raise typer.Exit(handle_error(e))
```

---

## Placeholder Reference

Templates use these placeholders (replaced by new-cli-tool):

| Placeholder | Example | Usage |
|-------------|---------|-------|
| `{{name}}` | `airtable` | Imports, commands |
| `{{name_underscore}}` | `airtable_cli` | Package name |
| `{{Name}}` | `Airtable` | Class names |
| `{{NAME}}` | `AIRTABLE` | Environment variables |
| `{{base_url}}` | `https://api.airtable.com/v1` | API base URL |
| `{{cli_command}}` | `lpass` | Underlying CLI (wrapper) |
| `{{credential_types}}` | `CredentialType.API_KEY` | CredentialType list (set via `--auth-type`, repeatable) |
| `{{description}}` | `Manage records` | Short description |
| `{{docs_url}}` | `https://...` | Documentation URL |

---

## Typer App Configuration

### Main App (main.py)

Uses callback pattern for `--version` support and help-on-no-command:

```python
app = typer.Typer(
    name="{{name}}",
    help="CLI interface for {{Name}}",
    add_completion=True,
)

@app.callback(invoke_without_command=True)
def callback(ctx: typer.Context, version: ...):
    if version:
        typer.echo(f"{{name}}-cli version {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()
```

### Subcommand Apps

Whether a subcommand app lives in `main.py` or `commands/*.py`, it MUST include
`no_args_is_help=True`:

```python
# REQUIRED - ensures help shown when no command specified
app = typer.Typer(help="Manage resources", no_args_is_help=True)
```

---

## Customization Points

After scaffolding, customize:

**All types:**
- **Define command output shape first**
  - Exact JSON fields and table columns
  - Required derived fields such as stable IDs
  - Local models only when validation, polymorphism, or serialization earns the code
- Start with resource commands in `main.py`; split into `commands/` only when multiple groups justify it
- Update `.env.example` with required variables
- Implement auth methods

**API type:**
- Implement API methods in `client.py` - return records matching the command contract
- Configure filter_map.py for server-side filtering
- Add retry logic for rate limits

**Browser type:**
- **Capture real DOM data FIRST** via `config.get_browser().get_page(url).evaluate(...)` before writing any parsers
- For login/status proof scripts on pages that redirect during authentication,
  do not poll visibility with repeated `page.evaluate(...)` calls. Use
  Playwright locator waits such as `page.locator(selector).first.wait_for(...)`
  or `is_visible(timeout=...)` so navigation is handled by the browser driver.
  If raw evaluation is unavoidable for a DOM-capture probe, treat
  "Execution context was destroyed" as a navigation-in-progress signal only:
  wait for the page to settle, then retry the bounded probe instead of
  classifying it as login failure or credential failure.
- Implement `parsers.py` based on REAL DOM patterns (never guess)
- Add domain methods to `client.py` using the `BrowserAutomation` subclass via `self.config.get_browser()`
- Validate every parser against actual captured data before marking complete
- Customize auth detection if needed
- Scraping methods must return records matching the command contract

**Wrapper type:**
- Add custom parsers in `parsers.py`
- Map underlying CLI commands to standard patterns
- Parse output into records matching the command contract

---

## Data Shape Architecture

The external Typer command contract is the primary requirement. Internal data
representation should be the smallest clear shape that preserves documented
stdout and table output.

### Plain Record Structure

Use plain dict records when parsed/API data can flow directly to output:

```python
def normalize_order(raw: dict) -> dict:
    return {
        "id": raw["id"],
        "customer_id": raw["customer_id"],
        "status": raw["status"],
        "total": raw["total"],
    }
```

### When To Add Local Models

Add `models.py` or `models/` only when it removes real complexity:
- required-field validation catches malformed upstream data
- polymorphic child objects need typed serialization
- enums materially clarify a fixed service vocabulary
- the command returns shared `AIInstruction`

```python
from cli_tools_shared.models import CLIModel


class Order(CLIModel):
    id: str
    customer_id: str
    status: str
```

### Data Shape Principles

1. **Do not add local models by default** - start with command output.
2. **Do not keep unused direct dependencies** - dependency declarations must match runtime imports.
3. **Do not add pure re-export modules** - import shared helpers directly.
4. **Keep metadata-only command modules to metadata** - one `COMMAND_CREDENTIALS` assignment.
5. **Keep BrowserAutomation subclasses declarative** - constants only.
6. **Use `SerializeAsAny`** for lists of polymorphic models when local models exist.

### Client Methods Return Contract Records

```python
def list_orders(self, limit: int = 100) -> list[dict]:
    response = self._make_request("GET", "/orders", params={"limit": limit})
    return [normalize_order(item) for item in response]

def get_order(self, order_id: str) -> dict:
    response = self._make_request("GET", f"/orders/{order_id}")
    return normalize_order_detail(response)
```

### SerializeAsAny for Polymorphic Child Lists

**When a parent model contains a list of child models that have subclasses, you MUST use `SerializeAsAny`.**

Without it, Pydantic only serializes base class fields, losing subclass-specific data.

```python
from pydantic import SerializeAsAny
from typing import List, Optional

# Base step class with subclasses
class Step(CLIModel):
    step_number: int
    action_type: str

class VariableStep(Step):
    variable_name: str
    code: str

class HttpStep(Step):
    url: str
    method: str

# Parent model containing steps
class Flow(CLIModel):
    id: str
    name: str
    # WRONG - loses subclass fields (variable_name, code, url, method)
    # steps: Optional[List[Step]] = None

    # CORRECT - preserves all fields from actual step types
    steps: Optional[List[SerializeAsAny[Step]]] = None
```

**Result comparison:**
```python
# Without SerializeAsAny - BROKEN (missing variable_name, code):
{"id": "1", "steps": [{"step_number": 1, "action_type": "Variable"}]}

# With SerializeAsAny - CORRECT (all fields present):
{"id": "1", "steps": [{"step_number": 1, "action_type": "Variable", "variable_name": "x", "code": "..."}]}
```

**When to use:**
- Any `List[BaseModel]` where BaseModel has subclasses
- Models populated by factory functions that return different types
- Any polymorphic model hierarchy stored in a parent model
