---
name: cli-tool
description: >-
  MANDATORY: CLI tool skill router for ALL cli-tools requests. Use this skill
  first for any available CLI tool, service CLI operation, CLI command
  execution, or CLI lifecycle work. DO NOT run cli-tools commands, guess
  command syntax, or load individual [tool]-cli skills directly before this
  router selects them. For service operations, route through
  [cli-tools-root]/_repo/skills/cli-tool/workflows/skill-router.md to
  [cli-tools-root]/_repo/skills/[tool]-cli/SKILL.md and the adjacent
  usage.json. For lifecycle work, delegate to cli-tool-expert
  and use this skill's lifecycle workflows. Triggers: any cli tool, cli
  command, service cli, [tool] cli, run cli, execute cli, create cli, update
  cli, test cli, fix cli, add command, list cli tools, cli standards.
---

<objective>
Route every cli-tools request to the correct repo-owned CLI skill or lifecycle workflow, then execute against the real command contract.
</objective>

<agent_routing>
Service-operation routing stays in the current session: use `<cli-tools-root>/_repo/skills/cli-tool/workflows/skill-router.md`, then load the selected service skill and its adjacent `usage.json`.

When this skill is invoked for CLI lifecycle work by a parent agent session and the current agent is not `cli-tool-expert`, delegate the lifecycle work to `cli-tool-expert` instead of performing CLI implementation work inline. Pass the complete user request, relevant file paths, constraints, and required validation.

When the current agent is `cli-tool-expert`, follow this skill normally.
</agent_routing>

<skill_router>
The repo-owned source of truth for CLI service skills is `<cli-tools-root>/_repo/skills`.

Classify skills by ownership and domain, not by whether they call a CLI as an
implementation detail. Service CLI skills and CLI lifecycle workflows live under
`<cli-tools-root>/_repo/skills`; project-specific workflows that merely call a
CLI belong to the target project's skill scope.

For any request that uses an existing CLI tool, read `<cli-tools-root>/_repo/skills/cli-tool/workflows/skill-router.md` before selecting a service skill. Do not look for the workflow at `<cli-tools-root>/_repo/skills/skill-router.md`. The selected service skill's `SKILL.md` and adjacent `usage.json` are mandatory before running any command.
</skill_router>

<tool_discovery>
Use `<cli-tools-root>/_repo/scripts/find-cli-tools.sh` to enumerate the
available CLI tools from the source tree. The script prints one JSON array of
records with `name`, `readme`, and `description`, where `description` is
extracted from each tool README's `## DESCRIPTION` block. The `readme` value is
relative to `<cli-tools-root>` unless it is already absolute; resolve it against
that root before deriving the tool directory or checking files. The default mode is
JSON, and `--json` is accepted as an explicit alias for that default. When
filtering the saved output with `jq`, iterate the array explicitly, for example
`jq -e '.[] | select(.name == "google")' <file>`. Do not treat the output as
JSONL records. When parsing the saved JSON with Python, do not wrap a quoted
heredoc parser inside a single-quoted `bash -lc '...'` command; that quote layer
can strip Python string literals such as `Path('/tmp/cli-tools.json')` before
Python starts. Instead invoke the parser as a standalone multiline command and
pass the JSON file path as argv, for example `python3 - "$json_file" <<'PY'`,
then read `sys.argv[1]` inside Python. Pass `--markdown` for a compact
`- name: <first sentence>` list (~2K tokens) suitable for context injection;
the Claude (`SessionStart` in `~/.claude/settings.json`) and Codex
(`SessionStart` in `~/.codex/hooks.json`) session-start hooks call it this way
to preload the CLI-tool roster every session.

Prefer this script over ad hoc `find`/`ls` scans when a task asks which CLI
tools exist, what they do, or which README describes them.
</tool_discovery>

<quick_start>
Route to appropriate workflow based on user intent:
- Use an existing CLI / service operation → workflows/skill-router.md
- Create new CLI → workflows/create-cli.md
- Test CLI → workflows/test-cli.md
- Modify CLI → workflows/update-cli.md
- Remove CLI → workflows/remove-cli.md
- List CLIs → workflows/list-cli.md
</quick_start>

<essential_principles>
These principles apply to ALL CLI tool operations. They cannot be skipped.

<principle name="Always Use new-cli-tool Script">
**Never create CLI files manually.** Use the scaffolding script:
```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/new-cli-tool --name <name> --type <api|browser|wrapper> [options]
```
This handles: directory structure, uv tool installation (isolated venv + symlink), and placement inside the parent cli-tools monorepo.
</principle>

<principle name="Output Stream Separation">
**stdout = DATA ONLY. stderr = MESSAGES ONLY.** See `references/output-standards.md` for details.
</principle>

