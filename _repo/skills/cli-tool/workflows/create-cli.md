<required_reading>
Before starting, read these references as needed:
- `references/templates.md` - Template structures and customization points
- `references/output-standards.md` - Output streams, format rules, list command requirements
- `references/secrets.md` - CLI-tools secret manager rules
- `references/auth-standards.md` - Authentication standards by credential type
- `references/config-standards.md` - Configuration and .env standards
- `references/command-standards.md` - Command naming, options, exit codes
- `references/model-standards.md` - Pydantic model standards
- `references/infra-standards.md` - Repository, documentation, symlinks
- `references/filtering.md` - Filtering architecture (for API CLIs)
</required_reading>

<process>
## Step 1: Gather Requirements

Ask the user (if not already provided):

1. **Service/API**: What service or API will this CLI interact with?
2. **CLI Type**:
   - `api` - REST API client
   - `browser` - Web automation (only if no API exists)
   - `wrapper` - Wrapping an existing CLI tool
3. **Base URL** (for api/browser): What is the API base URL or website URL?
4. **CLI Command** (for wrapper): What is the underlying CLI command name?
5. **Authentication**: How does authentication work? (API key, OAuth, etc.)
6. **Key Resources**: What are the main resources/commands needed?

## Step 2: Investigate Communication Methods (MANDATORY)

**BEFORE asking the user about CLI type, you MUST investigate in this order:**

### 2.1 Search for Public API

First, search for official API documentation:

```
1. Web search: "<service-name> API documentation"
2. Web search: "<service-name> developer API"
3. Web search: "<service-name> REST API"
4. Check for developer portal (e.g., developers.<service>.com)
```

If a public API exists with documentation and the API/auth path is currently
usable by Adam, use **`api` type**.

**API availability gate:** Documentation alone is not enough. If the official
API, SDK, developer program, or required credential is deprecated, unsupported,
invite-only, closed to new integrations, unavailable to new users, or usable
only by accounts that already possess a legacy token/key, stop before
scaffolding. Report the limitation to the user and ask whether they already have
the required usable credential. If they do, continue with the API path and note
that live validation depends on that credential. If they do not, ask whether to
proceed with a browser-automation CLI instead.

**AUTO-PROCEED:** If Step 2.1 determines no consumer-accessible API exists, proceed directly to Step 2.2 without waiting for user confirmation. The decision tree in Step 2.4 is deterministic -- do not present intermediate findings or options between Steps 2.1 and 2.2. Report consolidated findings only after completing all applicable discovery steps (2.1 through 2.3).

### 2.2 Discover Internal/Hidden APIs

If no public API exists, spawn the `ui-web-test-engineer` agent to explore the authenticated web interface and capture internal API calls.

**Include the base URL and all URL patterns discovered in Step 2.1 directly in the agent prompt. Never re-ask the user for information gathered during earlier steps.**

**Invoke the agent with this prompt:**

