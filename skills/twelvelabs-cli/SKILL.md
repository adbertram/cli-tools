---
name: "twelvelabs-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute twelvelabs operations using the `twelvelabs` CLI tool. CLI interface for TwelveLabs video AI API. Triggers: twelvelabs, twelvelabs cli, twelve labs, video ai, video analysis, analyze video, video index, generate text from video, video understanding, video transcription"
---

<objective>
Execute twelvelabs operations using the `twelvelabs` CLI. All TwelveLabs video AI interactions should use this CLI.
</objective>

<quick_start>
The `twelvelabs` CLI follows this pattern:
```bash
twelvelabs <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List indexes | `twelvelabs indexes list` |
| Create an index | `twelvelabs indexes create "my-index"` |
| Upload a video | `twelvelabs videos upload INDEX_ID /path/to/video.mp4` |
| List videos in index | `twelvelabs videos list INDEX_ID` |
| Generate text from video | `twelvelabs generate text VIDEO_ID -p "Describe this video"` |
| Generate JSON from video | `twelvelabs generate json VIDEO_ID -p "Return JSON of issues"` |
| Check auth | `twelvelabs auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `twelvelabs` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage TwelveLabs API authentication (login, logout, status)
- **indexes** -- Manage video indexes (list, get, create, delete)
- **videos** -- Manage videos in indexes (list, get, upload, delete)
- **generate** -- Generate text/JSON from indexed videos (text, json)
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