<principle name="Existing Path Operands Only">
Before passing optional repo paths to `rg`, `grep`, `find`, `ls`, `stat`, `cat`, `sed`, `nl`, `wc`, `head`, `tail`, or similar commands, prove each path exists or build the operand list from discovered existing paths. This applies equally to relative operands and absolute operands under `<cli-tools-root>`, including optional root children such as `<cli-tools-root>/scripts`; do not pass an absolute path just because the repo root exists. For file-reading commands such as `cat`, `sed`, `nl`, `wc`, `head`, and `tail`, filter glob and optional operands to regular files, not just existing paths; directories such as `__pycache__` are command errors. This includes personal CLI tool paths such as `_personal/<tool>/install.sh`, `_personal/<tool>/README.md`, and any other optional per-tool file. Missing optional paths are command errors, not no-match results, and wrong-kind operands are command errors too; report skipped optional paths separately instead of passing them as operands.

Shell globs used as search operands are optional paths too. Do not pass operands
such as `*/*_cli`, `tests`, or `docs` directly to `rg`; with Bash's default
glob behavior, an unmatched glob stays literal and ripgrep exits with status
`2` even if other operands produced matches. Expand the glob into an array,
keep only existing entries, and print a skipped marker for any optional root or
glob that produced no existing paths.

Do not run direct reads like `sed -n '1,260p' _personal/<tool>/install.sh`
unless that exact file has already been proven present in the same command or
by a prerequisite command whose result is in scope.
Do not run direct listings like `ls -la <tool>/.venv` unless that exact
directory has already been proven present in the same command or by a
prerequisite command whose result is in scope.
This also applies to guessed Python module paths after package layout
uncertainty, including shared package paths such as
`_repo/cli-tools-shared/cli_tools_shared/...`; discover the real file first
with an existing root and then read only the proven path.

Do not rely on a downstream pipeline stage to hide an upstream missing-operand
error. This is unsafe:

```bash
rg --files descript _repo/skills/descript-cli tests _repo | rg -F 'descript'
```

Build the operand list from paths proven to exist, print skipped optional paths,
then search only those operands:

```bash
paths=()
for path in descript _repo/skills/descript-cli tests _repo; do
  if [ -e "$path" ]; then
    paths+=("$path")
  else
    printf 'SKIPPED_MISSING_PATH: %s\n' "$path" >&2
  fi
done
if [ "${#paths[@]}" -eq 0 ]; then
  printf '%s\n' 'NO_EXISTING_PATHS'
  exit 0
fi
if rg -n -F -- 'descript' "${paths[@]}"; then
  exit 0
else
  rc=$?
  if [ "$rc" -eq 1 ]; then
    printf '%s\n' 'NO_MATCH:descript'
    exit 0
  fi
  exit "$rc"
fi
```

A no-match wrapper does not make missing operands safe. Filter optional paths
before the `rg` call, then handle `rg` status `1` only after the existing-path
operand list has been built.
</principle>

<principle name="Shape Expected No-Match Searches">
When exploratory `rg` or `grep` searches may legitimately find no match, wrap each search so status `1` prints an explicit no-match marker and exits `0`. An unguarded no-match status is a Tool Failure Protocol violation even when the missing text was expected. Do not use `|| true` unless the command immediately interprets and reports the expected no-match.

Do not chain exploratory searches to dependent file reads with `&&`, such as
`rg -n -F -- 'literal' file dir && sed -n '1,260p' file`, unless the search is
first wrapped to consume expected status `1`. A no-match result would skip the
dependent read and surface as a parent command failure instead of evidence.
</principle>

<principle name="Keep Search Operands Attached">
When composing `rg` or `grep` verification wrappers, keep every flag, pattern,
and path operand on the same physical command line unless you use explicit
backslash continuations or a shell array. Do not insert a bare newline before a
path operand; Bash treats the path as a separate command, which can produce
`Permission denied` or execute the wrong file even after the search printed a
match.
</principle>

<principle name="Search Only Bounded Source Roots">
Scope CLI-tool investigation searches to bounded source roots such as the target tool directory, `_repo/`, repo-owned skills, docs, tests, or exact files proven relevant. Do not run recursive `rg`, `grep`, or `find` over user cache/profile roots such as `/Users/adam/.npm`, `/Users/adam/.local/share`, `/Users/adam/Library`, or a whole home directory. When runtime profile or cache evidence is needed, inspect the exact known file or tool-owned profile path after proving it exists; do not discover it with a broad recursive search.
</principle>

<principle name="Safe printf Formats">
When composing CLI verification or diagnostic Bash commands, do not put leading
hyphens in the `printf` format operand unless options are terminated. Use
`printf -- '--- label ---\n'` for a literal format, or prefer
`printf '%s\n' '--- label ---'` so hyphens are data.
</principle>

<principle name="Shape Expected Live API Probes">
When a live smoke test intentionally uses fake or missing remote data to verify API wiring, wrap the command and explicitly validate the expected exit status plus the expected error marker. The wrapper must print an explicit expected-failure marker and exit `0` only for the intended response. A bare CLI command that exits non-zero is a Tool Failure Protocol violation even when the remote error was expected.