```
Explore <service-url> to discover internal/hidden REST APIs.

1. Follow `references/secrets.md` before asking Adam for CLI credentials.
2. If credentials are not in the secret manager, use the `lastpass` CLI tool to look them up. 
3. If not found in LastPass, use browser automation to inspect the service's login page for third-party authentication providers (e.g., Google, Microsoft). If supported, ask Adam if he would like to use one.
4. Ask Adam for manual credentials only if they cannot be found in the secret manager, LastPass, and third-party auth is unavailable or declined. Store newly provided reusable CLI credentials using `references/secrets.md`.
5. Navigate to <service-url> and authenticate using those credentials
6. Systematically explore the authenticated interface:
   - Visit every major section/page
   - Interact with data-heavy views (lists, dashboards, detail pages)
   - Perform CRUD-like actions (create, edit, delete) where safe to do so
   - Use search, filtering, sorting, and pagination features
7. Monitor ALL network requests (XHR/Fetch) for JSON API endpoints. For each discovered endpoint, document:
   - URL pattern (e.g., /api/v1/items?page=1&limit=50)
   - HTTP method (GET, POST, PUT, DELETE, PATCH)
   - Request headers (especially Authorization, X-API-Key, cookies, CSRF tokens)
   - Request body (for POST/PUT/PATCH)
   - Response body structure (field names, types, nesting)
   - Authentication mechanism (Bearer token, session cookie, API key header, etc.)
8. **BACKUP PLAN FOR BOT PROTECTION:** If the site blocks your automation with an interstitial bot-check (e.g. Datadome, PerimeterX "Almost there..."), do NOT give up. Instead, use the `run_command` tool to launch the user's REAL system Chrome binary in the background without stealing focus using `open -n -g`:
   ```bash
   open -n -g -a "Google Chrome" --args --remote-debugging-port=9222 --no-first-run --no-default-browser-check --user-data-dir=$(mktemp -d)
   ```
   Wait a few seconds for it to start listening, then write a temporary Python script that uses `playwright` to connect to `p.chromium.connect_over_cdp("http://127.0.0.1:9222")`. Because this uses the legitimate system Chrome executable instead of Playwright's Chromium, it reliably bypasses bot detection. Execute the script to perform the login, capture the required endpoint traces, and finally terminate the background Chrome process using `lsof -i :9222 -t | xargs kill -9`.
9. Identify patterns across endpoints:
   - Base URL prefix (e.g., /api/v2/)
   - Pagination style (offset, cursor, page number)
   - Error response format
   - Rate limiting headers
8. Produce your findings as a structured JSON report with an "endpoints" array, each entry containing: url, method, headers, requestBody, responseBody, authMechanism, notes
```

**Using the agent results:**

- If the agent discovers usable JSON API endpoints → use **`api` type** with those endpoints
- Feed the discovered endpoint catalog into Step 2.5 (Implementation Planning) as the API Discovery Results
- Use the documented auth mechanism to select the correct `--auth-type` in Step 3
- If the agent finds no XHR/JSON endpoints (all server-rendered), proceed to Step 2.3

### 2.3 Browser Automation (Last Resort)

Only if Steps 2.1 and 2.2 yield no usable APIs:

```
Browser automation is appropriate when:
- Service has NO public or internal REST/JSON APIs
- All data is rendered server-side (no XHR calls)
- Authentication requires complex browser interactions (CAPTCHAs, MFA)
```

Do not auto-select **`browser` type**. Stop and ask Adam:

```
No usable public or internal API path is available for this action. Should I make this command browser-driven?
```

Use **`browser` type** only after explicit approval.

### 2.4 Decision Tree

```
Is there an existing CLI tool for this service?
├── YES → Use "wrapper" type
└── NO → Did you find a public REST/JSON API that is currently usable by Adam? (Step 2.1)
    ├── YES → Use "api" type
    ├── LEGACY/CLOSED AUTH ONLY → Ask whether Adam has the required credential; otherwise ask whether to use "browser" type
    └── NO → Did you discover internal APIs? (Step 2.2)
        ├── YES → Use "api" type (with discovered endpoints)
        └── NO → STOP: ask whether Adam wants a browser-driven command
```

**Report your findings to the user** before proceeding:
- What investigation you performed
- What APIs (if any) you discovered
- Your recommended CLI type with justification
- If no usable API exists, the explicit browser-driven approval question above

### 2.4.5 Safe Repo Example Inspection

When comparing nearby CLIs or tests during discovery or planning, do not guess
optional paths such as `<other-cli>/tests/test_cli.py` or
`<cli-tools-root>/_repo/skills/<example>-cli`. First discover existing service
skill directories from the verified `<cli-tools-root>/_repo/skills` root, then
inspect only discovered paths. Do not run `find`, `rg`, `sed`, `cat`, `nl`,
`wc`, `head`, `tail`, `grep`, or similar with a guessed service-skill example
path. If a preferred example skill is absent, report that absence and choose
another discovered example or continue without one.
This is the cli-tools-specific application of the file-operand rule in
`/Users/adam/Dropbox/.agents/skills/agent-expert/references/global-standards.md`.

Keep repository inspection searches line-local and literal unless multiline
matching is deliberately required. Do not compose one complex `rg` regex with
alternation and `\n` escapes for mixed code-shape checks; use separate `rg -F`
probes with shaped no-match handling instead. Use `rg -U` only when the search
must match across real line breaks, and state that intent before running it.

## Step 2.5: Implementation Planning

