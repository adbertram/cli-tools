---
name: playwright-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Use this skill for ALL playwright-cli browser automation operations.
  DO NOT run playwright-cli commands without loading this skill first.
  Expert reference for the playwright-cli tool covering all commands, syntax,
  session management, element interaction model, and workflow patterns.
  Triggers: "playwright-cli", "playwright cli", "browser automation",
  "page snapshot", "browser session", "playwright click", "playwright fill",
  "playwright navigate", "open browser", "take screenshot with playwright".
---

<objective>
Expert reference for the `playwright-cli` browser automation CLI (npm package `@playwright/cli`, v0.1.0). Provides complete command syntax, interaction patterns, and workflow guidance for all 67 flat commands.
</objective>

<quick_start>
```bash
playwright-cli [-s=<session>] <command> [arguments] [options]
```

**Commands are flat — there are no grouped subcommands.** Write `playwright-cli snapshot`, not `playwright-cli page snapshot`.

| Task | Command |
|------|---------|
| Open browser to URL | `playwright-cli open https://example.com` |
| Navigate to URL | `playwright-cli goto https://example.com` |
| Take page snapshot | `playwright-cli snapshot` |
| Click element | `playwright-cli click REF` |
| Fill form field | `playwright-cli fill REF "text"` |
| Take screenshot | `playwright-cli screenshot` |
| List sessions | `playwright-cli list` |
| Press key | `playwright-cli press Enter` |
| Save auth state | `playwright-cli state-save auth.json` |
| List network requests | `playwright-cli network` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `playwright-cli` command.**
It contains every command, argument, and option with descriptions sourced directly from `--help`. Never guess at syntax. When in doubt, also run `playwright-cli --help <command>`.
</principle>

<principle name="Flat Command Surface">
The binary exposes flat commands — single-word (`open`, `close`, `goto`, `snapshot`, `click`, `fill`, `type`, `hover`, `select`, `upload`, `check`, `uncheck`, `drag`, `eval`, `reload`, `press`, `pdf`, `resize`, `list`, `network`, `route`, `console`, `install`) or hyphenated (`dialog-accept`, `dialog-dismiss`, `go-back`, `go-forward`, `tab-list`, `tab-new`, `tab-close`, `tab-select`, `state-load`, `state-save`, `cookie-list`, `cookie-get`, `cookie-set`, `cookie-delete`, `cookie-clear`, `localstorage-*`, `sessionstorage-*`, `route-list`, `unroute`, `run-code`, `tracing-start`, `tracing-stop`, `video-start`, `video-stop`, `install-browser`, `close-all`, `kill-all`, `delete-data`, `mousemove`, `mousedown`, `mouseup`, `mousewheel`, `keydown`, `keyup`, `dblclick`).

There are **no** grouped forms like `browser open`, `page snapshot`, `interact click`, `tab list`, `cookie get`, `network requests`, `devtools console`, or `data delete`. Those will fail at parse time.
</principle>

<principle name="Snapshot-Ref Interaction Model">
The core interaction pattern for element-based commands:
1. **Snapshot** — `playwright-cli snapshot` captures the page and returns element references (REFs)
2. **Interact** — Use the REF in an interaction command: `playwright-cli click REF`

The following commands require a REF from a prior snapshot: `click`, `dblclick`, `fill`, `hover`, `drag` (two refs), `select`, `check`, `uncheck`, and optionally `screenshot`/`eval`. Always snapshot before interacting, and re-snapshot after any DOM-changing action — stale refs are invalid. After any submit or navigation, inspect the new snapshot and continue from the live page state; do not assume the next page or step.

Interaction commands can report a markdown `### Error` block after the browser has already completed part of the action, such as a submit click that times out while the page still navigates. Treat `### Error` in stdout as an action error, then verify the final page state with `snapshot`, URL, or title before deciding whether the workflow can continue from the new page.
</principle>

<principle name="Session Management">
- **Default session**: Commands operate on the most recent browser session automatically.
- **Named sessions**: Use `-s=<session_name>` global option to target a specific session.
- **Do not use implicit `default` for automation**: For portal login,
credential, and multi-step browser work, open and reuse a short named session
with `-s=<short-name>` on every command. A bare command uses `default`, which
maps to `default.sock` under the workspace daemon hash; concurrent or stale
daemon startup can fail with `listen EADDRINUSE .../default.sock`. If this
happens, do not retry the bare command. Run `playwright-cli list --all`, target
the intended named session, or use `kill-all` only after preserving any needed
browser state.
- **Keep session names short on macOS**: The CLI embeds the session name directly in a Unix socket path under the system temp directory. Long names can exceed macOS socket path limits and fail with `listen EINVAL`. Use short lowercase names such as `rcenv`, `impact`, or `bf` instead of descriptive names like `codex-run-code-env-test`.
- **Recover after socket/runtime failures**: Errors such as `EADDRINUSE`,
  `listen EINVAL`, daemon startup failure, or `The browser '<name>' is not open,
  please run open first` mean the CLI session state is not trustworthy. Stop
  issuing element-ref commands like `click`, `fill`, or `press` against the old
  refs. Preserve the exact error, run `playwright-cli list` to prove whether the
  named session still exists, then either reopen the same short named session
  with `playwright-cli -s=<name> open <current-url>` and take a fresh
  `snapshot`, or escalate to the next approved browser-control method with the
  target URL and failure evidence. Never paste credentials into a session after
  this failure until the browser has been reopened and the visible destination
  has been verified.
