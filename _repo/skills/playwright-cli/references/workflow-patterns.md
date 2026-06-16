# Workflow Patterns

Common automation patterns using `playwright-cli`. All commands are flat — no grouped subcommands.

## Navigate and Interact with Elements

The fundamental pattern for all element-based automation:

```bash
# 1. Open browser and navigate
playwright-cli open https://example.com

# 2. Take snapshot to get element references
playwright-cli snapshot
# Returns refs like: ref="input_username", ref="btn_submit"

# 3. Interact using refs from snapshot
playwright-cli fill ref="input_username" "admin@example.com"
playwright-cli click ref="btn_submit"

# 4. Re-snapshot after page changes (refs become stale)
playwright-cli snapshot
```

**Key rule:** Always re-snapshot after any action that changes the page (click, navigation, form submit). Refs from a previous snapshot are invalid after the DOM changes.

## Login and Save Auth State

```bash
# Login with a password from a secret source, without printing the value
secrets_file="$(mktemp)"
trap 'rm -f "$secrets_file"' EXIT
APP_PASSWORD="$(lastpass items password ITEM_ID)" node - "$secrets_file" <<'NODE'
const fs = require("fs");
const [file] = process.argv.slice(2);
const value = process.env.APP_PASSWORD;
if (!value) throw new Error("APP_PASSWORD is empty");
fs.writeFileSync(file, `APP_PASSWORD=${JSON.stringify(value)}\n`, { mode: 0o600 });
NODE

PLAYWRIGHT_MCP_SECRETS_FILE="$secrets_file" playwright-cli -s=app open https://app.example.com/login
playwright-cli snapshot
playwright-cli fill ref="email_input" "user@example.com"
playwright-cli -s=app fill ref="password_input" APP_PASSWORD
playwright-cli click ref="login_button"

# Save auth state for reuse
playwright-cli state-save auth-example.json

# Later: restore auth state (skip login)
playwright-cli -s=app open
playwright-cli state-load auth-example.json
playwright-cli goto https://app.example.com/dashboard
```

**Secret rule:** `run-code` cannot read `process.env`; its VM context only receives `page`. For secret entry, set `PLAYWRIGHT_MCP_SECRETS_FILE` when opening the session and pass the secret key name, not the secret value, to `fill` or `type`. Do not verify real password fields by returning their full `inputValue()`.

**Validation pitfall:** Dummy values in `PLAYWRIGHT_MCP_SECRETS_FILE` are still secrets. If a wrapper reads a field value after filling from a dummy secret key, expect the CLI response redaction layer to return `<secret>KEY_NAME</secret>` rather than the literal dummy value. Validate that command output uses `process.env['KEY_NAME']` and does not print the raw value.

## Form Filling

```bash
playwright-cli snapshot

# Text fields — use fill (instant replace, requires ref)
playwright-cli fill ref="name_field" "John Doe"

# Search/autocomplete fields — focus with click, then type
# (type takes only text, not a ref)
playwright-cli click ref="search_box"
playwright-cli type "search query"
# Submit the typed text:
playwright-cli type "search query" --submit

# Dropdowns
playwright-cli select ref="country_select" "US"

# Checkboxes
playwright-cli check ref="agree_checkbox"

# File upload
playwright-cli upload /path/to/file.pdf

# Submit
playwright-cli click ref="submit_btn"
```

## Multi-Tab Workflows

```bash
# Open initial page
playwright-cli open https://example.com

# Open new tab
playwright-cli tab-new https://other-site.com

# List tabs
playwright-cli tab-list

# Switch between tabs (0-indexed)
playwright-cli tab-select 0  # back to first tab
playwright-cli tab-select 1  # second tab

# Close a tab
playwright-cli tab-close 1
```

## Scraping and Data Extraction

```bash
# Navigate to page
playwright-cli goto https://example.com/data

# Run JavaScript to extract data
playwright-cli eval "() => document.title"
playwright-cli eval "() => JSON.stringify([...document.querySelectorAll('table tr')].map(r => r.textContent))"

# Screenshot for visual capture
playwright-cli screenshot
playwright-cli screenshot ref="chart_element"            # specific element
playwright-cli screenshot --full-page --filename out.png # full scrollable page

# Save as PDF
playwright-cli pdf
```

## Render local HTML or SVG to PNG

`playwright-cli` only allows the `http:`, `https:`, `about:`, and `data:` protocols, so `file://` URLs are blocked — a `goto file://…` is rejected. The failure is silent: a `screenshot` run after the blocked navigation still exits `0` but captures a blank page, so the rejection is easy to miss. To render a local HTML/SVG file, load it as a `data:` URL or serve it over a local http server instead.