```bash
if output="$(airtable fields delete tblyZrpsEQCw20i20 fld00000000000000 --base app9uzzru5KZOImYQ --yes 2>&1)"; then
  status=0
else
  status=$?
fi
printf '%s\n' "$output"
if [ "$status" -eq 1 ] && printf '%s\n' "$output" | rg -q -F -- 'API request failed (404)'; then
  printf '%s\n' 'EXPECTED_FAILURE: fake field ID returned Airtable 404; API wiring reached the service.'
  exit 0
fi
exit "$status"
```
</principle>

<principle name="Shape Expected Mutation-Safeguard Probes">
When a negative smoke test intentionally verifies that a mutating command refuses
to run without explicit confirmation, wrap the command and explicitly validate
the expected exit status plus the exact refusal message. The wrapper must print
an explicit expected-failure marker and exit `0` only for that guard response.
A bare command such as `<tool> refunds create CAPTURE-123 --amount 4.50` that
exits non-zero is a Tool Failure Protocol violation even when the refusal is the
correct behavior.

```bash
if output="$(paypal refunds create CAPTURE-123 --amount 4.50 2>&1)"; then
  status=0
else
  status=$?
fi
printf '%s\n' "$output"
if [ "$status" -eq 1 ] && printf '%s\n' "$output" | rg -q -F -- 'Refusing to issue refund without --yes or --dry-run'; then
  printf '%s\n' 'EXPECTED_FAILURE: refund command refused to mutate without --yes or --dry-run.'
  exit 0
fi
exit "$status"
```
</principle>

<principle name="Shape Expected Auth Status Probes">
When an auth/status probe intentionally checks for an unauthenticated profile or
missing credential state, wrap the command and explicitly validate the expected
exit status plus the status evidence. The wrapper must print an explicit
expected-status marker and exit `0` only for the intended unauthenticated result.
Do not run bare commands such as `paypal auth status -t` when `authenticated:
false` or missing credentials are an expected diagnostic outcome.
Accept both YAML/text `authenticated: false` and JSON `"authenticated": false`
status evidence. This includes `copilot auth status --profile default`, which
can exit `2` while returning structured JSON with `"authenticated": false`; in
that case the wrapper should treat the result as unauthenticated status data
only after validating both the exit status and the JSON/text evidence.

```bash
if output="$(paypal auth status -t 2>&1)"; then
  status=0
else
  status=$?
fi
printf '%s\n' "$output"
if [ "$status" -eq 2 ] && printf '%s\n' "$output" | rg -q -e 'authenticated: false' -e '"authenticated"[[:space:]]*:[[:space:]]*false'; then
  printf '%s\n' 'EXPECTED_STATUS: paypal profile is unauthenticated.'
  exit 0
fi
exit "$status"
```
</principle>

<principle name="Structured CLI JSON Parsing">
When a CLI command emits JSON that another process will inspect, save stdout to
a task-workspace/temp file first, verify the command status and non-empty file,
then parse that file. Do not pipe JSON into a heredoc-backed parser that expects
stdin. In shapes like `az account list --all --output json | python3 - <<'PY'`
or `az account show --output json | python3 - <<'PY'`, the heredoc occupies
Python's stdin, so `json.load(sys.stdin)` reads empty input, Python reports
`JSONDecodeError: Expecting value: line 1 column 1 (char 0)`, and the producer
can report `Broken pipe`.

Before redirecting CLI JSON into a task-workspace artifact, create or prove the
artifact's parent directory. For explicit agent workspaces, run
`mkdir -p "$workspace"` before `>"$workspace/<name>.json"`; a missing parent
directory is a command-composition failure, not CLI output evidence.

Use this shape instead:
```bash
json_file=$(mktemp -t cli-json)
if az account show --output json >"$json_file"; then
  python3 - "$json_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
print(data["name"])
PY
else
  rc=$?
  printf 'PRODUCER_FAILED: az account show rc=%s\n' "$rc" >&2
  exit "$rc"
fi
```

For API or CLI response verification, inspect or validate the JSON contract
before indexing, slicing, or selecting nested keys. Do not assume shapes such as
every `GET /api/providers` item having a top-level `config` key, or a CLI
`list` command's parsed root being sliceable, until the saved JSON proves the
container type. Check the container type and required paths explicitly; if the
contract is missing, fail with `MISSING_JSON_PATH: providers[0].config` or
`JSON_CONTRACT_MISMATCH: expected list root, got object keys=[...]` instead of
a raw `KeyError`, `TypeError`, or `rows[:10]` failure.

Treat the parser as its own batch stage. Capture and return the parser status
before running later update, cleanup, summary, or verification commands, or
carry it into a `batch_rc` that becomes the final exit status. Do not let a
later successful CLI command mask a failed JSON parser.
</principle>

<principle name="Literal Searches For Template Tokens">
When searching for CLI template tokens or copied text containing braces,
backticks, dollar signs, parentheses, or other regex metacharacters, use
literal matching: `rg -n -F -- '{{description}}' <existing-path>`. Do not pass
tokens such as `{{name}}`, `{{description}}`, or `{{AUTH_IMPORT}}` as regex
patterns unless every regex metacharacter is intentionally escaped.

