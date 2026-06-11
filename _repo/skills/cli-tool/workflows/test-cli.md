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

This only proves the harness collects. It is not a replacement for CLI-specific validation through `test-cli-tool.sh --cli-name "$TOOL_NAME"`.

**Targeted harness execution:** If you run a direct `pytest -k ...` selection
against harness tests and the selection includes any CLI-dependent test, pass
`--cli-name "$TOOL_NAME"`. Use `--force` only for batch or collect-only harness
checks where CLI-dependent tests are allowed to skip.

**Direct per-tool pytest execution:** When running a tool's own tests directly,
use that tool's uv project environment and add pytest to the run environment.
Do not run `PYTHONPATH=. pytest`, `python -m pytest`, or another ambient
interpreter from the tool directory; shared dependencies such as
`cli_tools_shared` are resolved by the uv project declared in the tool's
`pyproject.toml`.

```bash
uv run --project <cli-tools-root>/$TOOL_NAME --with pytest python -m pytest <cli-tools-root>/$TOOL_NAME/tests
```

**Harness unit monkeypatches:** When a harness unit test patches an imported
helper such as `run_cli_command`, patch the module object that owns the
reference used by the code under test (for example,
`monkeypatch.setattr(sys.modules[__name__], "run_cli_command", fake)`) or import
the module under test and patch that object. Do not use a bare string target
such as `"test_profiles.run_cli_command"`; pytest may collect the file under a
different module name, causing the real helper to execute.

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
   - "AI Review: Verify reusable credentials are routed through the CLI-tools secret manager, not any `.env` file"
   - "AI Review: Verify activity logging covers important code paths"
   - "AI Review: Verify browser CLI uses base class is_authenticated() (no custom auth-check methods)" *(browser CLIs only)*
   - "AI Review: Verify auth status/test use AuthVerifier (no duplicated browser/credential checking)" *(all auth CLIs)*

3. **Summary todo** (always last):
   - content: "Present final test summary and verify all todos complete"
   - status: "pending"

**SKIP tests do NOT require todos** - they indicate features not applicable to this CLI.

**EXCEPTION: --filter is NEVER skippable.** All list commands must expose --filter regardless of API support. If tests skip filter checks, investigate why and ensure --filter is implemented.

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