**For CLIs with 4+ resource groups, complex auth (OAuth + browser), or significant API investigation:**
Run `/create-plan` before proceeding.

**For simpler CLIs (≤3 commands, single auth type):**
Present the command tree inline and get user approval before proceeding.

```
/create-plan <cli-name> CLI implementation
```

The plan MUST document:

### API Discovery Results
- Available endpoints and their purposes
- Authentication method (API key, OAuth, session)
- Rate limits and pagination patterns
- Response formats and error structures

### Command Structure Design (REQUIRES USER APPROVAL)

**You MUST present a complete command tree and get explicit user approval before proceeding.**

Present the proposed CLI structure in this format:

```
<cli-name>
├── auth
│   ├── login       - Authenticate with the service
│   └── status      - Check authentication status
├── <resource1>
│   ├── list        - List all <resource1> (with --filter, --limit, --table)
│   ├── get <id>    - Get a specific <resource1>
│   ├── create      - Create a new <resource1>
│   ├── update <id> - Update a <resource1>
│   └── delete <id> - Delete a <resource1>
├── <resource2>
│   └── ...
└── <special-commands>
```

For each command group, document:
- Resource groups (e.g., items, users, orders)
- CRUD operations per resource
- Filtering capabilities per endpoint
- Special operations beyond CRUD (export, import, share, etc.)

**After presenting the command tree, ASK THE USER:**
- "Does this command structure cover your needs?"
- "Are there any commands you want added or removed?"
- "Any naming preferences for commands or groups?"

**DO NOT proceed until the user confirms the command structure.**

### Output Data Design
- Exact fields each command returns
- Any derived fields the parser/client must create
- Whether local models earn their cost through validation, polymorphism, or serialization
- Relationships that must be visible in command output

### Implementation Risks
- Complex authentication flows (OAuth refresh, MFA)
- Non-standard API patterns
- Missing or incomplete documentation
- Pagination edge cases

**Why this is mandatory:** Discovering API limitations after creating the CLI structure wastes significant time. Planning prevents backtracking and ensures you understand the full scope before writing code.

**DO NOT proceed to Step 3 until the plan is approved.**

## Step 3: Run new-cli-tool Script

Execute the appropriate command:

```bash
# For API CLI (default: API key auth):
<cli-tools-root>/_repo/skills/cli-tool/scripts/new-cli-tool \
  --name <name> \
  --type api \
  --base-url <url> \
  --description "<description>" \
  --docs-url <docs-url>

# For API CLI with Personal Access Token auth:
<cli-tools-root>/_repo/skills/cli-tool/scripts/new-cli-tool \
  --name <name> \
  --type api \
  --base-url <url> \
  --auth-type personal_access_token \
  --description "<description>" \
  --docs-url <docs-url>

# For Browser CLI:
<cli-tools-root>/_repo/skills/cli-tool/scripts/new-cli-tool \
  --name <name> \
  --type browser \
  --base-url <url> \
  --description "<description>"

# For Wrapper CLI:
<cli-tools-root>/_repo/skills/cli-tool/scripts/new-cli-tool \
  --name <name> \
  --type wrapper \
  --cli-command <cmd> \
  --description "<description>" \
  --docs-url <docs-url>
```

**Script options:**
- `--auth-type` - Authentication type (repeatable for multiple types, AND semantics): `none`, `api_key` (default), `personal_access_token`, `oauth`, `oauth_authorization_code`, `username_password`, `browser_session`. Use `none` to skip auth scaffolding entirely. Example: `--auth-type api_key --auth-type browser_session`
- `--no-venv` - Skip virtual environment creation
- `--no-aliases` - Skip symlink/PowerShell setup
- `--no-install` - Skip installation only when you are deliberately leaving the CLI uninstalled for a scaffold-only artifact; do not use it for a completed wrapper CLI.

## Step 3.4: Wrapper Upstream CLI Provisioning Gate

For wrapper CLIs, the official upstream binary named by `CLI_COMMAND` is part of
the wrapper's implementation contract. The wrapper is not usable until that
binary is installed or bootstrapped by the wrapper creation/install path and
`<cli-command> --help` exits `0`.

