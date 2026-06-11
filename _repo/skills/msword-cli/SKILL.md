---
name: msword-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute msword operations using the `msword` CLI tool.
  Read Word docs, convert to markdown, and manage comments (list, add inline).
  Triggers: msword, msword cli, word document, docx, read word file, convert docx to markdown, word comments, extract word comments, add word comment, inline comment
---

<objective>
Execute msword operations using the `msword` CLI. All Word document interactions should use this CLI.
</objective>

<quick_start>
The `msword` CLI follows this pattern:
```bash
msword docs <action> <file> [options]
```

| Task | Command |
|------|---------|
| Read document text | `msword docs read document.docx` |
| Convert to markdown | `msword docs convert document.docx` |
| Convert to file | `msword docs convert document.docx --output document.md` |
| List comments | `msword docs comments list document.docx --table` |
| Filter comments by author | `msword docs comments list document.docx --filter "author:Jane"` |
| Add inline comment | `msword docs comments add document.docx --text "Fix this" --author "Editor" --reference-text "some text"` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `msword` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **docs** -- Read, convert, and manage comments in Word documents (read, convert, comments {list, add})
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
