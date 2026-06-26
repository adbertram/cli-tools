<required_reading>
Before testing, understand the standards:
- `references/output-standards.md` - Output streams, format rules, list command requirements
- `references/command-standards.md` - Command naming, options, exit codes
- `references/model-standards.md` - output-first data shape standards
- `references/filtering.md` - Filtering architecture requirements
</required_reading>

<process>
## Step 1: Pre-flight Check and Run Test Script

If not provided, ask: "Which CLI tool do you want to test?"

Parse arguments to extract the tool name, optional `--verbose` flag, and optional `--command` filter.

**Pre-flight Check:** Before running pytest, verify the CLI is functional:

```bash
$TOOL_NAME --help >/dev/null 2>&1
```

If this fails, investigate the CLI startup error BEFORE running tests.

**Harness-only collection:** When validating changes to the cli-tool test
harness itself, collect tests with the batch confirmation flag so
`pytest_configure` does not abort:

```bash
uv run --project <cli-tools-root>/_repo/skills/cli-tool python -m pytest --collect-only <cli-tools-root>/_repo/skills/cli-tool/tests --force
```

This only proves the harness collects. It is not a replacement for CLI-specific validation through `<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name "$TOOL_NAME"`.

**Harness batch execution:** When validating harness unit tests without a
specific CLI target, run pytest through the cli-tool skill uv project and pass
the batch confirmation flag:

```bash
uv run --project <cli-tools-root>/_repo/skills/cli-tool python -m pytest <cli-tools-root>/_repo/skills/cli-tool/tests --force
```

Do not run `python3 -m pytest <cli-tools-root>/_repo/skills/cli-tool/tests`
directly. That bypasses the skill project's declared `cli-tools-shared`
dependency, and CLI-dependent tests are only valid without `--cli-name` when
`--force` explicitly confirms a batch/collect-only harness run where those
tests may skip.

**UV validation serialization:** Run `uv run`, `uv sync`, `uv lock`,
`uv pip install`, `uv tool install`, and related environment-mutating
validation commands sequentially for this repo unless each command uses a
proven separate project directory, virtual environment, and `UV_CACHE_DIR`.
Do not launch multiple `uv run --project ... --with ...` pytest validations in
parallel from the same cli-tools checkout or shared uv cache; uv's project and
ephemeral overlay/cache state is mutable and parallel runs can corrupt import
paths. If a prior parallel run produced a malformed `_uv_ephemeral_overlay.pth`
or unexpected `ModuleNotFoundError`, remove or isolate the affected uv cache and
rerun the validations one at a time.

**Targeted harness execution:** If you run a direct `pytest -k ...` selection
against harness tests and the selection includes any CLI-dependent test, pass
`--cli-name "$TOOL_NAME"`. Use `--force` only for batch or collect-only harness
checks where CLI-dependent tests are allowed to skip.

**Direct per-tool pytest execution:** First resolve the actual tool directory
that contains the target CLI's `pyproject.toml`; do not derive it from the CLI
command name. Some tools live below `_personal/`, for example `ata-blog` lives at
`<cli-tools-root>/_personal/ata-blog`, so `<cli-tools-root>/$TOOL_NAME` is not a
safe project path. Every CLI must declare `pytest` as a dev dependency
(`[dependency-groups]` `dev = ["pytest>=7.0.0"]`) so `uv sync` installs it into
the project `.venv`. Run a tool's own tests through the project venv
interpreter, not a bare global `pytest`. The always-safe command is the uv
project run below, which injects pytest with `--with pytest` and works whether or
not the dev group has been synced. After `uv sync`, `uv run pytest` (from the
tool dir) and `.venv/bin/python -m pytest` are equally valid because both resolve
the project `.venv` where editable `cli_tools_shared` imports cleanly.

Do not run a bare `pytest` executable, `PYTHONPATH=. pytest`, ambient
`python3 -m pytest`, or any other interpreter outside the tool's `.venv`/uv
project. When `pytest` is missing from the project `.venv`, `uv run pytest`
silently falls back to the global pipx pytest, whose interpreter cannot import
editable `cli_tools_shared`; the suite then fails collection with
`ModuleNotFoundError: No module named 'cli_tools_shared'`. If you hit that error,
the fix is to declare+sync the dev group (or use the `--with pytest` command
below), not to switch to another ambient interpreter.