If `new-cli-tool` cannot install the upstream binary because the official
distribution is not Homebrew (for example npm, pipx, uv, or a vendor installer),
add the official install/bootstrap path to the wrapper source or repo-owned
install workflow before reporting the wrapper complete. Do not tell Adam to
install the wrapped CLI manually as the normal completion state.

Missing `CLI_COMMAND` is an implementation blocker, not a live API smoke-test or
API-key-auth blocker. API-key auth may remain user-configured only after the
official upstream binary is present and executable.

## Step 3.5: Post-Creation Validation

Run the validation script to confirm scaffolding succeeded:

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/validate-cli-tool.sh <name>
```

Verify all checks pass in the JSON output. If any check fails, investigate and fix before proceeding.

## Step 4: Define Output Shape First

Navigate to `<cli-tools-root>/<name>/` and define the data shape
each external command must print. Start from the documented command/output
contract, not from a template directory.

- Use plain dict records when parsed/API data can flow directly to output.
- Use parser/client code to add required derived fields such as stable IDs.
- Use local Pydantic models only when validation, polymorphism, or serialization
  removes real complexity.
- Delete empty or one-resource `models/` directories after simplification.

```python
def normalize_item(raw: dict) -> dict:
    return {
        "id": raw["id"],
        "name": raw["name"],
        "status": raw["status"],
    }
```

## Step 4.5: Full API Response Output (MANDATORY)

**For API-based CLIs, return ALL data the API provides.** Do not filter, omit, or selectively display API response fields.

- Include every field from API responses in CLI output
- Never hardcode a subset of "useful" fields - let the user filter with jq if needed
- If an API returns 20 fields, the CLI should output all 20 fields
- This ensures the CLI remains useful as APIs evolve and prevents data loss

## Step 5: Customize Client and Commands

**For API type:**
1. `<name>_cli/client.py`:
   - Implement API methods that return records matching the command contract
   - Add authentication logic
   - Implement server-side filtering where API supports it

```python
def list_items(self, limit: int = 100) -> list[dict]:
    response = self._make_request("GET", "/items", params={"limit": limit})
    return [normalize_item(item) for item in response]
```

2. `<name>_cli/config.py`:
   - Verify environment variable names
   - Add any additional config options

3. `<name>_cli/main.py` by default:
   - Keep the initial resource group in `main.py`
   - Implement `--table`/`-t` option on all list commands
   - Implement `--filter`/`-f` option on all list commands
   - Implement `--limit`/`-l` option on list commands
   - Split into `commands/<group>.py` only when multiple groups justify it

**For API type with `browser_session` auth:**
If you scaffolded an `api` type but used `--auth-type browser_session` (e.g., internal APIs requiring browser cookies), the API template does NOT provide `BrowserAutomation` by default. You MUST manually:
1. `<name>_cli/browser.py`: Create this file and define a `BrowserAutomation` subclass.
2. `<name>_cli/config.py`: Import your `BrowserAutomation` subclass and implement `def get_browser(self):`.
3. `<name>_cli/client.py`: Ensure client uses the browser automation session for auth/requests.
Failure to do this will cause `test-cli-tool.sh` browser automation checks to fail.

**For Wrapper type:**
1. `<name>_cli/client.py`:
   - Map wrapper methods to underlying CLI commands
   - Parse output and return records matching the command contract
   - Implement auth_login() and auth_status() methods

2. `<name>_cli/parsers.py`:
   - Add custom parsers for each output format
   - Handle different output patterns from underlying CLI

**For Browser type:**
1. **Capture real DOM data FIRST** (MANDATORY before writing any parsers):
   ```bash
   # Ensure browser is open and authenticated
   <name> auth login
   # In a debug script or REPL, drive the page via BrowserAutomation and
   # call page.evaluate("document.documentElement.outerHTML") (or a more
   # targeted DOM query) to capture the real HTML / structured data.
   # Examine the actual structure, THEN write parsers/extractors.
   ```

2. `<name>_cli/parsers.py`:
   - Normalize structured data returned from in-page JS extractors
     (`page.evaluate(...)`) against the REAL captured DOM (never guess).
   - Validate each parser against actual captured data.

3. `<name>_cli/client.py`:
   - Use the BrowserAutomation subclass for navigation + extraction (no
     direct browser binary subprocess calls, no direct BrowserHarnessService
     imports — only `self.config.get_browser()`).
   - **Return models** from all methods

## Step 6: Update .env.example

Add all required environment variable names. `.env.example` documents shape only; it must not contain real values. Reusable CLI credentials are governed by `references/secrets.md` and must not be written into `.env.example` or any other `.env` file by an agent or human.

```bash
# API type example (shape only)
API_KEY=
<NAME>_BASE_URL=https://api.example.com

