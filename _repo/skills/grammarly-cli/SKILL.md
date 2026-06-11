---
name: grammarly-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute grammarly operations using the `grammarly` CLI tool.
  CLI interface for Grammarly API -- plagiarism detection and document management.
  Triggers: grammarly, grammarly cli, plagiarism check, check plagiarism, grammarly documents, grammarly docs, plagiarism detection, grammar check
---

<objective>
Execute grammarly operations using the `grammarly` CLI. All grammarly interactions should use this CLI.
</objective>

<quick_start>
The `grammarly` CLI follows this pattern:
```bash
grammarly <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `grammarly auth status` |
| Check file for plagiarism | `grammarly plagiarism check document.docx` |
| Check text for plagiarism | `grammarly plagiarism check --text "Your text here"` |
| Check plagiarism status | `grammarly plagiarism status SCORE_REQUEST_ID` |
| List documents | `grammarly docs list --table` |
| Read document content | `grammarly docs read DOCUMENT_ID` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `grammarly` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage Grammarly API OAuth authentication (login, logout, status)
- **plagiarism** -- Plagiarism detection (check files/text, check status)
- **docs** -- Manage Grammarly documents (list, get, read, new)
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
