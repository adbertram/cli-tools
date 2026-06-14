---
name: harmony-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI
  implementation lifecycle work such as creating, testing, updating,
  troubleshooting, validating, removing, or documenting the CLI tool itself;
  delegate those tasks to cli-tool-expert. Execute Harmony operations using the
  `harmony` CLI tool. Manage Logitech Harmony hubs, activities, devices, and
  commands over the local network. Triggers: harmony, harmony cli, harmony hub,
  logitech harmony, list harmony devices, start harmony activity, send harmony
  command, harmony remote, probe harmony hub, scan harmony network
---

<objective>
Execute Logitech Harmony operations using the `harmony` CLI. All Harmony hub
interactions should use this CLI.
</objective>

<quick_start>
The `harmony` CLI follows this pattern:
```bash
harmony <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Discover hubs | `harmony hubs list --table` |
| Low-level hub probe | `harmony hubs probe --cidr 192.168.86.0/24 --table` |
| Show hub status | `harmony hubs get 192.168.1.50 --table` |
| List activities | `harmony activities list --hub 192.168.1.50` |
| Start activity | `harmony activities start "Watch TV" --hub 192.168.1.50` |
| List devices | `harmony devices list --hub 192.168.1.50` |
| List device commands | `harmony commands list "Living Room TV" --hub 192.168.1.50` |
| Send device command | `harmony commands send "Living Room TV" VolumeUp --hub 192.168.1.50` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `harmony` command.**
This file contains complete command syntax, all arguments, all options, and
usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Local Hub Access">
Harmony uses local network access. Prefer `harmony hubs list` to discover hubs.
If Bonjour/mDNS discovery returns no hubs, run `harmony hubs probe` to scan
Harmony TCP ports on the local subnet, then pass an explicit IP with `--hub` or
set `HARMONY_HUB` in `~/.local/share/cli-tools/harmony/.env`.
</principle>

<principle name="Command Groups">
- **hubs** -- Discover hubs, low-level TCP probe, show hub status, search hubs, sync hubs
- **activities** -- List/get/search activities, show current activity, start activity, power off
- **devices** -- List/get/search configured devices
- **commands** -- List/get/send device commands and change channel
- **config** -- Get or list raw hub configuration
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against `usage.json`
</success_criteria>
