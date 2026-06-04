---
name: cli-tool
description: >-
  MANDATORY: SUPPORTING SKILL for cli-tool-expert. Parent sessions must
  delegate CLI tool lifecycle work to the cli-tool-expert agent. DO NOT
  perform CLI lifecycle work inline outside cli-tool-expert. When loaded
  inside cli-tool-expert, creates, tests, updates, removes, and lists Python
  CLI tools in <cli-tools-root> using standardized templates and
  patterns. Triggers: create cli, new cli, test cli, fix cli, add command,
  cli standards.
---

<objective>
Create, test, update, remove, and list Python CLI tools in <cli-tools-root> using standardized templates and patterns.
</objective>

<agent_routing>
When this skill is invoked by a parent agent session and the current agent is not `cli-tool-expert`, delegate the work to `cli-tool-expert` instead of performing CLI lifecycle work inline. Pass the complete user request, relevant file paths, constraints, and required validation.

When the current agent is `cli-tool-expert`, follow this skill normally.
</agent_routing>

<quick_start>
Route to appropriate workflow based on user intent:
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

<principle name="Filtering Architecture">
**Every `list` command MUST support `--filter`/`-f`. No dedicated filter commands.** See `references/filtering.md` for architecture.
</principle>

<principle name="API-First for Web Interactions">
**Investigate public API, then internal APIs, then browser automation as last resort.** See `references/templates.md` for type details.
</principle>

<principle name="CLI-Tools Secret Manager">
**Any reusable human-supplied secret for a CLI tool belongs in the CLI-tools secret manager.** Follow `references/secrets.md` before asking Adam for CLI credentials or storing new CLI credentials. Do not instruct users or agents to place reusable credentials in any `.env` file. `.env` files are limited to non-secret config and CLI-managed runtime auth state under `~/.local/share/cli-tools/...`.
</principle>

<principle name="User Profile Folder">
The tool user profile folder is `~/.local/share/cli-tools/<tool>`. Non-authentication configuration lives in `~/.local/share/cli-tools/<tool>/.env`, never in the source tree.

Authentication-related runtime state lives under `~/.local/share/cli-tools/<tool>/authentication_profiles/<profile>/`, including the profile `.env`, tokens, browser session data, auth markers, and auth-tied cache/state; see `references/config-standards.md`.

Agents must not tell users to manually place reusable credentials in those `.env` files. Use the CLI-tools secret manager for raw credentials and let the CLI persist only its own runtime state.
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

**Rule:** For any ad-hoc import/smoke test of a CLI's modules, use the uv tool venv's python directly:

```bash
/Users/<user>/.local/share/uv/tools/<pkg-name>/bin/python3 -c "import <pkg>_cli.main"
```

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
