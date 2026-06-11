# Common CLI Issues and Quick Fixes

## Shadowed Launcher on PATH (older install ahead of uv tool symlink)

### Symptom
The CLI starts but fails with a misleading error such as
`ModuleNotFoundError: No module named 'cli_tools_shared'`, or `auth status`
returns a JSON shape that doesn't match the standard
`profiles[].credential_types{}` schema even though the source uses
`create_auth_app`. `which <tool>` resolves to something other than
`~/.local/bin/<tool>` — typically `/opt/homebrew/bin/<tool>`,
`/usr/local/bin/<tool>`, or `/opt/homebrew/opt/python@*/...`.

### Diagnosis
```bash
# Always check ALL entries on PATH, not just the first
which -a <tool>

# Inspect each non-uv launcher
ls -la /opt/homebrew/bin/<tool> /usr/local/bin/<tool> 2>/dev/null
head -3 /opt/homebrew/bin/<tool> 2>/dev/null
```

A stale launcher typically points to a different Python interpreter
(`#!/opt/homebrew/opt/python@3.14/bin/python3.14`) or an old Node.js
package (`/lib/node_modules/.../bin/<tool>.js`).

### Fix
Remove every non-uv launcher so `~/.local/bin/<tool>` (the uv tool
symlink) is the only one on PATH:

```bash
rm /opt/homebrew/bin/<tool>     # Homebrew shadow
rm /usr/local/bin/<tool>        # legacy or sudo-installed shadow (may need sudo)
```

Then verify:
```bash
which -a <tool>     # should list ONLY ~/.local/bin/<tool>
<tool> auth status  # must return profiles[].credential_types{...} JSON
```

If the stale launcher is root-owned (`ls -la` shows `root wheel`),
`rm` fails with "Permission denied". Agent shell sessions usually should not
run privileged delete commands. Ask the user to run
`sudo rm /usr/local/bin/<tool>` manually.

### Recurrence Prevention
Always run `which -a <tool>` (not just `which`) as the first diagnostic
when a uv-installed CLI behaves wrong. Multiple entries indicates
shadowing. Never accept the first PATH entry without confirming it
points at `~/.local/share/uv/tools/<pkg-name>/bin/<tool>`.

**General rule:** A CLI tool that "works yesterday but fails today" or
"is installed but the wrong thing runs" is almost always a PATH
shadowing problem, not a CLI bug. Inspect every entry `which -a`
returns before changing any code.

---

## CLI Won't Install / Command Not Found

### Symptom
```bash
$ myservice --version
zsh: command not found: myservice
```

Or a source checkout reinstall with system Python fails:

```bash
$ python3 -m pip install -e .
error: externally-managed-environment
```

### Diagnosis
```bash
# Check if symlink exists
ls -la ~/.local/bin/myservice

# Check if registered as uv tool
uv tool list | grep myservice

# Check if package is installed
uv tool install -e <cli-tools-root>/myservice --force --refresh
```

### Fixes

**Reinstall via uv:**
```bash
uv tool install -e <cli-tools-root>/myservice --force --refresh
```

For the current checkout:

```bash
uv tool install --editable . --force
```

Do not use Homebrew/system `pip install -e .` or
`--break-system-packages`. CLI tools are installed as uv tools, and
`~/.local/bin/<tool>` should point into `~/.local/share/uv/tools/`.

**Or use the install script:**
```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/install-cli-tool.sh myservice
```

---

## Authentication Fails

### Symptom
```bash
$ myservice auth status
Error: Missing credentials. Run 'myservice auth login' first.
```

### Diagnosis
```bash
# Check environment variables
env | grep -i MYSERVICE

# Check the profile .env managed by BaseConfig
cat ~/.local/share/cli-tools/myservice/authentication_profiles/default/.env

# Check reusable CLI secrets before asking Adam for the value; see references/secrets.md

# Verify the installed CLI resolves the intended profile
launcher="$(command -v myservice)"
interpreter="$(head -1 "$launcher" | sed 's/^#!//')"
"$interpreter" -c "from myservice_cli.config import get_config; print(get_config(profile='default').env_file_path)"
```

If the tool has multiple active profiles, direct Python probes must pass
`profile='<name>'` or instantiate `Config(profile='<name>')`. Do not rely on
ambient shell variables such as `MYSERVICE_PROFILE`, `JIRA_PROFILE`, or
`CLI_TOOLS_PROFILE`; `BaseConfig` does not use them for ad-hoc Python imports.

### Fixes

**Store reusable CLI credentials:**
Follow `references/secrets.md`.

**Run login command:**
```bash
myservice auth login
```

**Fix config.py path (CRITICAL):**
```python
# WRONG - CLI fails when run from other directories
ENV_PATH = Path(__file__).parent.parent / ".env"

# CORRECT - Always finds .env
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
```

---

## Commands Not Available

### Symptom
```bash
$ myservice items list
Error: No such command 'items'.
```

