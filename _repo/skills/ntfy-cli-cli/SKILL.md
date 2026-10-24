---
name: ntfy-cli-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute NtfyCli operations using the `ntfy-cli` CLI tool.
  CLI interface for NtfyCli.
  Triggers: ntfy-cli, ntfy-cli cli
---

<objective>
Execute NtfyCli operations using the `ntfy-cli` CLI. All NtfyCli interactions should use this CLI.
</objective>

<project_overrides>
Before acting on this skill, run:

```bash
~/.agents/skills/skill-expert/scripts/load-skill-overrides.sh ntfy-cli-cli
```

Apply any printed instructions alongside this skill's own workflow: they extend it and
never repeal its limits. No output means no project override is in effect. A non-zero
exit means the project's override file is broken -- report it and stop rather than
silently running unmodified.
</project_overrides>

<quick_start>
The `ntfy-cli` CLI follows this pattern:
```bash
ntfy-cli <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Report local executable readiness without mutating credentials | `ntfy-cli auth status` |
| Fetch cached messages and return a JSON array | `ntfy-cli messages poll <TOPIC>` |
| Publish a message with current upstream ntfy publish options | `ntfy-cli messages publish <TOPIC> [BODY]` |
| Stream upstream NDJSON without buffering or normalization | `ntfy-cli messages subscribe <TOPIC>` |
| Run subscriptions defined in upstream client configuration | `ntfy-cli messages subscribe-config` |
| Send ntfy's topic-only trigger message | `ntfy-cli messages trigger <TOPIC>` |
| server access get | `ntfy-cli server access get <USERNAME>` |
| server access list | `ntfy-cli server access list` |
| server access reset | `ntfy-cli server access reset` |
| server access set | `ntfy-cli server access set <USERNAME> <TOPIC> <PERMISSION>` |
| Run upstream ntfy server in the foreground | `ntfy-cli server serve` |
| server tokens create | `ntfy-cli server tokens create <USERNAME>` |
| server tokens delete | `ntfy-cli server tokens delete <USERNAME> <TOKEN>` |
| server tokens generate | `ntfy-cli server tokens generate` |
| server tokens get | `ntfy-cli server tokens get <USERNAME>` |
| server tokens list | `ntfy-cli server tokens list` |
| server users create | `ntfy-cli server users create <USERNAME>` |
| server users delete | `ntfy-cli server users delete <USERNAME>` |
| server users get | `ntfy-cli server users get <USERNAME>` |
| server users list | `ntfy-cli server users list` |
| Manage user passwords | `ntfy-cli server users password` |
| Manage user roles | `ntfy-cli server users role` |
| Pass arguments to ntfy unchanged, preserving stdout, stderr, and exit code | `ntfy-cli upstream` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `ntfy-cli` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `ntfy-cli --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Inspect upstream readiness; credentials remain upstream-owned (subcommands: status)
- **messages** -- Publish and receive ntfy messages (subcommands: poll, publish, subscribe, subscribe-config, trigger)
- **server** -- Administer a local ntfy server when upstream supports it (subcommands: access, serve, tokens, users)
- **upstream** -- Pass arguments to ntfy unchanged, preserving stdout, stderr, and exit code
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`ntfy-cli --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