Before reading or passing a tool's test paths to `sed`, `cat`, `nl`, `wc`,
`head`, `tail`, `grep`, `rg`, or direct `pytest`, discover the real test files
or prove the `tests` directory exists. Do not infer conventional filenames such
as `tests/test_<tool>.py`, `tests/test_cli.py`, or `tests/test_commands.py`. If
no tests directory exists, report `SKIP_MISSING` and use the harness script
below instead of a guessed file path.

Apply the same rule to shared harness paths. Do not assume root-level paths such
as `<cli-tools-root>/tests/conftest.py` exist. Discover the harness files under
`<cli-tools-root>/_repo/skills/cli-tool/tests` or the shared-package files under
`<cli-tools-root>/_repo/cli-tools-shared/tests`, keep only proven regular files,
and read or pass only those proven paths.

```bash
uv run --project <tool-dir> --with pytest python -m pytest <tool-dir>/tests
```

**Direct shared-package pytest execution:** When running tests for
`<cli-tools-root>/_repo/cli-tools-shared`, treat `cli-tools-shared` as its own
uv project, not as a CLI tool directory. Do not run `uv run pytest` from inside
`_repo/cli-tools-shared`; that can resolve the `pytest` executable without the
shared package on the import path, causing `ModuleNotFoundError:
cli_tools_shared` while loading `tests/conftest.py`.

Use `python -m pytest` through the shared package project and inject pytest into
that run:

```bash
uv run --project <cli-tools-root>/_repo/cli-tools-shared --with pytest python -m pytest <cli-tools-root>/_repo/cli-tools-shared/tests
```

Do not combine shared-package test paths and per-tool test paths in one pytest
invocation. Run the shared-package command above separately from the direct
per-tool pytest command so each suite resolves imports through its own uv
project.

**Expected-red test-first runs:** When a direct per-tool or shared-package
pytest run is intended to fail before implementation, do not run the bare
pytest command. Wrap it, capture the status and output, validate the expected
failure text, and exit `0` only for the intended red result. Expected red text
may be an assertion diff, exception type, or exact exception message. Unexpected
pass, unexpected failure text, or any other status remains a tool failure.
For `cli-tools-shared`, use the direct shared-package pytest command above in
the wrapper instead of a `$TOOL_NAME` project path.

When the red proof is a pytest assertion diff for a list or dict comparison, do
not key the wrapper only to directional pytest diff prose. Pytest can describe
the same cardinality bug as `Left contains one more item` or
`Right contains one more item` depending on operand order. Prefer a stable
domain-specific assertion message, exception type, or exact value from the diff;
if pytest prose is the only signal, require the test node name and accept both
directional variants.

**Table-output assertions:** Table output is display-only and may shorten cell
values for readability, while still showing every returned row. Do not assert
full untruncated URLs, UUIDs, descriptions, or other long scalar values in
Rich-rendered table stdout. Assert those full values against default JSON
output instead. For table stdout, assert stable headers, row presence, visible
labels, and the absence of row truncation; a cell-level ellipsis is acceptable
when the JSON output preserves the full value.

```bash
tmp_output="$(mktemp)"
if uv run --project <tool-dir> --with pytest python -m pytest <tool-dir>/tests/test_new_feature.py >"$tmp_output" 2>&1; then
  status=0
else
  status=$?
fi
cat "$tmp_output"
if [ "$status" -ne 0 ] && rg -q -F -- 'expected assertion, exception type, or exception message' "$tmp_output"; then
  printf '%s\n' 'EXPECTED_RED: test-first failure confirmed before implementation.'
  rm -f "$tmp_output"
  exit 0
fi
rm -f "$tmp_output"
if [ "$status" -eq 0 ]; then
  printf '%s\n' 'UNEXPECTED_PASS: test-first run passed before implementation.' >&2
  exit 1
fi
exit "$status"
```

**Harness unit monkeypatches:** When a harness unit test patches an imported
helper such as `run_cli_command`, patch the module object that owns the
reference used by the code under test (for example,
`monkeypatch.setattr(sys.modules[__name__], "run_cli_command", fake)`) or import
the module under test and patch that object. Do not use a bare string target
such as `"test_profiles.run_cli_command"`; pytest may collect the file under a
different module name, causing the real helper to execute.

**Command test fake lifecycle methods:** When a command test replaces a
production client or browser client with a fake, the fake must implement every
method the command can call on that object, including cleanup methods reached in
`finally` blocks such as `close()`. Missing lifecycle methods are test-fixture
bugs; add the method to the fake instead of changing the production cleanup
path.