### Diagnosis
```bash
# Check available commands
myservice --help

# Check command registration in the actual layout
rg -n '@.*command|add_typer' <cli-tools-root>/myservice/myservice_cli
```

### Fixes

**Add missing command decorator:**
```python
# In main.py (default scaffold) or commands/items.py (split layout)
@items_app.command("list")  # Or @app.command("list") in a split command module
def list_items(...):
    ...
```

**Register the subcommand app in main.py:**
```python
items_app = typer.Typer(help="Manage items", no_args_is_help=True)
app.add_typer(items_app, name="items")
```

**Reinstall after changes:**
```bash
uv tool install -e <cli-tools-root>/myservice --force --refresh
```

---

## Output Format Issues

### Symptom
- JSON output has extra text mixed in
- Table output is broken
- Messages appear in piped output

### Diagnosis
```bash
# Test JSON output purity
myservice items list 2>/dev/null | jq '.'

# Check for raw print statements
grep -n "^print(" <cli-tools-root>/myservice/myservice_cli/commands/*.py
```

### Fixes

**Use correct output functions:**
```python
# WRONG
print(json.dumps(data))
print(f"Found {len(data)} items")

# CORRECT
print_json(data)           # Data to stdout
print_info(f"Found {len(data)} items")  # Message to stderr
```

**Use stderr for messages:**
```python
# WRONG - pollutes stdout
typer.echo("Processing...")

# CORRECT - goes to stderr
typer.echo("Processing...", err=True)
# Or use output.py functions
print_info("Processing...")
```

---

## Filtering Not Working

### Symptom
- `--filter` returns same results
- Filter applied but wrong results

### Diagnosis
```bash
# Test filter
myservice items list --filter "status:active" | jq 'length'
myservice items list | jq 'length'  # Compare counts

# Check implementation
grep -n "apply_filters\|filter_map" <cli-tools-root>/myservice/myservice_cli/client.py
```

### Fixes

**Validate filters are passed:**
```python
# Ensure filters parameter reaches client method
def list_items(self, filters: Optional[List[str]] = None):
    if filters:
        validate_filters(filters)  # Add validation
    ...
```

**Check API parameter translation:**
```python
# Debug what's being sent
api_params = filter_map.to_api_params(filters)
print(f"API params: {api_params}", file=sys.stderr)  # Debug
```

**Implement filter_map correctly:**
```python
# Register translator for each filterable field
filter_map.register_api_translator('status', lambda op, val: {'status': val})
```

---

## Limit Not Applied

### Symptom
```bash
$ myservice items list --limit 5 | jq 'length'
100  # Expected 5
```

### Diagnosis
```bash
# Check client implementation
grep -n "limit\|:limit" <cli-tools-root>/myservice/myservice_cli/client.py
```

### Fixes

**Pass limit to API (CORRECT):**
```python
def list_items(self, limit: int = 100):
    params = {"limit": limit}  # Pass to API
    response = self._make_request("GET", "/items", params=params)
    return response
```

**DON'T slice client-side:**
```python
# WRONG - fetches all then slices
def list_items(self, limit: int = 100):
    response = self._make_request("GET", "/items")
    return response[:limit]  # BAD!
```

---

## Wrapper CLI - Underlying CLI Not Found

### Symptom
```bash
$ myservice auth status
Error: 'lpass' not found. Install with: brew install lastpass-cli
```

### Fixes

**Install underlying CLI:**
```bash
# Common CLIs and their brew packages
brew install lastpass-cli  # for lpass
brew install awscli       # for aws
brew install gh           # for gh
```

**Verify installation:**
```bash
which lpass
lpass --version
```

---

## Manual Import Tests Fail With ModuleNotFoundError (Wrong Interpreter)

### Symptom
You manually import a CLI's modules with plain `python3` and get errors like:
```bash
$ python3 - <<'PY'
import copilot_cli.main
PY
# ModuleNotFoundError: No module named 'httpx'

$ python3 - <<'PY'
import jira_cli.config
PY
# ModuleNotFoundError: No module named 'cli_tools_shared'
```

### Root Cause
`python3` on the system PATH is NOT the interpreter the CLI actually runs with.
Every CLI installed by `uv tool install` has its own isolated venv at
`~/.local/share/uv/tools/<pkg-name>/` and the launcher at `~/.local/bin/<cli>`
has a shebang that points to that venv's interpreter:

```bash
$ head -1 ~/.local/bin/copilot
#!~/.local/share/uv/tools/copilot-cli/bin/python3
```

