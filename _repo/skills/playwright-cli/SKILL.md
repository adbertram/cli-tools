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
</principle>

<principle name="Session Management">
- **Default session**: Commands operate on the most recent browser session automatically.
- **Named sessions**: Use `-s=<session_name>` global option to target a specific session.
- **List sessions**: `playwright-cli list` (add `--all` to include sessions from all workspaces).
- **Multiple sessions**: Open multiple browsers with `playwright-cli open`, target each with `-s=<name>`.
- **Cleanup**: `playwright-cli close-all`, or `playwright-cli kill-all` for stale/zombie processes.
</principle>

<principle name="fill vs type">
- `fill REF "text"` — Replaces existing content instantly (like clearing + pasting). Requires a REF. Use for most form fields.
- `type "text"` — Types character by character into the currently focused element. **Takes only text, no REF.** Focus the target first (e.g., `click REF`) before `type`. Use when the field has autocomplete, live search, or key-by-key event handlers. Add `--submit` to press Enter after typing.
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

Do not assume Node globals are available in `run-code`. In this environment, `require(...)` fails with `ReferenceError: require is not defined`, and dynamic `import(...)` can fail with `ERR_VM_DYNAMIC_IMPORT_CALLBACK_MISSING`. For local CLI lookups or secrets, retrieve values outside `run-code`, redirect command output when needed, and use normal snapshot-ref commands.

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
- Command executes without error.
</success_criteria>
