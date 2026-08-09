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
Expert reference for the `playwright-cli` browser automation CLI (npm package `@playwright/cli`, v0.1.18). Provides command syntax and workflow guidance for all 86 visible flat commands.
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
| List network requests | `playwright-cli requests` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `playwright-cli` command.**
It contains every command, argument, and option with descriptions sourced directly from `--help`. Never guess at syntax. When in doubt, also run `playwright-cli --help <command>`.
</principle>

<principle name="Flat Command Surface">
The binary exposes only flat commands. The adjacent `usage.json` contains the
exact current command names, arguments, and options.

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
- **A named session is not a persistent profile**: The daemon defaults to an
  isolated context. A config file can contain `browser.userDataDir`, but that
  path is not used unless `open` also enables persistence. When the config owns
  the profile and executable, use
  `playwright-cli -s=svc open URL --config /absolute/path/cli.config.json --persistent`
  and require the resulting status to report the configured path. A reported
  `user-data-dir: <in-memory>` is a failed profile launch. `--profile <dir>`
  also implies persistence; do not give it a path that conflicts with the
  config's `browser.userDataDir`.
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
First prove the launcher identity with `command -v`, its resolved path, its
shebang, and the owning package metadata. The canonical launcher must resolve
to the npm package `@playwright/cli` at the version recorded in `usage.json`.
A Python launcher that imports `playwright_cli.main` is a different wrapper.
Its grouped `browser`, `page`, or `interact` commands do not define this
skill's contract. Repair the launcher or package install. Do not translate flat
commands for that wrapper.

Do not call `require.resolve()` on guessed private package subpaths. Node can
reject them with `ERR_PACKAGE_PATH_NOT_EXPORTED`. Resolve the real launcher,
then inspect its adjacent package metadata by file path.

```bash
launcher=$(command -v playwright-cli)
node -e 'const fs=require("node:fs"); const path=require("node:path"); const launcher=fs.realpathSync(process.argv[1]); const packageJson=path.join(path.dirname(launcher),"package.json"); if (!fs.existsSync(packageJson)) { console.error(`MISSING_PACKAGE_JSON:${packageJson}`); process.exit(1); } const pkg=JSON.parse(fs.readFileSync(packageJson,"utf8")); if (pkg.name !== "@playwright/cli") { console.error(`WRONG_PACKAGE_OWNER:${pkg.name}`); process.exit(1); } console.log(JSON.stringify({launcher,packageJson,name:pkg.name,version:pkg.version},null,2));' "$launcher"
```
</principle>

<principle name="fill vs type">
- `fill REF "text"` — Replaces existing content instantly (like clearing + pasting). Requires a REF. Use for most form fields.
- `type "text"` — Types character by character into the currently focused element. **Takes only text, no REF.** Focus the target first (e.g., `click REF`) before `type`. Use when the field has autocomplete, live search, or key-by-key event handlers. Add `--submit` to press Enter after typing.
- For password/API-key/token fields, do not pass the real secret value as the `fill` text and do not embed it in `run-code`; command output includes the generated Playwright code. Instead, open the session with `PLAYWRIGHT_MCP_SECRETS_FILE` pointing to a dotenv file, then pass the secret key name to `fill` only, e.g. `playwright-cli -s=pp fill REF PAYPAL_PASS`. The CLI fills the secret value and redacts it from output as `<secret>PAYPAL_PASS</secret>`.
- **Only `fill` substitutes a secret key. `type` does not. Never pass a secret key name to `type`.** The CLI `fill` command maps to the MCP tool `browser_type`, which calls `lookupSecret`. The CLI `type` command maps to the MCP tool `browser_press_sequentially`, whose handler calls `page.keyboard.type(text)` and never calls `lookupSecret`. Only `browser_type` and `browser_fill_form` call `lookupSecret`. `playwright-cli -s=x type MY_KEY` types the literal characters `MY_KEY` into the page. The result is a failed login that looks like a wrong-password event. There is no CLI command that types a secret key by key. Verified in published `@playwright/cli` 0.1.18.
- **Every secret `fill` requires the post-fill length check.** See the `Secret Fill Verification` principle below.
- If `click REF` on a visible submit control is blocked by an overlay or intercepted pointer events, use keyboard submission from the focused field, such as `playwright-cli press Enter` or `playwright-cli fill REF "text" --submit`, before reaching for raw DOM submission.
</principle>

<principle name="Secret Fill Verification (MANDATORY)">
Version 0.1.18 resolves the secret, then calls `locator.fill()` on the target.
Exit status `0` does not prove the final page state. A stale ref or a page
script can still change the target value.

After every secret `fill`, read back the per-field value **LENGTHS** and confirm two facts:
1. The intended field's value length equals the secret's length.
2. No other field's value length changed.

Never read, print, or log a field value. Read `value.length` only.

Take a baseline before the `fill`, then check after the `fill`:

