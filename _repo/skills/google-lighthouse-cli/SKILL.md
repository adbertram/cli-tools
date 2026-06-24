---
name: google-lighthouse-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute google-lighthouse operations using the `google-lighthouse` CLI tool.
  Run and manage Google Lighthouse audits.
  Triggers: google-lighthouse, google-lighthouse cli, google-lighthouse audits, lighthouse audit, run Lighthouse audit, website performance audit, Core Web Vitals audit, list Lighthouse audits, get Lighthouse report, blog performance audit
---

<objective>
Execute google-lighthouse operations using the `google-lighthouse` CLI. All Google Lighthouse audit interactions should use this CLI.
</objective>

<quick_start>
The `google-lighthouse` CLI follows this pattern:
```bash
google-lighthouse <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Run a desktop audit | `google-lighthouse audits run https://example.com/` |
| Run a mobile audit | `google-lighthouse audits run https://example.com/ --form-factor mobile` |
| Show selected audit fields | `google-lighthouse audits run https://example.com/ --properties id,scores.performance,artifacts.html` |
| List saved audits | `google-lighthouse audits list` |
| List saved audits as a table | `google-lighthouse audits list --table` |
| Filter saved audits | `google-lighthouse audits list --filter "url:eq:https://example.com/"` |
| Get one audit | `google-lighthouse audits get AUDIT_ID` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `google-lighthouse` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `google-lighthouse` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **audits** - Run new Lighthouse audits and retrieve saved audit summaries and artifact paths.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** - Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against usage.json
</success_criteria>
