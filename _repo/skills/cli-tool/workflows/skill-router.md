<objective>
Route an existing cli-tools service operation to the repo-owned service skill that owns the requested CLI command.
</objective>

<skill_locations>
- Router skill: `<cli-tools-root>/_repo/skills/cli-tool/SKILL.md`
- Service skills: `<cli-tools-root>/_repo/skills/<tool>-cli/SKILL.md`
- Command maps: `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json`
- Lifecycle scripts: `<cli-tools-root>/_repo/skills/cli-tool/scripts/`
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

From the user's requested CLI command or service name:

1. Lowercase the tool name.
2. Convert spaces and underscores to hyphens.
3. Append `-cli` if the name does not already end in `-cli`.
4. Resolve exactly to `<cli-tools-root>/_repo/skills/<normalized-name>/SKILL.md`.

For example:

| User wording | Service skill |
| --- | --- |
| `google` | `<cli-tools-root>/_repo/skills/google-cli/SKILL.md` |
| `dev_to` | `<cli-tools-root>/_repo/skills/dev-to-cli/SKILL.md` |
| `microsoft 365` | `<cli-tools-root>/_repo/skills/microsoft-365-cli/SKILL.md` |
| `n8n node` | `<cli-tools-root>/_repo/skills/n8n-node-cli/SKILL.md` |

If the exact path does not exist, list available service skills and ask one targeted question for the intended tool. Do not guess from a nearby name.

```bash
find /Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills \
  -maxdepth 1 -mindepth 1 -type d -name '*-cli' -exec basename {} \; | sort
```

## Step 4: Load The Selected Skill And Command Map

Read both files before running any command:

```bash
sed -n '1,220p' /Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/<tool>-cli/SKILL.md
sed -n '1,260p' /Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/<tool>-cli/usage.json
```

Follow the selected skill's principles. Use `usage.json` as the command syntax contract. Do not infer flags, argument order, output formats, or auth behavior from memory.

## Step 5: Execute Through Bash

Run the actual CLI command through Bash using the syntax from `usage.json`. Inspect stdout after every command. If stdout is an AI instruction object, follow the selected service skill's AI-instruction rule instead of summarizing it as normal output.

## Step 6: Report Minimal Proof

Report the selected service skill path, the command run, and the outcome. If blocked, report the exact missing skill path, missing auth state, missing executable, or failing command output.
</process>

<success_criteria>
- Existing CLI requests route through this workflow before service-skill loading.
- The selected service skill path is under `<cli-tools-root>/_repo/skills`.
- The selected service skill's `SKILL.md` and adjacent `usage.json` are read before command execution.
- CLI lifecycle work is routed back to the lifecycle workflows instead of service-operation skills.
- No duplicate repo-owned skill root is created.
</success_criteria>