# OAuth example (shape only; secret values come from the secret manager)
CLIENT_ID=
CLIENT_SECRET=
<NAME>_ACCESS_TOKEN=
<NAME>_REFRESH_TOKEN=
<NAME>_TOKEN_EXPIRES_AT=
```

Document the boundary anywhere credentials are mentioned: reusable human-supplied secrets come from `<cli-tools-root>/_repo/_secret-manager/secrets.sh`; only CLI-managed runtime auth state belongs in profile `.env` files.

## Step 6.5: Code Simplification Pass (Post-Implementation)

After initial implementation is complete, run `/debloat` to review all new code for reuse, quality, and efficiency issues.

Invoke the `debloat` skill on the CLI directory.

**If `/debloat` identifies issues, fix them before proceeding.** Re-run `validate-cli-tool.sh` after any fixes to confirm scaffolding is still valid.

## Step 7: Test the CLI

### 7.1 Verify installation

```bash
<name> --version
<name> --help
```

### 7.2 Verify authentication (BLOCKING GATE)

**Browser-session CLIs (`--auth-type browser_session` / `MANUAL_LOGIN=True`):**
The agent CANNOT run `auth login` automatically — it opens a GUI browser window. Do NOT attempt to run it. Instead:
1. Tell the user: "Please run `<name> auth login` in your terminal and complete the sign-in. Let me know when done."
2. Wait for explicit confirmation before continuing.
3. Run `<name> auth status` and check that `authenticated: true` before proceeding.
4. If not authenticated, repeat — do not proceed to Step 7.3 or Step 8 until confirmed.

**All other CLIs:**
```bash
<name> auth status
```
If not authenticated, ask the user to provide credentials or run the relevant auth command, then verify `auth status` passes.

**Re-auth check:** If Step 8 testing takes longer than ~30 minutes, re-run `<name> auth status` before continuing — browser sessions expire and a mid-test 403 is not a pipeline bug.

### 7.3 Smoke test a live command

```bash
# Test a list command
<name> <resource> list --table
<name> <resource> list | jq '.'
```

## Step 8: Run test-cli-tool (MANDATORY - ZERO FAILURES ALLOWED)

Execute the test script to get structured JSON results:

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name <name>
```

The script returns JSON with `success`, `summary`, `auth_required`, `failures[]` (with pre-formatted todos), and `raw_output`.

**⛔ ABSOLUTE REQUIREMENT: ALL test failures MUST be fixed before proceeding.**

- **Zero tolerance for test failures** - Do not skip, ignore, or rationalize any failure
- **Fix every single issue** - Each failure in the JSON output must be addressed
- **Re-run until all pass** - Execute the script repeatedly until `"success": true`
- **Warnings are acceptable** - Only failures must be fixed; warnings may be addressed later
- **No exceptions for "wrapper CLIs" or "passthrough patterns"** - If the test expects an option, implement it
- **No skipping structural tests** - ALL command structure tests are required to run and PASS for all CLIs, including browser CLIs. The only exception is `test_install.py` which may be skipped for non-wrapper CLIs. If tests are being skipped because you have not implemented full commands (e.g., missing `main.py`, `commands/`, `list` operations, or `get` operations), you must fully implement the CLI's command structure until those tests execute and PASS. A skipped test due to missing command structure is equivalent to a failure.
- **Wrapper upstream binary failures are implementation failures** - Install or bootstrap the official `CLI_COMMAND` dependency before reporting completion
- **Auth-required CLIs without credentials** - Follow `workflows/test-cli.md` live-auth blocker handling. Static/source work can be complete, but live compliance remains `LIVE_AUTH_BLOCKED` until real credentials authenticate.