Keep CLI skill and `usage.json` inspection searches line-local unless a real
cross-line match is deliberately required. Do not use Hermes `search_files` or
plain `rg` with a pattern containing a literal `\n` escape such as
`"list": \{\n\s+"help"`; ripgrep rejects that without multiline mode, and
`search_files` has no multiline flag. Prefer separate fixed-string probes for
single-line anchors, or read the bounded JSON/Markdown section and inspect the
adjacent lines directly. Use `rg -U` only in a shell probe where multiline
matching is intentional and explicitly stated.
</principle>

<principle name="Per-Tool Project Config Discovery">
CLI tool project configs live under each tool directory. Do not assume `<cli-tools-root>/pyproject.toml` exists. Do not assume `<cli-tools-root>/<tool>/pyproject.toml` or `<cli-tools-root>/_personal/<tool>/pyproject.toml` exists either. When inspecting dependencies, pytest configuration, package metadata, or a test runner for a named CLI, discover `<cli-tools-root>/<tool>/pyproject.toml` from the target tool directory, keep only proven regular files, and read it only after that exact file path exists. If discovery shows no project config exists, report `CONFIG_ABSENT: <tool>` and do not issue `sed`, `cat`, `nl`, `wc`, `head`, or `tail` against the absent path.
</principle>

<principle name="Filtering Architecture">
**Every `list` command MUST support `--filter`/`-f`. No dedicated filter commands.** See `references/filtering.md` for architecture.
</principle>

<principle name="API-First for Web Interactions">
**Investigate public API, then internal APIs.** If neither provides a usable
path and the requested command would require browser automation, stop before
scaffolding or implementation and ask Adam: "No usable public or internal API
path is available for this action. Should I make this command browser-driven?"
Continue only after explicit approval. See `references/templates.md` for type
details.
</principle>

<principle name="CLI-Tools Secret Manager">
**Any reusable human-supplied secret for a CLI tool belongs in the CLI-tools secret manager.** Follow `references/secrets.md` before asking Adam for CLI credentials or storing new CLI credentials. Do not instruct users or agents to place reusable credentials in any `.env` file. `.env` files are limited to non-secret config and CLI-managed runtime auth state under `~/.local/share/cli-tools/...`.
</principle>

<principle name="User Profile Folder">
The tool user profile folder is `~/.local/share/cli-tools/<tool>`. Non-authentication configuration lives in `~/.local/share/cli-tools/<tool>/.env`, never in the source tree.

Authentication-related runtime state lives under `~/.local/share/cli-tools/<tool>/authentication_profiles/<profile>/`, including the profile `.env`, tokens, browser session data, auth markers, and auth-tied cache/state; see `references/config-standards.md`.

Agents must not tell users to manually place reusable credentials in those `.env` files. Use the CLI-tools secret manager for raw credentials and let the CLI persist only its own runtime state.
</principle>

<principle name="Browser Profile Process Cleanup">
Do not clear stale browser profile processes with ad hoc shell filters such as
`ps | awk` plus `kill`. Browser profile cleanup must go through the shared
`cli_tools_shared.browser.processes.profile_process_pids` helper or an existing
CLI/shared cleanup path that uses it. That helper matches the explicit Chrome
`--user-data-dir` value, skips zombies, and excludes the current process
ancestry so a wrapper command that mentions the profile path cannot kill itself.

If a CLI needs a new cleanup command or repair path, add it at the shared helper
or CLI command layer and cover it with tests. Do not hand-run profile-path PID
filters against `~/.local/share/cli-tools/<tool>/authentication_profiles/...`.
</principle>

<principle name="Fresh File Snapshots Before Patching">
After any scaffolding script, installer, validation script, formatter, cleanup command, or subagent may have changed a file, reread that exact file before preparing an `apply_patch` hunk for it. Patch against the current on-disk content, not a remembered template or earlier read. Build each hunk from a current on-disk line plus verified surrounding context. If copied failure text, plan prose, or expected converted text is not present as its own current line, do not use it as a standalone patch anchor; choose a verified heading or current line instead.
</principle>

<principle name="Browser Parser Validation (MANDATORY)">
**NEVER write browser parsers from guesswork.** Validate every parser against real DOM snapshots captured via the BrowserAutomation page. See `references/templates.md` for browser CLI workflow.
</principle>

<principle name="Output Contract First Architecture">
**The documented Typer commands and stdout shape are the contract.** Internal models, helper modules, and dependencies are optional implementation details. Use the smallest clear code that preserves command names, options, exit behavior, auth behavior, and JSON/table output. Plain dict records are acceptable when they directly represent the external output. See `references/model-standards.md` for details.
</principle>

<principle name="AI Instruction Results">
When a deterministic command reaches a boundary that requires AI judgment, return the shared `AIInstruction` model as JSON on stdout using `print_ai_instruction()`. Do not call an LLM from inside the CLI, do not emit plain-text instructions, and do not include required pre-action commands. Optional verification or follow-up commands are allowed only after the AI agent completes the instruction. See `references/output-standards.md`, `references/model-standards.md`, and `references/templates.md`.
</principle>

