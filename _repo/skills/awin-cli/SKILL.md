---
name: awin-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute awin operations using the `awin` CLI tool. Awin Publisher API CLI -- list publisher accounts and advertiser programmes via Bearer token auth.
  Triggers: awin, awin cli, awin publisher, awin programmes, awin advertisers, list awin programs, awin affiliate, awin api.
---

<objective>
Execute Awin Publisher API operations using the `awin` CLI. All Awin
publisher and programme interactions should use this CLI.
</objective>

<quick_start>
The `awin` CLI follows this pattern:

```bash
awin <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Authenticate | `awin auth login` |
| Check auth | `awin auth status` |
| List publisher accounts | `awin publishers list` |
| Get one publisher | `awin publishers get PUBLISHER_ID` |
| List joined programmes | `awin programmes list` |
| List unjoined programmes | `awin programmes list --relationship notjoined` |
| Get one programme | `awin programmes get PROGRAMME_ID` |
| Clear cached responses | `awin cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `awin` command.** It contains complete command syntax, arguments, options, and usage instructions.
</principle>

<principle name="Authentication">
Awin uses Bearer token authentication. Generate the token at
https://ui.awin.com/awin-api and run `awin auth login`. You will be
prompted for the token AND your numeric Awin Publisher ID.
</principle>

<principle name="Output Controls">
List commands support `--limit/-l`, `--filter/-f`, `--properties/-p`, and `--table/-t`. JSON is the default on stdout.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
