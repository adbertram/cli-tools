---
name: cc-connect-slack-manager-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute cc-connect-slack-manager operations using the `cc-connect-slack-manager` CLI tool.
  Manage the always-on Cody Slack cc-connect bridge.
  Triggers: cc-connect-slack-manager, cc-connect-slack-manager cli, Cody Slack bridge, Cody app bridge, Cody cc-connect, Cody Slack app, check Cody bridge, restart Cody bridge, Cody Slack tokens, Cody DM bridge
---

<objective>
Execute cc-connect-slack-manager operations using the `cc-connect-slack-manager` CLI. All cc-connect-slack-manager interactions should use this CLI.
</objective>

<quick_start>
The `cc-connect-slack-manager` CLI follows this pattern:
```bash
cc-connect-slack-manager <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Show service status | `cc-connect-slack-manager service status --table` |
| Restart bridge | `cc-connect-slack-manager service restart` |
| Show logs | `cc-connect-slack-manager service logs --lines 80` |
| Verify Slack app | `cc-connect-slack-manager app verify --table` |
| Send test DM | `cc-connect-slack-manager app send-test "Bridge test"` |
| Check tokens | `cc-connect-slack-manager tokens status --table` |
| Run health checks | `cc-connect-slack-manager checks list --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `cc-connect-slack-manager` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Token Handling">
Never print Slack token values. This CLI only reports token presence and uses Keychain for operations that require a token.
</principle>

<principle name="Command Groups">
- `checks` - Run Cody bridge health checks
- `config` - Show Cody bridge configuration
- `service` - Manage Cody bridge service
- `app` - Verify and test the Cody Slack app
- `tokens` - Check Keychain token status
</principle>
</essential_principles>

<reference_index>
**`usage.json`** - Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
- Slack tokens are never printed
</success_criteria>