<principle name="Use the CLI's Own Interpreter for Manual Imports">
**Every uv-installed CLI has its own isolated interpreter at `~/.local/share/uv/tools/<pkg-name>/bin/python3`.** The launcher at `~/.local/bin/<cli>` has a shebang that points to it. Running `python3 -c "import <cli>_cli.main"` or `python3 - <<'PY'` with ANY other interpreter (system python, Homebrew python, the test venv) will fail with `ModuleNotFoundError` because the CLI's dependencies are installed ONLY in that uv tool venv. Those failures are NOT CLI bugs — they are wrong-interpreter diagnoses.

**Rule:** For any ad-hoc import/smoke test of a CLI's modules, inspect the live launcher and use the interpreter from its shebang. Do not derive the uv tool path from the command name. This also applies to task-workspace scripts that import CLI packages or internals such as `<pkg>_cli.commands`; run those scripts with the launcher shebang interpreter instead of ambient `python3`.

When writing a task-workspace Python script that intentionally imports installed
CLI internals, make the runtime contract visible in the source. Prefer a shebang
that points at `/usr/bin/env <cli>` only when the CLI itself executes Python
files; otherwise include a header comment naming the launcher-derived interpreter
that must run the script. If Hermes/Pyright reports `reportMissingImports` for
that intentional CLI-internal import because the editor interpreter is not the
launcher interpreter, suppress only that import line (for example
`from <pkg>_cli.client import get_client  # pyright: ignore[reportMissingImports]`).
Do not add brittle `sys.path` bootstraps into ad-hoc scripts just to satisfy the
editor; they can make the script run against a different source checkout than the
installed CLI launcher uses.

```bash
launcher="$(command -v <cli>)"
interpreter="$(head -1 "$launcher" | sed 's/^#!//')"
"$interpreter" -c "import <pkg>_cli.main"
"$interpreter" path/to/task_script_that_imports_cli.py
```

For heredoc probes, the heredoc target must be the same shebang interpreter;
never write the probe as a bare `python3 - <<'PY'` from inside a CLI source
directory:

```bash
launcher="$(command -v <cli>)"
interpreter="$(head -1 "$launcher" | sed 's/^#!//')"
"$interpreter" - <<'PY'
import <pkg>_cli.main
PY
```

The shebang interpreter only proves you are in the installed CLI environment;
it does not prove an internal module path exists. Before importing non-entrypoint
internals such as auth helpers or client factories, verify the source layout or
use `importlib.util.find_spec()` with the shebang interpreter. Do not assume a
module named `<pkg>_cli.auth` exists. In scaffolded CLIs, command auth is often
mounted from `cli_tools_shared.auth_commands`, and client factories commonly
live in `<pkg>_cli.client`.

When inspecting source-defined mappings, registries, or constants from an
installed CLI module, enumerate the live keys first and index only those exact
keys. Do not normalize table, command, or resource names to guessed lowercase,
snake_case, or singular forms before looking them up.

This interpreter rule is only for ad-hoc imports and direct config probes. Do
not use the installed CLI interpreter to run a tool's pytest suite. The uv tool
venv (from `uv tool install`) contains runtime dependencies, not test-only
dependencies such as `pytest`.

Every CLI must declare `pytest` as a dev dependency so `uv sync` installs it
into the project `.venv`. Use the scaffold convention:

```toml
[dependency-groups]
dev = [
    "pytest>=7.0.0",
]
```

Once that group is declared and synced, run the suite through the project venv
interpreter — `uv run pytest` (from the tool dir) or `.venv/bin/python -m
pytest`. Both resolve the project `.venv`, where editable `cli-tools-shared`
imports cleanly. Never run a bare global `pytest`: when `pytest` is absent from
the project `.venv`, `uv run pytest` silently falls back to the global pipx
pytest, whose interpreter cannot import editable `cli-tools-shared`, so test
modules fail collection with `ModuleNotFoundError: No module named
'cli_tools_shared'`.

For focused per-tool tests (and as a fallback for any tool whose dev group is
not yet synced), use the direct pytest command in `workflows/test-cli.md`, which
injects pytest into the run with `--with pytest`:

```bash
uv run --project <cli-tools-root>/$TOOL_NAME --with pytest python -m pytest <cli-tools-root>/$TOOL_NAME/tests
```

Do not use a source-checkout `uv run --project ... python -` heredoc for
Playwright or dependency availability probes. Those probes are installed-runtime
checks, so use the live launcher shebang interpreter and redirect stdout/stderr
to bounded task-workspace files before printing a short summary:

```bash
workspace=/path/to/task-workspace
mkdir -p "$workspace"
launcher="$(command -v paypal)"
interpreter="$(head -1 "$launcher" | sed 's/^#!//')"
stdout="$workspace/paypal_playwright_probe.stdout"
stderr="$workspace/paypal_playwright_probe.stderr"
if "$interpreter" - >"$stdout" 2>"$stderr" <<'PY'
import playwright
print("PLAYWRIGHT_AVAILABLE")
PY
then
  status=0
else
  status=$?
fi
printf 'STATUS:%s STDOUT_BYTES:%s STDERR_BYTES:%s\n' "$status" "$(wc -c <"$stdout")" "$(wc -c <"$stderr")"
head -c 500 "$stdout"
printf '\n'
exit "$status"
```