```bash
guard=/Users/adam/Dropbox/GitRepos/Agents/skills/global/browser-automation/scripts/verify-secret-fill.sh
"$guard" baseline pp /tmp/pw-base.json
playwright-cli -s=pp fill REF PAYPAL_PASS
"$guard" check pp /tmp/pp.env PAYPAL_PASS '#password' /tmp/pw-base.json
```

The guard prints `PW_GUARD_OK` and exits `0` only when both facts hold. On `PW_GUARD_FAIL`, **do not submit the form.** Clear the polluted field, resolve why the focus moved, and fill again. On a two-step login, submit the email step first so the password field genuinely accepts the focus. Do not set the value with `eval` or `run-code`; that puts the plaintext secret on the command line and skips the page's input events.

The inline equivalent of the length read:

```bash
playwright-cli -s=pp eval "() => Array.from(document.querySelectorAll('input,textarea')).map(el => ({ sel: el.id, type: el.type, len: el.value.length }))"
```

A `fill` that puts the literal secret key name into the page is a different failure: the secrets file path was missing or unreadable. Stop, and rerun with the real readable `PLAYWRIGHT_MCP_SECRETS_FILE` path. Do not keep submitting the form.
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
The `category` values in `usage.json` mirror the help section names. They are
reference groups only. Always invoke the flat command name.
</principle>

<principle name="Output Format">
Commands return **markdown** by default. Use the global `--json` option for a
JSON response. Use `--raw` for only the result value. Large results, such as snapshots and network logs,
console logs) are written to files inside `.playwright-cli/` and the command
output references them by path. Read those files directly for structured data.
When using `--filename`, keep the command output visible and verify the
referenced file is non-empty before relying on it; modal dialogs and failed or
blocked states can still produce useful command output even when a redirected
file is empty. `snapshot --filename FILE` can also exit `0` and print a
Snapshot link while `FILE` is zero bytes if the page has not produced an
accessibility tree yet. Wait for a target-specific semantic locator, take a
fresh snapshot, and require `test -s FILE`; the link alone is not proof.

When redirecting `playwright-cli` stdout to an artifact, especially for
`run-code`, do not run a bare command such as `playwright-cli ... run-code ...
>"$out"`. Create the artifact parent, capture stderr to a sidecar file,
preserve the producer status, and print explicit evidence on failure. On
success, verify the stdout artifact is non-empty and inspect it for `### Error`
before treating the command as successful.
If the command exits non-zero, print stdout as failure evidence because
`run-code` writes markdown `### Error` output to stdout while stderr can be
empty.
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
  printf 'PLAYWRIGHT_FAILED:%s rc=%s stdout=%s stderr=%s\n' "$out" "$rc" "$out" "$err" >&2
  [ -s "$out" ] && sed -n '1,80p' "$out" >&2
  [ -s "$err" ] && sed -n '1,80p' "$err" >&2
  exit "$rc"
fi
```

Per-command options vary and are documented in `usage.json`; examples:
- `list` supports `--all`
- `cookie-list` supports `--domain` / `--path`
- `requests` supports `--static` / `--filter` / `--clear`
- `console` supports `--clear` and a positional `min-level` (info, warning, error, etc.)
- `screenshot` supports `--filename` / `--full-page`

There are no generic `--table`, `--limit`, or `--properties` flags. Use only
the options listed for the exact command in `usage.json`.
</principle>

<principle name="Eval Versus Run-Code">
`eval` executes JavaScript in the browser DOM context. It does not receive a
Playwright `page` object: use `() => ...` for page-global DOM code, or
`(element) => ...` with a REF when inspecting one snapshot element. Do not pass
`async (page) => page.locator(...)` to `eval`; `page` will be undefined. When a
probe needs Playwright APIs such as `page.locator`, `page.getByRole`, or
`page.title`, use `run-code` with `async (page) => { ... }` and inspect stdout
for `### Error`.
</principle>

<principle name="Verify Form Mutations">
`run-code` expects a JavaScript function/callable expression invoked with the `page` object. Do not pass top-level statements such as `await page.title();` or `const title = await page.title();`; use `async (page) => { ... }` for multi-statement snippets. Runtime syntax errors can print a markdown `### Error` block while the process still exits `0`, so inspect stdout for `### Error` before treating a `run-code` result as successful.

Do not assume Node globals are available in `run-code`. In this environment, `process` is `undefined`, `require(...)` fails with `ReferenceError: require is not defined`, and dynamic `import(...)` can fail with `ERR_VM_DYNAMIC_IMPORT_CALLBACK_MISSING`. For secrets, do not use `process.env` in `run-code`; open the session with `PLAYWRIGHT_MCP_SECRETS_FILE` and use a snapshot-ref `fill` command with the secret key name. Only `fill` substitutes a secret key. Never pass a secret key name to `type`, because `type` sends the literal characters. Verify every secret `fill` with the length check in the `Secret Fill Verification` principle.

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
- Secret key names passed to `fill` only, never to `type`.
- Every secret `fill` followed by the per-field length check, and the form not submitted when the check fails.
</success_criteria>