**Command test fake helper signatures:** When a command test monkeypatches a
helper function, keep the fake signature compatible with the production call,
including keyword-only arguments such as `profile`. Capture and assert those
arguments in the test. A `TypeError` from a fake that omits a new keyword
argument is a test-stub bug, not an implementation bug.

**Direct Typer command calls:** When a unit test calls a `@app.command` function
directly instead of using `CliRunner`, pass every Typer argument and option
parameter explicitly, including newly added options whose CLI defaults are
`typer.Option(...)`. A direct Python call does not apply Typer's CLI default
conversion; omitted parameters can reach command logic as `typer.models.OptionInfo`
objects and make truthiness checks take the wrong branch. Prefer extracting a
pure helper for command logic and testing that helper when direct invocation
would require many CLI-only option defaults.

When a direct-called command helper is expected to exit via `raise typer.Exit(...)`,
assert `pytest.raises(typer.Exit)` or `pytest.raises(click.exceptions.Exit)`, not
`pytest.raises(SystemExit)`. `typer.Exit` is Click's `Exit` exception and is not a
`SystemExit`; `SystemExit` assertions belong around wrappers such as `run_app(app)`
that intentionally convert CLI execution into a process exit.

**Run the test script for structured JSON results:**

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name "$TOOL_NAME" [--command "$COMMAND"] [--verbose]
```

The script returns JSON with:
- `success`: boolean - whether all tests passed
- `summary`: object with passed/failed/skipped/errors counts
- `auth_required`: boolean - whether auth is needed
- `auth_command`: string - command to authenticate (if auth_required)
- `failures`: array - each failure with test_name, file, message, and pre-formatted todo

Display the summary to the user.

## Step 1.5: Handle Authentication Errors

If `auth_required` is true in the JSON response, complete testing is blocked until authentication is fixed:

1. **First, check actual auth status:**
   ```bash
   $TOOL_NAME auth status 2>/dev/null
   ```
   Parse the JSON output to check the `authenticated` field.

2. **If authenticated (true):** Investigate why the harness still considers auth incomplete. Do not treat the test run as complete until the harness passes.

3. **If NOT authenticated (false):** Use **AskUserQuestion** to ask:
   - Question: "The [tool-name] CLI is not authenticated. Integration tests require authentication. Would you like to authenticate now?"
   - Options:
     - "Yes, authenticate now" - User will run the auth command
     - "Skip integration tests" - Continue with only static analysis results

4. **If user chooses to authenticate:**
   - Tell the user: "Please run `[auth_command from JSON]` in your terminal, then let me know when complete."
   - Wait for user confirmation
   - Re-run the test script from Step 1

5. **If user chooses to skip:**
   - Report that complete testing is blocked by missing authentication
   - Do not present the harness as passing

### Live-auth blockers for new auth CLIs

New auth CLIs can complete static/source compliance without real credentials, but
they cannot complete live compliance until the required credential exists and
`auth status` returns an authenticated profile. Do not create fake credentials,
mark the CLI as no-auth, disable live tests, or edit validator expectations to
force a pass.

When credentials are unavailable, finish the code/static fixes that do not need
live auth, then report `LIVE_AUTH_BLOCKED` with:

- `auth_required: true`
- the `auth_command` from `test-cli-tool.sh`
- the exact `auth status` output or schema error
- the exact live execution tests that remain blocked

After credentials are stored through the CLI-tools secret manager or captured by
the CLI's own login flow, run the auth command and re-run `test-cli-tool.sh`
until `"success": true`.

## Step 2: Create Master Todo List (MANDATORY)

**You MUST use TaskCreate to create a comprehensive todo list immediately after reviewing test results.**

Create todos from:

1. **Failures array from JSON** - The script provides pre-formatted todos:
   ```json
   "failures": [
     {
       "todo": {
         "content": "Fix: ...",
         "activeForm": "Fixing ...",
         "status": "pending"
       }
     }
   ]
   ```
   Extract each `failures[].todo` and create a task for it.

2. **AI Review items** (for ALL CLIs) - One todo per check:
   - "AI Review: Verify --limit is API-level"
   - "AI Review: Verify --filter is exposed on list commands"
   - "AI Review: Verify --filter uses standard syntax"
   - "AI Review: Verify filter_translator implementation"
   - "AI Review: Verify exponential retry with jitter"
   - "AI Review: Verify all datetime/timestamp display uses format_local_time utility"
   - "AI Review: Verify NO silent error swallowing (CRITICAL)"
   - "AI Review: Verify auth status makes actual API call (CRITICAL)"
   - "AI Review: Verify auth uses cli_tools_shared (not custom auth module)"
   - "AI Review: Verify --force only clears ephemeral state (tokens/sessions), not static credentials"
   - "AI Review: Verify dry-run/preview commands that do not call live APIs run auth-free with isolated profile data"
   - "AI Review: Verify reusable credentials are routed through the CLI-tools secret manager, not any `.env` file"
   - "AI Review: Verify activity logging covers important code paths"
   - "AI Review: Verify browser CLI uses base class is_authenticated() (no custom auth-check methods)" *(browser CLIs only)*
   - "AI Review: Verify auth status/test use AuthVerifier (no duplicated browser/credential checking)" *(all auth CLIs)*

3. **Summary todo** (always last):
   - content: "Present final test summary and verify all todos complete"
   - status: "pending"

**SKIP tests do NOT require todos** - they indicate features not applicable to this CLI.

**EXCEPTION — these structural skips are NEVER acceptable. Treat them as failures and create fix todos:**
- **commands directory** — every CLI must have a `commands/` directory; skips citing "no commands directory found" mean the CLI is incomplete
- **list commands** — every CLI must expose at least one `list` command; skips citing "no list commands found" mean the CLI is incomplete
- **get commands** — every CLI must expose at least one `get` command; skips citing "no get commands found" mean the CLI is incomplete
- **filters.py** — every CLI must have `filters.py`; skips citing "filters.py not found" mean the CLI is incomplete
- **--filter on list commands** — every list command must expose `--filter`; skips or absences here mean the CLI is incomplete

## Step 3: Work Through Every Todo (MANDATORY)

**You MUST resolve every todo in order. No todo can remain pending when workflow completes.**

For each todo:
1. Mark as "in_progress" before starting work
2. Perform the required action (fix code, verify implementation, etc.)
3. Mark as "completed" only after action is fully done
4. If a fix requires re-testing, run the test script again and update todos accordingly

### AI Review Process

**CRITICAL: Every AI Review item applies equally to ALL CLI types (API, browser, wrapper). No exceptions.**

- Do NOT rationalize away a missing feature based on CLI type (e.g., "browser CLIs don't need activity logging" — WRONG, they need it MORE)
- Do NOT mark an AI Review item "completed" if the feature is absent. If it's missing, it's an ISSUE — create a fix todo.
- "N/A for this CLI type" is NEVER a valid completion note unless the review item explicitly says it's conditional (e.g., "browser CLIs only")
- Every review item exists because it was needed enough to codify. Treat each one as a hard requirement.

For AI Review todos:
1. Mark "in_progress"
2. Read the relevant source files (client.py, command files)
3. Verify the implementation matches the requirement
4. Mark "completed" with note: "Verified correct" or "ISSUE: [description]"
5. If ISSUE found, create a new fix todo

**CRITICAL datetime/timestamp display Requirements:**
ALL timestamps displayed in table output MUST use the `format_local_time()` or `format_local_time_only()` utility functions from parsers.py:
- Import: `from ..parsers import format_local_time, format_local_time_only`
- Use `format_local_time(timestamp)` for "Jan 13 14:30" format (date + time)
- Use `format_local_time_only(timestamp)` for "14:30:45" format (time only)
- NEVER display raw ISO timestamps (e.g., "2025-01-13T14:30:45Z") in table output
- All times MUST be converted to local timezone before display
- Check `main.py` plus any existing `commands/*.py` files for timestamp display

**CRITICAL --filter Requirements:**
ALL CLI tools MUST expose --filter flags on list commands, regardless of whether the underlying API supports filtering. The filter_translator MUST translate the standard CLI tool filtering syntax to whatever method is required:
- **API supports filtering**: Translate to API query parameters
- **API has limited filtering**: Translate supported filters to API params, apply unsupported filters client-side
- **API has no filtering**: Apply all filters client-side after fetching data

The absence of API-level filtering support is NOT an excuse to omit --filter from commands.

**CRITICAL auth status Requirements:**
The `auth status` command MUST make an actual API call to verify credentials are valid. Simply checking that credentials exist locally is NOT sufficient. The command must:
- Make a lightweight API call (e.g., get user info, list with limit=1)
- Return success only if the API call succeeds
- Distinguish between "not configured" and "configured but invalid"

**CRITICAL secret storage requirements:**
- Reusable human-supplied secrets (API keys, usernames, passwords, client secrets, long-lived bearer tokens) MUST be stored and retrieved through the CLI-tools secret manager
- Agents and docs MUST NOT instruct users to place those values in any `.env` file
- `.env` files are limited to non-secret config and CLI-managed runtime auth state

**CRITICAL dry-run/preview auth requirements:**
Commands whose `--dry-run` or preview mode only prints the intended request and
does not call a live API MUST be executable without saved credentials. Validate
the installed launcher with isolated profile data so shared command
registration cannot require auth before the command inspects `--dry-run`:

```bash
tmpdir="$(mktemp -d)"
XDG_DATA_HOME="$tmpdir" <tool> <command> --dry-run
rc=$?
rm -rf "$tmpdir"
exit "$rc"
```

If that check fails with missing credentials, fix the command credential
declaration or shared registration path instead of adding credentials to the
test environment. Use `COMMAND_CREDENTIALS = {"<command>": ["no_auth"]}` only
when the command code itself enforces auth before live mutations and keeps the
dry-run path auth-free.

### Fix Process

For fix todos:
1. Mark "in_progress"
2. Read relevant files to understand the issue
3. Make the necessary code changes
4. Run test script to verify the fix:
   ```bash
   <cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name "$TOOL_NAME" [--command "$COMMAND"]
   ```
5. Mark "completed" only if test now passes
6. If still failing, investigate further - do NOT mark complete

## Step 4: Re-test After Fixes

After making any code changes, re-run the test script:

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name "$TOOL_NAME" [--command "$COMMAND"] [--verbose]
```

If new failures appear:
- Create new todos for new failures
- Continue working through all todos

## Step 5: Verify All Todos Complete (MANDATORY)

Before presenting the final summary, verify:
- [ ] ALL todos are marked "completed"
- [ ] ZERO todos remain "pending" or "in_progress"
- [ ] All pytest tests pass (ZERO FAILED)
- [ ] All AI Review items verified

**If any todos remain incomplete, continue working. Do NOT proceed to summary.**

## Step 6: Present Final Summary

Only after ALL todos are complete, present:

```
## Test Results for [TOOL_NAME] CLI

### Pytest Results
- PASSED: X tests
- FAILED: 0 tests (all fixed)
- SKIPPED: X tests

### AI Review
- --limit: [Verified correct at API level]
- --filter exposed: [Verified present on all list commands]
- --filter syntax: [Verified standard field:op:value format]
- filter_translator: [Verified translates to API params / client-side filtering]
- Exponential retry: [Verified correct with jitter]
- Datetime display: [Verified all timestamps use format_local_time utility and display in local timezone]
- Error handling: [Verified NO silent error swallowing - all API errors surface to user]
- auth status: [Verified makes actual API call to validate credentials]
- --force ephemeral: [Verified --force only clears tokens/sessions, not static credentials]
- Dry-run preview auth: [Verified dry-run/preview commands that do not call live APIs run with isolated empty profile data]
- Secret storage: [Verified reusable credentials use secret manager instead of `.env`]
- Activity logging: [Verified get_activity_logger used in client and command files]
- Browser auth delegation: [Verified uses base class is_authenticated() — no custom is_logged_in/_ensure_logged_in] *(browser CLIs only)*

### Fixes Applied
1. [List each fix made]

### Work Complete
All compliance tests passing. All todos resolved.
```
</process>

<anti_patterns>
## Anti-Patterns (NEVER DO THESE)

**You cannot skip a failing test by assuming it's someone else's problem:**
- "This is probably a fixture/mock issue" -> INVESTIGATE the actual error
- "This isn't a CLI standards issue" -> The test framework disagrees, investigate why
- "Let me move on to AI review items" -> NO. Fix ALL failing tests FIRST
- "I'll mark this as complete because..." -> Tests are either PASSING or NOT. No exceptions.

**IF YOU THINK A FAILURE IS ENVIRONMENTAL:**
1. STILL create a todo for investigation
2. Trace the actual error (read logs, check fixtures, verify test setup)
3. PROVE it's environmental with evidence
4. Only then ask user how to proceed (fix environment OR skip with documented justification)

**You cannot dismiss an AI Review finding by rationalizing the CLI type:**
- "Browser CLIs don't need activity logging" -> WRONG. Fix it.
- "N/A — no API to retry against" -> Still needs error handling strategy. Fix it.
- "Timestamps are already human-readable" -> Still verify the display path. Fix if raw.
- "Low priority gap" -> There are no low priority gaps. Every AI Review item is a hard requirement.

**You cannot complete a "fix test" todo by deciding the test is wrong.**

To complete a fix todo, you must demonstrate ONE of:
- Test now passes (run pytest, show PASSED)
- Test was legitimately incorrect (show the spec/requirement change)
- Environment issue proven with evidence (user approved skip)

"I think it's probably X" is NEVER sufficient to complete a todo.
</anti_patterns>

<complex_issues>
## Handling Complex Issues

If an issue is too complex to fix in this session:

1. **Do NOT skip it** - You must still attempt to understand and document it
2. Create a detailed fix todo with:
   - Root cause analysis
   - Proposed solution approach
   - Files that need modification
3. Use AskUserQuestion to ask: "This fix requires [X]. Should I proceed or create a detailed plan?"
4. Options:
   - "Proceed with fix" - Continue fixing
   - "Create remediation plan" - Invoke `/create-plan` with detailed context
5. **Either way, the todo must be resolved** - either fixed or planned
</complex_issues>

<configuration>
Test behavior is controlled by `<cli-tools-root>/_repo/skills/cli-tool/tests/cli_test_config.toml`

Edit this file to:
- Change Python version requirement
- Adjust command timeouts
- Configure exclusions
- Set max nesting depth per CLI
- Define parameter fixtures for commands that require IDs
</configuration>

<fixtures>
## Test Fixtures for Parameterized Commands

Some commands require parameters (database IDs, page IDs, etc.) to execute. Without fixtures, tests will skip with:
```
Command requires positional argument. Fix: Add fixture to tests/fixtures/<cli-name>.json
```

### Step 1: Create Fixture File

Create `<cli-tools-root>/_repo/skills/cli-tool/tests/fixtures/<cli-name>.json`:

```json
{
  "database_id": "abc123-def456-...",
  "page_id": "ghi789-jkl012-...",
  "app_id": 12345678
}
```

### Step 2: Add Parameter Mapping

Add mapping in `tests/cli_test_config.toml`:

```toml
[cli_specific.<cli-name>.param_fixtures]
# For flag-based parameters (--database-id VALUE):
"database page list" = { "--database-id" = "database_id" }
"pages blocks list" = { "--page-id" = "page_id" }

# For positional arguments (command VALUE):
# Use "_pos1", "_pos2", etc. for positional args in order
"item list" = { "_pos1" = "app_id" }
```
</fixtures>

<browser_cli_features>
## Browser CLI Template Features

Browser CLIs should be nearly identical to the `_repo/skills/cli-tool/templates/browser/` template. The template provides:

### Authentication System
- **`auth.py`** - Complete auth detection and session management
- **`config.py`** - Auth cookie names, selectors, URL patterns, timeout settings

### Named Profile Support
- Multiple profiles for multi-account scenarios
- `--profile/-p` flag on all auth commands

### Auth Commands
- `auth login [--force] [--profile NAME]` - Interactive login with auto-monitoring
- `auth status [--table] [--profile NAME]` - Check auth status
- `auth test [--table] [--verbose] [--profile NAME]` - Browser-based verification
- `auth logout [--force] [--profile NAME]` - Clear sessions

**Site-specific customization** should only be in:
1. `_custom_auth_test()` callback in client.py
2. Environment variables for auth indicators
3. `_get_critical_cookie_names()` in auth.py
</browser_cli_features>

<success_criteria>
Testing is complete ONLY when:
- [ ] pytest shows ZERO FAILED tests
- [ ] ALL AI Review items verified correct
- [ ] CLI has a `commands/` directory (mandatory — no exceptions)
- [ ] CLI has at least one `list` command (mandatory — no exceptions)
- [ ] CLI has at least one `get` command (mandatory — no exceptions)
- [ ] CLI has `filters.py` (mandatory — no exceptions)
- [ ] ALL list commands expose --filter flag (no exceptions)
- [ ] filter_translator properly implements translation (API or client-side)
- [ ] ALL timestamps displayed use format_local_time utility (local timezone)
- [ ] NO silent error swallowing - all API errors must surface to user
- [ ] auth status makes actual API call to validate credentials
- [ ] Activity logging covers important code paths (get_activity_logger used)
- [ ] ALL todos marked "completed"
- [ ] Final summary presented

**There is no "review later" option. All work must be completed or formally planned.**
</success_criteria>