When probing a CLI source checkout rather than the installed launcher, use that
tool's `pyproject.toml` environment so editable sources such as
`cli-tools-shared` resolve, but still keep parent output bounded.

For any tool-scoped Python introspection against source files, run
`uv run --project <tool-dir> python ...` from the target tool environment. Do
not run system `python3` or bare `python` from inside `_personal/<tool>` or
another tool source directory. For PayPal source probes and tests, do not print
unbounded `uv run` output directly to the parent tool result:

```bash
workspace=/path/to/task-workspace
mkdir -p "$workspace"
stdout="$workspace/paypal_source_probe.stdout"
stderr="$workspace/paypal_source_probe.stderr"
if uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/paypal python - >"$stdout" 2>"$stderr" <<'PY'
from paypal_cli.config import get_config
print(get_config().env_file_path)
PY
then
  status=0
else
  status=$?
fi
printf 'STATUS:%s STDOUT_BYTES:%s STDERR_BYTES:%s\n' "$status" "$(wc -c <"$stdout")" "$(wc -c <"$stderr")"
head -c 500 "$stdout"
printf '\n'
exit "$status"
```

Do not run `"$interpreter" -m pip ...` inside a uv tool venv for package
metadata diagnostics. uv tool environments may not include `pip`. Use
`importlib.metadata` from the launcher shebang interpreter instead, and read
editable source data from `direct_url.json` through the returned package file:

```bash
"$interpreter" - <<'PY'
import json
from importlib import metadata

dist = metadata.distribution("<distribution-name>")
print(dist.version)
direct_url = next((f for f in dist.files or [] if str(f).endswith("direct_url.json")), None)
if direct_url is not None:
    print(json.loads(direct_url.read_text())["url"])
PY
```

For multi-profile CLIs, direct config probes must also pass an explicit profile:

```bash
"$interpreter" -c "from <pkg>_cli.config import get_config; print(get_config(profile='<profile>').env_file_path)"
```

Do not expect per-tool shell variables such as `JIRA_PROFILE` or a generic `CLI_TOOLS_PROFILE` environment variable to select the profile for an ad-hoc Python probe. The CLI runtime resolves profiles through explicit `--profile` handling and internal runtime overrides, not ambient shell env vars.

`validate-cli-tool.sh` and the pytest `test_launcher_shebang_points_to_uv_tool_python` check enforce this shebang is correct. If they fail, reinstall with `uv tool install -e <cli-dir> --force --refresh`. See `references/common-issues.md` for details (including the CWD / sys.path wrinkle when editing source).
</principle>

<principle name="Update cli_tools.md After Creation">
After creating a CLI tool, you MUST update `<cli-tools-root>/_repo/docs/cli_tools.md`:
- Find the CLI tools table
- Add the new tool row in alphabetical order
- Document: command name and description
</principle>

<principle name="Usage JSON Lives In The CLI Skill">
**The canonical `usage.json` for a service CLI lives in its repo-owned skill
folder:** `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json`.

Do not look for the command map in the CLI source folder, package folder,
runtime profile folder, or installed uv tool directory. Service-operation agents
must load `<cli-tools-root>/_repo/skills/<tool>-cli/SKILL.md` and consult the
adjacent `usage.json` before running that CLI. CLI lifecycle workflows that
change commands or parameters must refresh that same skill-folder `usage.json`.
Use `<cli-tools-root>/_repo/skills/cli-tool/scripts/regenerate-usage-json
<tool>` to refresh it; do not import `cli_test_utils` from ad-hoc Python.
</principle>

<principle name="Schema-Safe Usage JSON Inspection">
When programmatically inspecting one or more `usage.json` files, identify the
tool from the parent skill directory, not from the filename; every command map
file is named `usage.json`. First run a bounded schema probe that prints the
root type, root keys, and `commands` keys; for deeper command paths, print only
the current node type and keys before indexing. When a `jq` key is not a valid
identifier, including keys with hyphens such as `replace-section`, use bracket
notation such as `.commands.pages.commands.content.commands["replace-section"]`
instead of dot notation. When filtering `to_entries` rows against a side array
or lookup map, bind the current row before piping into the side data; jq changes
`.` to the side value inside that pipeline. Use
`map(. as $entry | select($actions | index($entry.key)))`, not
`map(select($actions | index(.key)))`, because the latter evaluates `.key`
against `$actions`.
Avoid full-map dumps, recursive walks, interactive
extractors, or probes that can block or emit excessive output. Before
dereferencing a nested command path, inspect the available keys
at the current level and fail clearly with `MISSING_JSON_PATH:
commands.<group>.<subcommand>` when the path is absent. Generated command
groups nest children under a `commands` object at each level, so a subcommand
path alternates group name and `commands`: use
`.commands.gmail.commands.labels.commands.add`, not
`.commands.gmail.labels.add` or `.commands.gmail.labels.commands.add`, after
the parent keys have been inspected. Do not assume command groups,
subcommands, or fields such as `name` exist from memory or from another tool's
map.
In Python helpers, validate the container before membership checks: do not run
`if key in node` until `node` has been proven to be a dict. A missing child is
a contract error, not `None`; fail with the full alternating command path and
available keys, for example `MISSING_JSON_PATH:
commands.items.commands.search available=[create,get,list,password,username]`.