**Common failures and fixes:**
| Failure | Fix |
|---------|-----|
| Missing `--table/-t` | Add: `table: bool = typer.Option(False, "--table", "-t", help="Display as table")` |
| Missing `--limit/-l` | Add: `limit: int = typer.Option(100, "--limit", "-l", help="Maximum results")` |
| Missing `--filter/-f` | Add: `filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter")` |
| Missing `--properties/-p` | Add: `properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Fields")` |
| Missing `--force/-F` on auth login | Add force flag to re-authenticate |
| auth status format | Output must use the shared profile shape with `profiles[].authenticated` and `profiles[].credential_types` |
| Command not in README | Add command documentation with examples |

**DO NOT proceed to Step 9 until test-cli-tool.sh shows zero failures.**

## Step 9: AI Review (MANDATORY for API CLIs)

**After test-cli-tool passes, you MUST perform the AI review.** Read `<name>_cli/client.py`, `<name>_cli/main.py`, and any existing `<name>_cli/commands/*.py`, then verify:

### 9.1 --limit Implementation

**CORRECT**: Limit passed to API request
```python
params = {"limit": limit}
response = self._make_request("GET", "/items", params=params)
```

**WRONG**: Client-side slicing
```python
response = self._make_request("GET", "/items")
return response["items"][:limit]  # BAD!
```

### 9.2 --filter Implementation

**CORRECT**: Filters translated to API parameters
```python
api_params = filter_map.to_api_params(filters)
params.update(api_params)
response = self._make_request("GET", "/items", params=params)
```

**WRONG**: Client-side filtering after fetch
```python
response = self._make_request("GET", "/items")
items = apply_filters(response["items"], filters)  # Only acceptable as fallback!
```

### 9.3 No Dedicated Filter Commands

**FORBIDDEN**: Any of these patterns
```python
@app.command("filter")  # NO!
def filter_items(...):
    ...
```

**REQUIRED**: Filtering via --filter on list commands only
```python
@app.command("list")
def list_items(
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f"),
):
    ...
```

### 9.4 Exponential Retry Implementation

**Required characteristics:**
- Formula: `base_delay * 2^attempt` with optional jitter
- Only retries: 429, 500, 502, 503, 504, connection errors, timeouts
- Honors `Retry-After` header
- Configurable: max_retries, base_delay, max_delay, jitter

### 9.5 Lean Contract Verification

Verify that:
- Command names, options, and stdout shape match the README and tests
- Internal data representation is the smallest clear shape that preserves output
- Direct dependencies are used by runtime package code
- Metadata-only command modules contain only `COMMAND_CREDENTIALS`
- Browser subclasses contain declarative hook constants only
- README, `.env.example`, and auth guidance route reusable human-supplied secrets to the CLI-tools secret manager instead of any `.env` file

### 9.6 Report AI Review Findings

Present findings in this format:
```
### AI Review Results
- --limit: [Correctly implemented at API level / INCORRECTLY client-side]
- --filter: [Correctly implemented at API level / INCORRECTLY client-side / Not yet implemented]
- Dedicated filter commands: [None found / VIOLATION: found filter command]
- Exponential retry: [Correctly implemented / Missing or incorrect]
- Lean architecture: [Smallest clear implementation / VIOLATION: unused helpers, models, or dependencies]
- Secret storage guidance: [Reusable credentials routed to secret manager / VIOLATION: guidance stores secrets in `.env`]
```

**Fix any issues found before proceeding.** Re-run test-cli-tool.sh after fixes.

## Step 9.5: Final Code Simplification

Run `/debloat` one final time on all changes before committing.

Invoke the `debloat` skill on the CLI directory.

**If issues are found:**
1. Fix them
2. Re-run `test-cli-tool.sh` to confirm zero failures
3. Only proceed when both `/debloat` is clean and tests pass

## Step 9.7: LastPass Credential Discovery And Live Auth Smoke

After the CLI implementation is created, installed, and testable, complete this
step before `cli_tools.md`, CLI skill generation, commits, or final completion.
For new CLI creation, an unauthenticated profile is a required user checkpoint,
not a completion blocker to report and move past. Prompt Adam to authenticate
once, save the auth profile through the CLI, and continue only after the saved
profile is authenticated and live CLI tests pass.

