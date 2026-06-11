---
name: cli-tool
description: >-
  MANDATORY: CLI tool skill router for ALL cli-tools requests. Use this skill
  first for any available CLI tool, service CLI operation, CLI command
  execution, or CLI lifecycle work. DO NOT run cli-tools commands, guess
  command syntax, or load individual <tool>-cli skills directly before this
  router selects them. For service operations, route through
  workflows/skill-router.md to <cli-tools-root>/_repo/skills/<tool>-cli/SKILL.md
  and the adjacent usage.json. For lifecycle work, delegate to cli-tool-expert
  and use this skill's lifecycle workflows. Triggers: any cli tool, cli
  command, service cli, <tool> cli, run cli, execute cli, create cli, update
  cli, test cli, fix cli, add command, list cli tools, cli standards.
---

<objective>
Route every cli-tools request to the correct repo-owned CLI skill or lifecycle workflow, then execute against the real command contract.
</objective>

<agent_routing>
Service-operation routing stays in the current session: use `workflows/skill-router.md`, then load the selected service skill and its adjacent `usage.json`.

When this skill is invoked for CLI lifecycle work by a parent agent session and the current agent is not `cli-tool-expert`, delegate the lifecycle work to `cli-tool-expert` instead of performing CLI implementation work inline. Pass the complete user request, relevant file paths, constraints, and required validation.

When the current agent is `cli-tool-expert`, follow this skill normally.
</agent_routing>

<skill_router>
The repo-owned source of truth for CLI service skills is `<cli-tools-root>/_repo/skills`.

Classify skills by ownership and domain, not by whether they call a CLI as an
implementation detail. Service CLI skills and CLI lifecycle workflows live under
`<cli-tools-root>/_repo/skills`; project-specific workflows that merely call a
CLI belong to the target project's skill scope.

For any request that uses an existing CLI tool, read `workflows/skill-router.md` before selecting a service skill. The selected service skill's `SKILL.md` and adjacent `usage.json` are mandatory before running any command.
</skill_router>

<tool_discovery>
Use `<cli-tools-root>/_repo/scripts/find-cli-tools.sh` to enumerate the
available CLI tools from the source tree. The script prints JSON records with
`name`, `readme`, and `description`, where `description` is extracted from each
tool README's `## DESCRIPTION` block.

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
Before passing optional repo paths to `rg`, `grep`, `find`, `cat`, `sed`, `nl`, `wc`, `head`, `tail`, or similar commands, prove each path exists or build the operand list from discovered existing paths. Missing optional paths are command errors, not no-match results; report skipped optional paths separately instead of passing them as operands.
</principle>

<principle name="Shape Expected No-Match Searches">
When exploratory `rg` or `grep` searches may legitimately find no match, wrap each search so status `1` prints an explicit no-match marker and exits `0`. An unguarded no-match status is a Tool Failure Protocol violation even when the missing text was expected. Do not use `|| true` unless the command immediately interprets and reports the expected no-match.
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

<principle name="Literal Searches For Template Tokens">
When searching for CLI template tokens or copied text containing braces,
backticks, dollar signs, parentheses, or other regex metacharacters, use
literal matching: `rg -n -F -- '{{description}}' <existing-path>`. Do not pass
tokens such as `{{name}}`, `{{description}}`, or `{{AUTH_IMPORT}}` as regex
patterns unless every regex metacharacter is intentionally escaped.
</principle>

<principle name="Per-Tool Project Config Discovery">
CLI tool project configs live under each tool directory. Do not assume `<cli-tools-root>/pyproject.toml` exists. When inspecting dependencies, pytest configuration, package metadata, or a test runner for a named CLI, discover `<cli-tools-root>/<tool>/pyproject.toml` or another existing config file from that tool directory and read it only after that exact file path exists.
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
**Every uv-installed CLI has its own isolated interpreter at `~/.local/share/uv/tools/<pkg-name>/bin/python3`.** The launcher at `~/.local/bin/<cli>` has a shebang that points to it. Running `python3 -c "import <cli>_cli.main"` with ANY other interpreter (system python, Homebrew python, the test venv) will fail with `ModuleNotFoundError` because the CLI's dependencies are installed ONLY in that uv tool venv. Those failures are NOT CLI bugs — they are wrong-interpreter diagnoses.

**Rule:** For any ad-hoc import/smoke test of a CLI's modules, inspect the live launcher and use the interpreter from its shebang. Do not derive the uv tool path from the command name.

```bash
launcher="$(command -v <cli>)"
interpreter="$(head -1 "$launcher" | sed 's/^#!//')"
"$interpreter" -c "import <pkg>_cli.main"
```

This interpreter rule is only for ad-hoc imports and direct config probes. Do
not use the installed CLI interpreter to run a tool's pytest suite. The uv tool
venv contains runtime dependencies, not test-only dependencies such as
`pytest`. For focused per-tool tests, use the direct pytest command in
`workflows/test-cli.md`:

```bash
uv run --project <cli-tools-root>/$TOOL_NAME --with pytest python -m pytest <cli-tools-root>/$TOOL_NAME/tests
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
file is named `usage.json`. Before dereferencing a nested command path, print
or otherwise inspect the available keys at the current level. Do not assume
command groups, subcommands, or fields such as `name` exist from memory or from
another tool's map.
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
- Invokes `/create-cli-tool-skill` after successful CLI creation
- **⛔ Passes test-cli-tool.sh with ZERO FAILURES** (warnings acceptable)

**BLOCKING: Do NOT mark any CLI work as complete if test-cli-tool.sh shows failures.**
</success_criteria>