Usage nodes can omit documentation-only fields such as `examples` even when
they include `options`. Before reading `node["examples"]`, inspect the node's
keys and treat examples as optional with `node.get("examples", [])`; reserve
`MISSING_JSON_PATH` failures for fields required by the usage contract.
Usage node metadata fields can also use different containers across commands:
`options` may be a list of option records, not an object. Before calling object
methods such as `.keys()` or iterating entries, inspect the field type and
handle the actual container; fail clearly with `JSON_CONTRACT_MISMATCH:
commands.<path>.options expected object/list got <type>` for unsupported
shapes.
</principle>

<principle name="⛔ Zero Test Failures Policy">
**ALL test-cli-tool.sh failures MUST be fixed. No exceptions.**

- **Do not skip, ignore, or rationalize** any test failure
- **Fix every `[FAIL]`** in the test output before marking work complete
- **Re-run tests** until output shows all tests passed
- **Warnings are acceptable** - only failures block completion
- **No special cases** - wrapper CLIs, passthrough patterns, and all other CLI types must pass all tests

**Required command options for compliance:**
- `list` commands: `--table/-t`, `--limit/-l`, `--filter/-f`, `--properties/-p`
- `get` commands: `--table/-t`
- `auth login`: `--force/-F` (when auth commands are present)
- `auth status`: Must output JSON in the per-profile, per-credential-type shape emitted by `create_auth_app`:
  `{"profiles":[{"name","auth_type","active","authenticated","credential_types":{"<type>":{"credentials_saved","authenticated",...}}}]}`.
  Use the shared `cli_tools_shared.auth_commands.create_auth_app` — no custom `auth_status` function unless the CLI is genuinely exceptional (see `references/auth-standards.md`).
- README: Must document ALL commands with examples

**Note:** Auth commands are optional for some CLI types (wrapper, browser, `--auth-type none`). If a CLI has no `auth` subcommand, auth tests are automatically skipped.
</principle>
</essential_principles>

<intake>
Route to appropriate workflow based on user intent. If intent is clear from the user's message (e.g., "create a CLI for Stripe", "test the notion CLI"), route directly without asking.

If ambiguous, ask:
1. **Create** a new CLI tool
2. **Test** an existing CLI tool
3. **Update** an existing CLI tool
4. **Remove** a CLI tool
5. **List** all CLI tools
</intake>

<routing>
| Response | Workflow | Description |
|----------|----------|-------------|
| service operation, "run", "execute", "<tool> cli", existing CLI command | workflows/skill-router.md | Select and load the repo-owned service skill |
| 1, "create", "new", "build", "make" | workflows/create-cli.md | Full creation workflow |
| 2, "test", "validate", "check" | workflows/test-cli.md | Run test suite and AI review |
| 3, "update", "modify", "change", "add command", "fix" | workflows/update-cli.md | Modify existing CLI |
| 4, "remove", "delete", "uninstall" | workflows/remove-cli.md | Remove CLI tool |
| 5, "list", "show all", "which CLIs" | workflows/list-cli.md | List all CLI tools |
| other | Clarify intent, then route |

**Intent-based routing (if user provides clear context):**
- "create a CLI for Stripe" → workflows/create-cli.md
- "test the notion CLI" → workflows/test-cli.md
- "add a new command to airtable CLI" → workflows/update-cli.md
- "remove the podio CLI" → workflows/remove-cli.md
- "list all my CLIs" → workflows/list-cli.md

**After reading the workflow, follow it exactly.**
</routing>

<reference_index>
All domain knowledge in `references/`:

**Output:** output-standards.md (streams, format rules, truncation, field selection, list requirements)
**Secrets:** secrets.md (CLI-tools secret manager, naming, storage/retrieval rules, prohibited stores)
**Auth:** auth-standards.md (credential types, multi-auth, OAuth, force flag, wrapper auth)
**Config:** config-standards.md (.env, path resolution, token refresh)
**Commands:** command-standards.md (naming, options, CRUD patterns, list/get, search, exit codes)
**Data Shapes:** model-standards.md (when to use local models, plain records, AIInstruction, SerializeAsAny)
**Infrastructure:** infra-standards.md (AI review, logging, repos, docs, symlinks)
**Templates:** templates.md (API, browser, wrapper structures, lean architecture, file responsibilities)
**Filtering:** filtering.md (filters.py, filter_map.py architecture)
**Caching:** caching.md (@cached decorator, cache commands, env config, serialization, integration steps)
**Troubleshooting:** common-issues.md (quick fixes for common problems)
</reference_index>