A plain `python3` (e.g. Homebrew's `python@3.14`) does NOT have the CLI's
declared dependencies (`httpx`, `pydantic`, `cli-tools-shared`, etc.)
installed, so any `import <cli_name>_cli...` will fail. That failure has
nothing to do with the CLI itself — it's a wrong-interpreter diagnosis.

### Fix — Always Use the CLI's Own Interpreter for Ad-Hoc Imports

**Never** import CLI modules with bare `python3`. Inspect the installed
launcher and use the interpreter named in its shebang:

```bash
# Correct — apples-to-apples manual import test
launcher="$(command -v jira)"
interpreter="$(head -1 "$launcher" | sed 's/^#!//')"
"$interpreter" -c "import jira_cli.config; print(jira_cli.config.__file__)"
```

Replace `jira` and `jira_cli.config` with the target CLI command and module.
Do not derive the uv tool path from the command name; the launcher shebang is
the source of truth.

### Second Wrinkle: sys.path Depends on CWD
The uv tool venv's interpreter picks up the local editable source when run
from inside the CLI repo (`<cli-tools-root>/<name>`), and the
installed copy when run from anywhere else. If you need to test the
installed copy specifically, `cd /` (or anywhere outside the repo) first.

### Validation
Running the CLI itself (`copilot --help`, `copilot auth status`) is the
real auth/functionality signal — not bare-python import tests. The installed
CLI interpreter is also not the pytest runner. Its uv tool venv is runtime-only
and does not include test-only packages such as `pytest`. For focused per-tool
pytest runs, use the tool's uv project and inject pytest into that run:

```bash
uv run --project <cli-tools-root>/<name> --with pytest python -m pytest <cli-tools-root>/<name>/tests
```

If `test-cli-tool.sh` or `validate-cli-tool.sh` report a shebang mismatch,
reinstall:
```bash
uv tool install -e <cli-tools-root>/<name> --force --refresh
```

---

## Import Errors on Startup

### Symptom
```bash
$ myservice --help
ImportError: cannot import name 'xyz' from 'myservice_cli'
```

### Fixes

**Check circular imports:**
- Ensure commands don't import from each other
- Use local imports if needed

**Verify __init__.py:**
```python
# In myservice_cli/__init__.py
__version__ = "0.1.0"
# Don't import heavy modules here
```

**Reinstall:**
```bash
uv tool install -e <cli-tools-root>/myservice --force --refresh
```

---

## Issue: `test_env_has_active_profile` / `test_each_auth_type_has_one_active_profile` Fail After Adding a CLI

**Symptom:**
```
'<cli>' has no active profile .env at
  /Users/<user>/.local/share/cli-tools/<cli>/authentication_profiles/default/.env.
All auth-capable CLI tools must auto-initialise the active profile
via BaseConfig on first invocation.
```

**Cause:** `BaseConfig.__init__` is responsible for auto-initialising the first active profile under
`~/.local/share/cli-tools/<tool>/authentication_profiles/default/.env` (inside the tool user profile folder) on first
invocation. If `Config(...)` is never constructed when the CLI runs — for example because
`create_auth_app(get_config_fn=...)` is not wired up, or `main.py` skips the standard auth app
factory — the directory is never created and the profile compliance tests fail.

Do NOT create a `.env` in the CLI source tree. Profile data is user-machine state and must live
under the tool user profile folder (`~/.local/share/cli-tools/<tool>`), not inside `<cli-tools-root>/<cli>/`. The single source of
truth for the path is `cli_tools_shared.config.get_profiles_base_dir(<cli>)`.

**Fix:** Use the standard scaffolding. Ensure `main.py` calls `create_auth_app(get_config_fn=get_config)`
from `cli_tools_shared.auth_commands`, and that `get_config()` returns the CLI's `Config(BaseConfig)`
instance. Then either:

1. Run any command (e.g. `<cli> auth status`) once — this constructs `Config()` and triggers
   `BaseConfig` to auto-initialise the active profile, OR
2. Run `<cli> auth login` to capture real credentials.

Both paths produce the same on-disk result: `~/.local/share/cli-tools/<cli>/authentication_profiles/default/.env`
with `ACTIVE=true`.

**Verification:**
```bash
<cli> --help > /dev/null
ls ~/.local/share/cli-tools/<cli>/authentication_profiles/default/.env   # must exist
<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name <cli>  # both tests pass
```

**Recurrence Prevention:** The compliance tests resolve the profile path via
`cli_tools_shared.config.get_profiles_base_dir(cli_name)` rather than hardcoding any location, so
the test stays in sync with the canonical path resolver. The shared `cli_tools_shared` package
auto-migrates any legacy repo-local `.env` files into the per-profile layout on first construction
of `BaseConfig` — never create `.env` in the source tree to "satisfy" the test; that file gets
migrated away. If a future change moves the profile root, update `get_profiles_base_dir` in one
place and both the tests and CLIs follow automatically.

---

## Quick Reference: Test After Fixes

Always verify fixes work:

```bash
# Basic functionality
myservice --version
myservice --help

# Auth
myservice auth status

# List with options
myservice items list --table
myservice items list --limit 5
myservice items list --filter "status:active"

# Full test suite
<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name myservice
```
