---
name: rakuten-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute rakuten operations using the `rakuten` CLI tool. Rakuten Advertising Publisher API CLI -- list advertiser programs via OAuth 2.0 password grant.
  Triggers: rakuten, rakuten cli, rakuten advertising, rakuten advertisers, rakuten affiliate, linkshare, rakuten linksynergy, list rakuten advertisers, rakuten merchants.
---

<objective>
Execute Rakuten Advertising Publisher API operations using the `rakuten`
CLI. All Rakuten advertiser interactions should use this CLI.
</objective>

<quick_start>
The `rakuten` CLI follows this pattern:

```bash
rakuten <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Authenticate | `rakuten auth login` |
| Check auth | `rakuten auth status` |
| List approved advertisers | `rakuten advertisers list` |
| List all advertisers | `rakuten advertisers list --status all` |
| Get one advertiser by mid | `rakuten advertisers get MERCHANT_ID` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `rakuten` command.** It contains complete command syntax, arguments, options, and usage instructions.
</principle>

<principle name="Authentication">
Rakuten Advertising uses OAuth 2.0 password grant. Create an Application
at https://developers.rakutenadvertising.com/ to obtain Client ID +
Client Secret. The publisher SID is in the top-right of
https://pubdashboard.rakutenadvertising.com. Run `rakuten auth login` to
set Client ID, Client Secret, SID, dashboard username, and dashboard
password. The CLI caches the access token until it expires (60 minutes).
</principle>

<principle name="Output Controls">
List commands support `--limit/-l`, `--filter/-f`, `--properties/-p`, `--status/-s`, and `--table/-t`. JSON is the default on stdout.
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