### 9.7.1 Classify The Auth Boundary

- API and browser service CLIs with any auth type other than `none`: this step
  is mandatory.
- Wrapper CLIs: skip this step when the underlying CLI owns service auth. Record
  `SKIPPED_WRAPPER_AUTH: underlying CLI owns auth`. If the wrapper itself
  persists a separate CLI-tools auth profile, this step is mandatory for that
  wrapper profile.
- CLIs with `--auth-type none`: record `SKIPPED_NO_AUTH`.

### 9.7.2 Search LastPass With The `lastpass` CLI

Use the repo-owned `lastpass` CLI syntax from
`<cli-tools-root>/_repo/skills/lastpass-cli/usage.json`. Do not call `lpass`,
parse LastPass exports, use the browser vault UI, or use any ad hoc LastPass
helper.

Verify LastPass auth first:

```bash
lastpass auth status
```

Search for the service credential entry without printing secret values:

```bash
lastpass items list --filter "name:like:%<service-name>%" --properties id,name,username,url --table
```

If no unambiguous LastPass entry contains the credential values required by the
new CLI, stop with `LIVE_AUTH_BLOCKED: LastPass has no usable <service-name>
credentials for <needed credential types>` and do not mark CLI creation
complete.

### 9.7.3 Store Reusable Credentials In The CLI-Tools Secret Manager

Retrieve only the exact values needed by the new CLI's auth flow. Do not print
secrets, do not use `lastpass items get --show-password`, and do not write raw
reusable credentials to `.env`, `.env.example`, or
`authentication_profiles/<profile>/.env`.

Use the value-specific LastPass commands and immediately store each reusable
credential through `references/secrets.md`:

```bash
SECRET_VALUE="$(lastpass items username "$entry_id")"
printf '%s' "$SECRET_VALUE" | <cli-tools-root>/_repo/_secret-manager/secrets.sh set --tool <name> --type username
unset SECRET_VALUE

SECRET_VALUE="$(lastpass items password "$entry_id")"
printf '%s' "$SECRET_VALUE" | <cli-tools-root>/_repo/_secret-manager/secrets.sh set --tool <name> --type <credential-type>
unset SECRET_VALUE
```

Choose the secret-manager `<credential-type>` from the CLI's auth contract, for
example `password`, `api-key`, `personal-access-token`, `client-id`, or
`client-secret`. For token-style LastPass entries, treat the LastPass password
field as the token value unless the service's documented credential shape
requires a separate exact field.

Reusable raw credentials belong in the CLI-tools secret manager. CLI-managed
runtime auth state belongs in `~/.local/share/cli-tools/<name>/authentication_profiles/<profile>/`.
`.env.example` remains shape-only.

### 9.7.4 Create Or Verify The CLI Auth Profile

Use the new CLI's own auth/profile commands. Do not create profile files by hand.

```bash
<name> auth profiles list --properties name,active,auth_type
<name> auth profiles create <profile-name>
<name> auth login --profile <profile-name>
<name> auth status --profile <profile-name>
```

Create the profile only when the CLI's own profile list proves it is absent. For
multi-credential CLIs, authenticate the required credential type explicitly when
needed:

```bash
<name> auth login --profile <profile-name> --credential-type <credential-type>
```

Feed values retrieved from the CLI-tools secret manager into the CLI's normal
non-echoing auth flow or first-class auth options without printing them. If the
CLI auth flow requires browser login, MFA, consent, or other one-time user
action, prompt Adam to complete that authentication once in the opened browser
or terminal. You are not done until the CLI has saved that authenticated profile
and `<name> auth status --profile <profile-name>` confirms the shared
authenticated profile JSON. Stop with `LIVE_AUTH_BLOCKED: <name> auth
login/status failed for <profile-name>` only when the auth path cannot create a
saved profile after Adam has had the opportunity to authenticate, and preserve
the non-secret failure output.

### 9.7.5 Run Live Read-Only Smoke Commands

After `<name> auth status --profile <profile-name>` reports the shared
`profiles[].authenticated` JSON shape as authenticated, run at least one live
read-only command against the service. Use a command from the approved command
tree, such as a `list`, `get`, `search`, or `status` command. Do not count
`--help`, unit tests, compliance tests, cache-only output, or local parser checks
as the live smoke.

