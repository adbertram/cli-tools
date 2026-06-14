---
name: weather-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI
  implementation lifecycle work such as creating, testing, updating,
  troubleshooting, validating, removing, or documenting the CLI tool itself;
  delegate those tasks to cli-tool-expert. Execute Weather operations using the
  `weather` CLI tool. Get current temperature, humidity, and forecasts for US
  ZIP codes using public no-auth weather APIs. Triggers: weather, weather cli,
  zip code weather, current temperature, current humidity, weather conditions,
  weather forecast
---

<objective>
Execute weather lookups using the `weather` CLI.
</objective>

<quick_start>
The `weather` CLI follows this pattern:
```bash
weather <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Get current conditions for one ZIP code | `weather conditions get 90210` |
| Get current conditions for DEFAULT_ZIP | `weather conditions get` |
| Show conditions as a table | `weather conditions get 90210 --table` |
| List conditions for multiple ZIP codes | `weather conditions list 90210 10001 --table` |
| Get forecast for one ZIP code | `weather forecast get 90210 --days 7` |
| Get forecast for DEFAULT_ZIP | `weather forecast get --days 7` |
| List forecasts for multiple ZIP codes | `weather forecast list 90210 10001 --days 3 --table` |
| Use Celsius | `weather conditions get 90210 --unit celsius` |
| Select fields | `weather conditions get 90210 --properties zip_code,temperature,humidity` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `weather` command.**
This file contains complete command syntax, all arguments, all options, and
usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="No Auth">
Weather uses public no-auth APIs. Do not ask for credentials.
</principle>

<principle name="Default ZIP">
When ZIP arguments are omitted, `weather` reads `DEFAULT_ZIP` from
`~/.local/share/cli-tools/weather/.env`.
</principle>

<principle name="Command Groups">
- **conditions** -- Get or list current temperature and humidity by US ZIP code.
- **forecast** -- Get or list daily forecasts by US ZIP code.
- **cache** -- Clear cached API responses.
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
