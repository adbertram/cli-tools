---
name: wpengine-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI
  implementation lifecycle work such as creating, testing, updating,
  troubleshooting, validating, removing, or documenting the CLI tool itself;
  delegate those tasks to cli-tool-expert. Execute WP Engine Hosting Platform
  API operations using the `wpengine` CLI tool.
  Triggers: wpengine, wp engine, wpengine cli, wp engine cli, wp engine api,
  wp engine accounts, wp engine sites, wp engine environments, wp engine cache,
  wp engine ssh, wp engine sftp
---

<objective>
Execute WP Engine Hosting Platform API and documented connection-helper operations using the `wpengine` CLI.
</objective>

<quick_start>
The `wpengine` CLI follows this pattern:

```bash
wpengine <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Authenticate | `wpengine auth login` |
| Check auth | `wpengine auth status` |
| Check API status | `wpengine api status` |
| List accounts | `wpengine accounts list --table` |
| Get account | `wpengine accounts get ACCOUNT_ID` |
| List sites | `wpengine sites list --table` |
| Get site | `wpengine sites get SITE_ID` |
| List environments | `wpengine environments list --table` |
| Get environment | `wpengine environments get ENVIRONMENT_ID` |
| Purge all cache | `wpengine cache purge ENVIRONMENT_ID --type all` |
| Get SSH details | `wpengine ssh connection get ENVIRONMENT_NAME` |
| Get SSH config | `wpengine ssh config get ENVIRONMENT_NAME` |
| List SSH keys | `wpengine ssh keys list --table` |
| Add SSH key | `wpengine ssh keys add "ssh-ed25519 ..."` |
| Delete SSH key | `wpengine ssh keys delete SSH_KEY_ID --yes` |
| Get SFTP details | `wpengine sftp connection get ENVIRONMENT_NAME --username USERNAME` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `wpengine` command.**
This file contains the complete command tree with arguments and options. Never guess command syntax.
</principle>

<principle name="Authentication">
WP Engine API credentials come from WP Engine User Portal API Access. Use the API User ID as `USERNAME` and the API Password as `PASSWORD` through `wpengine auth login`.
</principle>

<principle name="Output">
JSON is the default output. Use `--table` only when a human-readable table is needed. API-backed JSON output preserves full API response fields unless `--properties` is explicitly supplied.
</principle>

<principle name="Scope Limits">
The v1 CLI is API-only plus documented SSH/SFTP connection helpers.
- Do not use this CLI for deploy or theme-file mutation commands; use the existing WordPress/ATA Blog theme file push path for that.
- SFTP commands derive documented host/user strings only. They do not manage, retrieve, or validate SFTP credentials.
- SSH/SFTP helper output is intended to provide `--host`, `--user`, and remote host/path details for existing file-push workflows.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication commands and profile management
- **api** -- Public API status
- **accounts** -- WP Engine account list/get
- **sites** -- WP Engine site list/get
- **environments** -- WP Engine install/environment list/get
- **cache** -- Environment cache purge
- **ssh** -- SSH connection/config helpers and SSH key API operations
- **sftp** -- SFTP connection helper output
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against `usage.json`
- Mutation commands are limited to approved API operations only
</success_criteria>