```bash
<name> <resource> list --limit 1
```

The read-only smoke command must complete successfully against the live service.
If live auth or the smoke command cannot be completed, report the exact
`LIVE_AUTH_BLOCKED` reason and do not mark CLI creation complete.
Then run the repo CLI testing tool against the live authenticated profile:

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name <name>
```

The live test run must pass with zero failures before CLI creation is complete.

## Step 10: Update cli_tools.md

Add the new CLI to `<cli-tools-root>/_repo/docs/cli_tools.md`:

1. Find the CLI tools table
2. Add a new row in alphabetical order:

```markdown
| `<name>` | <Description> |
```

Example:
```markdown
| `stripe` | Stripe payments API - manage customers, charges, subscriptions |
```

## Step 11: Create CLI Tool Skill (Auto)

After the CLI tool is fully created and tested, automatically create its associated CLI tool skill by invoking:

```
/create-cli-tool-skill <name>
```

This generates a repo-owned skill at `<cli-tools-root>/_repo/skills/<name>-cli/` with `SKILL.md` and `usage.json`, enabling natural language command discovery for the new CLI.

**Do not ask the user** — this step runs automatically as part of CLI creation.
</process>

<success_criteria>
CLI creation is complete when:
- [ ] `/create-plan` executed and plan approved by user
- [ ] new-cli-tool script executed successfully
- [ ] CLI installs and runs (`<name> --version` works)
- [ ] `<name> --help` shows all commands
- [ ] `<name> auth status` works (outputs shared profile JSON) -- when auth commands are present
- [ ] List commands have `--table`, `--filter`, `--limit`, `--properties` options
- [ ] Get commands have `--table` option
- [ ] auth login has `--force/-F` flag -- when auth commands are present
- [ ] README documents ALL commands with examples
- [ ] Output shape defined and covered by command contract tests
- [ ] Internal representation is minimal: no unused helpers, models, or dependencies
- [ ] Browser parsers validated against real DOM captures via BrowserAutomation (browser CLIs only)
- [ ] ALL command structure tests pass (none skipped due to missing `main.py`, `commands/`, or missing `list`/`get` commands). `test_install.py` is the only permitted structural skip for non-wrapper CLIs.
- [ ] **⛔ test-cli-tool.sh passes with ZERO FAILURES** (warnings acceptable)
- [ ] `/debloat` post-implementation pass completed (Step 6.5)
- [ ] AI Review completed (for API CLIs):
  - [ ] --limit implemented at API level (not client-side slicing)
  - [ ] --filter translates to API parameters (client-side only as fallback)
  - [ ] No dedicated filter commands
  - [ ] Exponential retry correctly implemented
  - [ ] Internal representation is minimal and tied to the command contract
- [ ] `/debloat` final pass completed (Step 9.5) — tests still pass after fixes
- [ ] Step 9.7 LastPass/profile/live-smoke completed for non-wrapper API/browser service CLIs:
  - [ ] `lastpass auth status` passed and `lastpass items list` searched the service credential entry without printing secrets
  - [ ] Needed reusable credential values were transferred to `<cli-tools-root>/_repo/_secret-manager/secrets.sh`
  - [ ] CLI auth profile was created or verified through the CLI's own `auth` commands
  - [ ] Adam completed any required one-time browser/MFA/consent authentication
  - [ ] `<name> auth status --profile <profile-name>` confirmed authenticated profile JSON
  - [ ] At least one live read-only service smoke command succeeded
  - [ ] `test-cli-tool.sh --cli-name <name>` passed with the saved authenticated profile
- [ ] Wrapper CLIs explicitly skipped Step 9.7 unless the wrapper owns a separate CLI-tools auth profile
- [ ] cli_tools.md has been updated with the new CLI
- [ ] `/create-cli-tool-skill` invoked to generate the CLI's repo-owned skill
- [ ] Git repo initialized and committed

**⛔ BLOCKING REQUIREMENT: Do NOT mark CLI as complete if test-cli-tool.sh shows ANY failures.**
</success_criteria>
