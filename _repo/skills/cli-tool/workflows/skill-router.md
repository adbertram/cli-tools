<objective>
Route an existing cli-tools service operation to the repo-owned service skill that owns the requested CLI command.
</objective>

<skill_locations>
- Router skill: `<cli-tools-root>/_repo/skills/cli-tool/SKILL.md`
- Service skills: `<cli-tools-root>/_repo/skills/<service-skill-dir>/SKILL.md`
- Command maps: `<cli-tools-root>/_repo/skills/<service-skill-dir>/usage.json`
- Lifecycle scripts: `<cli-tools-root>/_repo/skills/cli-tool/scripts/`

`<service-skill-dir>` is the repo-owned directory that exists for the requested
tool: `<tool>-cli` for a CLI-tools-owned tool, or the bare registered tool name
for a project-scoped service CLI. Resolve the directory that exists; never
require a directory the repo does not register. See Step 3.
</skill_locations>

<process>
## Step 1: Use The Repo SSOT

The cli-tools repository skill source of truth is:

```bash
/Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills
```

Do not create or use `<cli-tools-root>/skills` or runtime-root copies for repo-owned CLI skills. If a service skill is missing, fix `<cli-tools-root>/_repo/skills`.

## Step 2: Separate Service Operations From Lifecycle Work

Service operations use an already available CLI tool: listing, getting, searching, creating service records, auth status/login/logout, downloading, uploading, sending, importing, exporting, cache clearing, or any command the tool exposes.

Lifecycle work changes the CLI implementation or skill bundle: create, update, test, troubleshoot, validate, remove, scaffold, add command, edit command behavior, refresh usage metadata, or fix tests.

If the request is lifecycle work, return to `SKILL.md` routing and use the lifecycle workflow. Do not load a service skill as a substitute for lifecycle work.

## Step 3: Resolve The Service Skill

Resolve the service skill from the skill directories that exist under
`<cli-tools-root>/_repo/skills`. The repo owns the directory name; the router
matches it. A service skill directory is a directory under `_repo/skills` that
holds both `SKILL.md` and an adjacent `usage.json`; a directory without
`usage.json` is not a service skill.

From the user's requested CLI command or service name:

1. Lowercase the tool name.
2. Convert spaces and underscores to hyphens.
3. Match the normalized name against the existing service skill directories, in
   this order, and stop at the first match:
   - `<normalized-name>` when it already ends in `-cli`
   - `<normalized-name>-cli`
   - `<normalized-name>`, for a project-scoped service CLI that cli-tools
     registers under the bare tool name
4. Resolve to `<cli-tools-root>/_repo/skills/<matched-dir>/SKILL.md`.

For example:

| User wording | Service skill |
| --- | --- |
| `google` | `<cli-tools-root>/_repo/skills/google-cli/SKILL.md` |
| `dev_to` | `<cli-tools-root>/_repo/skills/dev-to-cli/SKILL.md` |
| `microsoft 365` | `<cli-tools-root>/_repo/skills/microsoft-365-cli/SKILL.md` |
| `n8n node` | `<cli-tools-root>/_repo/skills/n8n-node-cli/SKILL.md` |
| `coursecraft` | `<cli-tools-root>/_repo/skills/coursecraft/SKILL.md` |

`coursecraft` is the worked project-scoped case. cli-tools registers the tool as
`coursecraft`: `<cli-tools-root>/coursecraft` links to
`Agents/CourseCraft/tools/coursecraft`, `_repo/docs/cli_tools.md` carries its
row, and its repo-owned service skill is
`<cli-tools-root>/_repo/skills/coursecraft/SKILL.md` with the adjacent
`usage.json`. Do not require `_repo/skills/coursecraft-cli`, and do not stop the
operation because that directory is absent. An absent `<tool>-cli` directory is
a resolution failure only when no existing directory matches either form.

List the service skill directories that exist before matching:

```bash
for dir in /Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/*/; do
  if [ -f "${dir}SKILL.md" ] && [ -f "${dir}usage.json" ]; then basename "$dir"; fi
done | sort
```

If no existing directory matches the requested tool, list the available service
skills and ask one targeted question for the intended tool. Do not guess from a
nearby name.

## Step 4: Load The Selected Skill And Command Map

Read both files before running any command:

```bash
sed -n '1,220p' /Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/<service-skill-dir>/SKILL.md
sed -n '1,260p' /Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/<service-skill-dir>/usage.json
```

Follow the selected skill's principles. Use `usage.json` as the command syntax contract. Do not infer flags, argument order, output formats, or auth behavior from memory.

For wrapper CLIs, treat the wrapper's selected skill, `usage.json`, and live
help as authoritative. Do not assume the upstream tool's raw syntax works
through the wrapper; prove the wrapper command shape first.

For help probes, derive the exact command group and action from `usage.json`
before executing `<tool> ... --help`. Do not pluralize service nouns or probe
nearby guessed groups. For example, BrickLink order commands are under
`bricklink order ...`, not `bricklink orders ...`.

## Step 5: Browser-Session Auth Gate

If the selected service skill, `usage.json`, or command credentials show the
requested command requires browser automation / `browser_session`, check auth
status with the shaped unauthenticated-status wrapper from `SKILL.md` before the
service command. If the active browser-session profile is unauthenticated, use
Computer Use to open a visible terminal and run the documented Bash login
command, usually `bash -lc '<tool> auth login ...'`. For multi-credential CLIs,
scope the login with `--credential-type browser_session`; use `--force` only
when the session is stale, expired, or explicitly being refreshed. After login,
rerun `auth status` and proceed only when it reports authenticated.

Do not replace this with headless Playwright, ad hoc browser scripts, manual
session-file edits, or a different auth path. If Computer Use or local GUI
control is unavailable under the current host policy, or Adam has said not to
use a headed browser / not to interrupt him in the current turn, stop and report
that exact blocker. For Cloudflare or similar bot walls, apply the
`Cloudflare And Bot Walls In Browser CLIs` principle in `SKILL.md` before
retrying or escalating browser surfaces.

## Step 6: Execute Through Bash

Run the actual CLI command through Bash using the syntax from `usage.json`. Inspect stdout after every command. If stdout is an AI instruction object, follow the selected service skill's AI-instruction rule instead of summarizing it as normal output.

## Step 7: Report Minimal Proof

Report the selected service skill path, the command run, and the outcome. If blocked, report the exact missing skill path, missing auth state, missing executable, or failing command output.
</process>

<success_criteria>
- Existing CLI requests route through this workflow before service-skill loading.
- The selected service skill path is under `<cli-tools-root>/_repo/skills`.
- The selected service skill's `SKILL.md` and adjacent `usage.json` are read before command execution.
- CLI lifecycle work is routed back to the lifecycle workflows instead of service-operation skills.
- No duplicate repo-owned skill root is created.
</success_criteria>