- **List sessions**: `playwright-cli list` (add `--all` to include sessions from all workspaces).
- **Multiple sessions**: Open multiple browsers with `playwright-cli open`, target each with `-s=<name>`.
- **Cleanup**: `playwright-cli close-all`, or `playwright-cli kill-all` for stale/zombie processes.
</principle>

<principle name="Installed Package Internals">
When diagnosing the npm-installed `@playwright/cli` package, do not call
`require.resolve()` on guessed private package subpaths such as
`playwright/lib/mcp/terminal/daemon`. Node enforces the package `exports` map,
and non-exported internals fail with `ERR_PACKAGE_PATH_NOT_EXPORTED` even when
the file exists on disk. Resolve an exported neighboring module from the real
launcher package context first, then inspect adjacent files by filesystem path
only after proving those paths exist.

```bash
launcher=$(command -v playwright-cli)
node -e 'const fs=require("node:fs"); const path=require("node:path"); const {createRequire}=require("node:module"); const launcher=fs.realpathSync(process.argv[1]); const req=createRequire(launcher); const exported=req.resolve("playwright/lib/mcp/terminal/program"); const dir=path.dirname(exported); const target=path.join(dir,"daemon.js"); if (!fs.existsSync(target)) { console.error(`MISSING_INSTALLED_FILE:${target}`); process.exit(1); } console.log(target);' "$launcher"
```
</principle>

<principle name="fill vs type">
- `fill REF "text"` — Replaces existing content instantly (like clearing + pasting). Requires a REF. Use for most form fields.
- `type "text"` — Types character by character into the currently focused element. **Takes only text, no REF.** Focus the target first (e.g., `click REF`) before `type`. Use when the field has autocomplete, live search, or key-by-key event handlers. Add `--submit` to press Enter after typing.
- For password/API-key/token fields, do not pass the real secret value as the `fill`/`type` text and do not embed it in `run-code`; command output includes the generated Playwright code. Instead, open the session with `PLAYWRIGHT_MCP_SECRETS_FILE` pointing to a dotenv file, then pass the secret key name to `fill` or `type`, e.g. `playwright-cli -s=pp fill REF PAYPAL_PASS`. The CLI fills the secret value and redacts it from output as `<secret>PAYPAL_PASS</secret>`.
- If `click REF` on a visible submit control is blocked by an overlay or intercepted pointer events, use keyboard submission from the focused field, such as `playwright-cli press Enter` or `playwright-cli fill REF "text" --submit`, before reaching for raw DOM submission.
</principle>

<principle name="CAPTCHA and Disabled Submit Controls">
After CAPTCHA or anti-bot callbacks, do not treat a token or a single input's
`disabled === false` as proof that the submit button is enabled. Re-snapshot the
page and verify the actual submit control's state with `playwright-cli eval`,
including `disabled`, `aria-disabled`, class names, visibility, and the
accessible snapshot text. If the target control still has `aria-disabled="true"`
or a disabled class, do not force-click it and do not remove the disabled state
with `eval`; wait for the page's callback to complete, re-check required fields,
or use the site's normal keyboard submission only when the focused field is a
non-sensitive lookup/search field and the action is not a final payment,
medical, financial, credential, or account-changing submit. For payment,
medical, financial, credential, or final authorization flows, a Playwright
"not enabled" click failure is a stop-and-report condition unless the site
itself later enables the button through its normal UI.
</principle>

<principle name="Command Categories">
The categories below mirror the section headers in `playwright-cli --help`. They are **reference groupings only** — they are NOT prefixes. Always invoke the flat command name.

- **Core** — `open`, `close`, `goto`, `type`, `click`, `dblclick`, `fill`, `drag`, `hover`, `select`, `upload`, `check`, `uncheck`, `snapshot`, `eval`, `dialog-accept`, `dialog-dismiss`, `resize`, `delete-data`
- **Navigation** — `go-back`, `go-forward`, `reload`
- **Keyboard** — `press`, `keydown`, `keyup`
- **Mouse** — `mousemove`, `mousedown`, `mouseup`, `mousewheel`
- **Save as** — `screenshot`, `pdf`
- **Tabs** — `tab-list`, `tab-new`, `tab-close`, `tab-select`
- **Storage** — `state-load`, `state-save`, `cookie-{list,get,set,delete,clear}`, `localstorage-{list,get,set,delete,clear}`, `sessionstorage-{list,get,set,delete,clear}`
- **Network** — `route`, `route-list`, `unroute`
- **DevTools** — `console`, `run-code`, `network`, `tracing-start`, `tracing-stop`, `video-start`, `video-stop`
- **Install** — `install`, `install-browser`
- **Browser sessions** — `list`, `close-all`, `kill-all`
</principle>

