# Working Agreement

Load and follow `$cody` at the start of every conversation. Cody identity, email, Slack, bridge, project-manager, scheduling, and durable-learning details live in that skill; keep this file focused on this repo.

Load and follow `$continuous-agent-learning` for every conversation. When reusable workflow knowledge changes, fix the owning source after the task is complete and verified.

Use `$agentsmd-expert` before editing this file or any nested `AGENTS.md` file.

## Repo Map

- This is the parent monorepo for CLI tools. Treat `/Users/adam/Dropbox/GitRepos/cli-tools` as the source of truth.
- Each service CLI lives in `<tool>/` with `pyproject.toml`, a `<tool>_cli/` package, optional tests/docs, and an optional `uv.lock`.
- Shared runtime code lives in `_repo/cli-tools-shared/`.
- Repo-level scripts, templates, docs, skills, agents, and the CLI-tools secret manager live under `_repo/`.
- Do not recreate retired root folders such as `skills/`, `_scripts/`, `_templates/`, `_secret-manager/`, or `cli-tools-shared/`; use their `_repo/` locations.
- Child tool folders must not contain nested `.git` metadata. This repo has one git root.

## Commands

- Install or refresh one tool: `_repo/_scripts/install-cli-tool.sh <tool-folder>`.
- Create, validate, test, list, or remove tools through the repo-owned CLI lifecycle scripts under `_repo/skills/cli-tool/scripts/`.
- Validate a single tool with `_repo/skills/cli-tool/scripts/validate-cli-tool.sh <tool-name>` or `_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name <tool-name>` as appropriate.
- Test shared runtime changes from `_repo/cli-tools-shared/` with `uv run pytest`.
- Refresh the catalog after tool metadata changes with `_repo/_scripts/refresh_readme.sh`.

## CLI Tool Work

- For CLI lifecycle work, use the `$cli-tool` skill. Parent sessions should delegate implementation, creation, testing, or removal work to the `cli-tool-expert` agent instead of doing it inline.
- Before invoking, creating, or updating any subagent, load `$agent-expert`.
- Every subagent prompt must be self-contained, must not use `fork_context`, and must explicitly reference `/Users/adam/Dropbox/.agents/skills/agent-expert/references/global-standards.md`.
- Use the scaffolding script for new tools; do not hand-create a tool package from scratch.
- Use the installed tool launcher or the tool's uv interpreter for smoke tests. Do not diagnose uv-installed packages with an unrelated system Python interpreter.

## Tool Contracts

- JSON is the default output. Do not add redundant `--json` flags.
- stdout is for data only. stderr is for progress, warnings, and confirmations.
- `get` commands return the resource object. `list` commands return the resource array.
- Command groups use noun-verb Typer structure, such as `orders list` and `orders get`.
- Every `list` command must support `--table/-t`, `--limit/-l`, `--filter/-f`, and `--properties/-p`.
- API-backed tools expose `auth login`, `auth status`, and `auth logout` when authentication is required.
- Browser-backed tools must use shared browser/profile helpers from `cli-tools-shared`; validate parsers against real captured pages instead of guessing at DOM structure.
- Credentials belong in the CLI-tools secret manager or tool-owned profile/config paths, never in source files.

## Development Rules

- Keep changes small and source-focused. Fix root causes instead of adding fallback paths or compatibility branches for bad data.
- Do not add fallback values, alternate execution paths, or defensive handling for states that should not exist.
- Verify third-party SDK and package APIs against the installed package before implementing against them.
- When installing or changing third-party dependencies, check the current stable package version first and update lockfiles intentionally.
- Preserve existing uncommitted work you did not create. Do not revert unrelated changes in this repo.

## Done When

- Relevant validation or tests pass with zero failures.
- Installed launcher smoke tests pass for behavior that depends on uv tool installation.
- Shared-package changes are verified against at least one affected consumer when the change affects installed CLI behavior.
- README or `_repo/docs/cli_tools.md` is updated when tool command metadata or catalog content changes.
- Any instruction, skill, or agent source updates are reported in the final summary.