<workflows_index>
| Workflow | Purpose |
|----------|---------|
| skill-router.md | Route an existing CLI/service operation to its repo-owned service skill |
| create-cli.md | Create a new CLI tool from scratch |
| test-cli.md | Run compliance tests and AI review |
| update-cli.md | Modify an existing CLI tool |
| remove-cli.md | Remove a CLI tool and all artifacts |
| list-cli.md | List all CLI tools with status |
</workflows_index>

<quick_reference>
**CLI Types:**
- `api` - REST API clients
- `browser` - Web automation using `BrowserAutomation`, named sessions, and `BaseConfig`
- `wrapper` - Wraps existing CLI tools through subprocess calls

**Auth Types (for `--auth-type` flag on `new-cli-tool`, repeatable for multiple types):**
- `none` - No auth (skips auth command scaffolding entirely)
- `api_key` - API key auth (env var: `API_KEY`) [default for api type]
- `personal_access_token` - PAT auth (env var: `PERSONAL_ACCESS_TOKEN`)
- `oauth` - OAuth 2.0 (env vars: `CLIENT_ID`, `CLIENT_SECRET`, `ACCESS_TOKEN`)
- `oauth_authorization_code` - OAuth auth code flow (env vars: `CLIENT_ID`, `CLIENT_SECRET`, `ACCESS_TOKEN`, `REDIRECT_URI`)
- `username_password` - Basic auth (env vars: `USERNAME`, `PASSWORD`)
- `browser_session` - Browser session (no env vars; stores session in profile) [default for browser type]

**Data Shape Structure (Optional):**
```
models.py or models/
└── only when validation, polymorphism, or serialization logic earns the code
```

Omit local models when parsed/API records can flow straight to the documented output. If a command group only needs credential metadata because the command logic is centralized in `main.py`, keep `commands/<group>.py` to a module docstring plus one `COMMAND_CREDENTIALS` assignment.

**Script Locations:**
- Scaffolding: `<cli-tools-root>/_repo/skills/cli-tool/scripts/new-cli-tool`
- CLI Tools: `<cli-tools-root>/`
- Validate: `<cli-tools-root>/_repo/skills/cli-tool/scripts/validate-cli-tool.sh`
- Install: `<cli-tools-root>/_repo/skills/cli-tool/scripts/install-cli-tool.sh`
- Test: `<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh`
- Remove: `<cli-tools-root>/_repo/skills/cli-tool/scripts/remove-cli-tool.sh`
- List: `<cli-tools-root>/_repo/skills/cli-tool/scripts/list-cli-tool.sh`

**Template Locations:**
- Templates: `<cli-tools-root>/_repo/skills/cli-tool/templates/` (api/, browser/, wrapper/)
- README Template: `<cli-tools-root>/_repo/skills/cli-tool/templates/README_TEMPLATE.md`

**Common Commands:**
```
<cli-tools-root>/_repo/skills/cli-tool/scripts/new-cli-tool --name myservice --type api --base-url https://api.example.com
<cli-tools-root>/_repo/skills/cli-tool/scripts/new-cli-tool --name myservice --type api --base-url https://api.example.com --auth-type personal_access_token
<cli-tools-root>/_repo/skills/cli-tool/scripts/new-cli-tool --name mysite --type browser --base-url https://mysite.com
<cli-tools-root>/_repo/skills/cli-tool/scripts/new-cli-tool --name mysite --type browser --base-url https://mysite.com --auth-type oauth --auth-type browser_session
<cli-tools-root>/_repo/skills/cli-tool/scripts/new-cli-tool --name myservice --type wrapper --cli-command original-cmd
<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name myservice --verbose
```
</quick_reference>

<domain_knowledge>
<topic name="Typer Dependency Extras">
**Context:** Use this when creating or updating Python CLI tool `pyproject.toml` dependencies.
**Key Facts:** Current Typer releases no longer expose the legacy `all` extra, so CLI tools should depend on `typer>=0.9.0` instead of `typer>=0.9.0`. The stale extra produces `uv` warnings during `uv run` and `uv tool install`, even though installation continues.
**Gotchas:** If the warning appears while installing one CLI, inspect both that CLI and `cli-tools-shared`; transitive package metadata can be the source. After changing shared dependency metadata, refresh the dependent CLI install with `uv tool install -e . --force --refresh` so it resolves the new `cli-tools-shared` commit.
</topic>

</domain_knowledge>

<success_criteria>
A successful skill invocation:
- Routes to the correct workflow based on user intent
- Loads appropriate references when needed
- Follows workflow steps exactly
- Preserves the documented command/output contract with the smallest clear implementation
- Removes unused local helpers, local models, and direct dependencies
- Meets workflow-specific success criteria
- Updates cli_tools.md for new CLI tools
- Runs `_repo/skills/cli-tool/scripts/create-cli-tool-skill <name>` after successful CLI creation
- **⛔ Passes test-cli-tool.sh with ZERO FAILURES** (warnings acceptable)

**BLOCKING: Do NOT mark any CLI work as complete if test-cli-tool.sh shows failures.**
</success_criteria>