<principle name="Output Format">
Commands return **markdown** (Slack-style `mrkdwn` with `###` headers and indented list items) — **not JSON**. Large results (snapshots, network logs, console logs) are written to files inside `.playwright-cli/` and the command output references them by path. Read those files directly for structured data. When using `--filename`, keep the command output visible and verify the referenced file is non-empty before relying on it; modal dialogs and failed or blocked states can still produce useful command output even when a redirected file is empty.

When redirecting `playwright-cli` stdout to an artifact, especially for
`run-code`, do not run a bare command such as `playwright-cli ... run-code ...
>"$out"`. Create the artifact parent, capture stderr to a sidecar file,
preserve the producer status, and print explicit evidence on failure. On
success, verify the stdout artifact is non-empty and inspect it for `### Error`
before treating the command as successful.
If a validation wrapper prints per-case summaries to the parent stdout, capture
that wrapper stdout in its own log and assert summary markers against that log,
not against the per-case redirected producer stdout artifacts.

```bash
out=/path/to/workspace/dom.json
err=/path/to/workspace/dom.stderr
mkdir -p "$(dirname "$out")"
if playwright-cli -s=ata run-code 'async (page) => ({ title: await page.title() })' >"$out" 2>"$err"; then
  if [ ! -s "$out" ]; then
    printf 'PLAYWRIGHT_STDOUT_EMPTY:%s\n' "$out" >&2
    exit 1
  fi
  rg -n -F -- '### Error' "$out"
  rg_rc=$?
  if [ "$rg_rc" -eq 0 ]; then
    printf 'PLAYWRIGHT_MARKDOWN_ERROR:%s\n' "$out" >&2
    exit 1
  fi
  [ "$rg_rc" -eq 1 ] || exit "$rg_rc"
else
  rc=$?
  printf 'PLAYWRIGHT_FAILED:%s rc=%s stderr=%s\n' "$out" "$rc" "$err" >&2
  [ -s "$err" ] && sed -n '1,80p' "$err" >&2
  exit "$rc"
fi
```

Per-command options vary and are documented in `usage.json`; examples:
- `list` supports `--all`
- `cookie-list` supports `--domain` / `--path`
- `network` supports `--static` / `--clear`
- `console` supports `--clear` and a positional `min-level` (info, warning, error, etc.)
- `screenshot` supports `--filename` / `--full-page`

There are **no** generic `--table`, `--limit`, `--filter`, `--properties`, or `--json` flags. To filter list output, parse the markdown or read the `.playwright-cli/*.log` file the command wrote.
</principle>

<principle name="Verify Form Mutations">
`run-code` expects a JavaScript function/callable expression invoked with the `page` object. Do not pass top-level statements such as `await page.title();` or `const title = await page.title();`; use `async (page) => { ... }` for multi-statement snippets. Runtime syntax errors can print a markdown `### Error` block while the process still exits `0`, so inspect stdout for `### Error` before treating a `run-code` result as successful.

Do not assume Node globals are available in `run-code`. In this environment, `process` is `undefined`, `require(...)` fails with `ReferenceError: require is not defined`, and dynamic `import(...)` can fail with `ERR_VM_DYNAMIC_IMPORT_CALLBACK_MISSING`. For secrets, do not use `process.env` in `run-code`; open the session with `PLAYWRIGHT_MCP_SECRETS_FILE` and use normal snapshot-ref `fill`/`type` commands with the secret key name.

After dropdown changes, verify the live DOM value with `playwright-cli eval`. If `playwright-cli select REF VALUE` reports success but the selected value is still empty, set the element value with `eval` and dispatch a bubbling `change` event, then verify again.
</principle>

<principle name="Sensitive Form Verification">
For payment or credential flows, minimize exploratory commands once sensitive pages are open. Before final submit, use `playwright-cli eval` to verify only sanitized values: merchant/payee, account/reference, amount, email, card last four, expiration, CVV length, billing ZIP/address summary, and required unchecked/checked flags. Never print full card numbers, CVV values, passwords, or tokens.
</principle>
</essential_principles>

<reference_index>
- **`usage.json`** — Flat command map with all arguments, options, defaults, and descriptions (sourced from `--help`).
- **`references/workflow-patterns.md`** — Common automation workflows (login, form filling, scraping, state persistence, network mocking, recording).
</reference_index>

<success_criteria>
- Flat command name used (verified against `usage.json` or `playwright-cli --help <cmd>`).
- Snapshot taken before any element-ref interaction command.
- `-s=<session>` used when multiple sessions exist.
- Command stdout inspected for `### Error`; when present, final page state is verified before continuing.
</success_criteria>