```bash
# data: URL — charset=utf-8 is REQUIRED, or non-ASCII (em dashes, etc.) render as mojibake
b64=$(base64 -i diagram.html | tr -d '\n')
playwright-cli resize 1920 1080
playwright-cli goto "data:text/html;charset=utf-8;base64,$b64"
playwright-cli screenshot --filename out.png

# Alternative for larger or multi-file pages: serve over http, then navigate to it
python3 -m http.server 8765 --directory . &
playwright-cli goto http://localhost:8765/diagram.html
playwright-cli screenshot --filename out.png
```

## Network Monitoring

```bash
# Navigate and let requests happen
playwright-cli goto https://example.com

# List all requests made (markdown summary; full log saved to .playwright-cli/network-*.log)
playwright-cli network

# Include static resources (images, fonts, scripts)
playwright-cli network --static

# To filter, read the log file directly and grep/jq it:
log=$(playwright-cli network | awk -F'[()]' '/\[Network\]/{print $2; exit}')
grep '/api/' "$log"

# Clear the captured list
playwright-cli network --clear

# Mock a network endpoint
playwright-cli route "**/api/data*" --status 200 --body '{"ok":true}' --content-type application/json
playwright-cli route-list              # see active routes
playwright-cli unroute "**/api/data*"  # remove mock
playwright-cli unroute                 # remove all routes
```

## Cookie and Storage Management

```bash
# Cookies
playwright-cli cookie-list
playwright-cli cookie-list --domain example.com
playwright-cli cookie-get "session_token"
playwright-cli cookie-set "custom_flag" "true" --domain example.com --secure
playwright-cli cookie-delete "tracking_id"
playwright-cli cookie-clear

# localStorage
playwright-cli localstorage-list
playwright-cli localstorage-get "app_settings"
playwright-cli localstorage-set "theme" "dark"
playwright-cli localstorage-delete "stale_key"
playwright-cli localstorage-clear

# sessionStorage (same API, session-scoped)
playwright-cli sessionstorage-list
playwright-cli sessionstorage-get "temp_data"
playwright-cli sessionstorage-set "flow_step" "2"
playwright-cli sessionstorage-clear
```

## Debugging and Recording

```bash
# View console messages
playwright-cli console              # info and above (default)
playwright-cli console error        # errors only
playwright-cli console warning      # warnings+
playwright-cli console --clear      # reset the captured log

# Record a trace (for debugging)
playwright-cli tracing-start
# ... perform actions ...
playwright-cli tracing-stop

# Record video
playwright-cli video-start
# ... perform actions ...
playwright-cli video-stop --filename /tmp/session.webm

# Run raw Playwright code (pass a callable expression invoked with `page`)
playwright-cli run-code "async (page) => { const title = await page.title(); return title; }"

# Do not pass top-level statements; this can print `### Error` while exiting 0:
# playwright-cli run-code "await page.title();"

# Do not use run-code for secret entry; process is unavailable in its VM:
# playwright-cli run-code 'async (page) => page.getByRole("textbox", { name: "Password" }).fill(process.env.APP_PASSWORD)'
```

## Dialog Handling

```bash
# Accept alert/confirm
playwright-cli dialog-accept

# Accept prompt with text
playwright-cli dialog-accept "my response text"

# Dismiss (cancel)
playwright-cli dialog-dismiss
```

## Multi-Session Management

```bash
# Open named sessions (capture the session ID from output)
playwright-cli open https://site-a.com
playwright-cli open https://site-b.com

# List all sessions (add --all to include other workspaces)
playwright-cli list
playwright-cli list --all

# Target a specific session with -s=<name>
playwright-cli -s=session_name snapshot
playwright-cli -s=session_name click ref="element"

# Cleanup
playwright-cli close-all
playwright-cli kill-all  # for stale/zombie processes
```

## Scrolling

```bash
# Scroll down
playwright-cli mousewheel 0 500

# Scroll up
playwright-cli mousewheel 0 -500

# Scroll right
playwright-cli mousewheel 500 0
```

## Keyboard and Mouse Primitives

```bash
# Keyboard
playwright-cli press Enter
playwright-cli press ArrowDown
playwright-cli keydown Shift
playwright-cli click ref="checkbox"
playwright-cli keyup Shift

# Mouse
playwright-cli mousemove 400 300
playwright-cli mousedown
playwright-cli mousemove 600 500
playwright-cli mouseup
```

## Setup and Installation

```bash
# Initialize workspace (first-time setup)
playwright-cli install

# Install/update browser binary
playwright-cli install-browser --browser chrome

# Resize browser window
playwright-cli resize 1920 1080

# Wipe session data
playwright-cli delete-data
```
