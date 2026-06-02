---
name: "keywords-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute keywords operations using the `keywords` CLI tool. Query autocomplete suggestions from search engines for keyword research -- Google, YouTube, Bing, Amazon, DuckDuckGo. Triggers: keywords, keywords cli, keyword research, autocomplete suggestions, search suggestions, keyword ideas, seo keywords, suggest keywords, keyword tool"
---

<objective>
Execute keywords operations using the `keywords` CLI. All keyword research via autocomplete should use this CLI.
</objective>

<quick_start>
The `keywords` CLI follows this pattern:
```bash
keywords suggest <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Get keyword suggestions | `keywords suggest query "python tutorial" --table` |
| Multi-source suggestions | `keywords suggest query "best laptop" -s google -s youtube -s amazon --table` |
| Filter suggestions | `keywords suggest query "seo" --filter "tool" --table` |
| Recursive expansion | `keywords suggest query "python" --recurse --depth 2 --table` |
| List available sources | `keywords suggest sources --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `keywords` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **suggest** -- Query autocomplete suggestions (query, sources)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
