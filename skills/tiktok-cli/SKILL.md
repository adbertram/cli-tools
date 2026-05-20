---
name: tiktok-cli
description: >-
  Execute tiktok operations using the `tiktok` CLI tool.
  TikTok transcript downloader using yt-dlp.
  Triggers: tiktok, tiktok cli, tiktok transcripts, tiktok auth
---

<objective>
Execute tiktok operations using the `tiktok` CLI. All tiktok interactions should use this CLI.
</objective>

<quick_start>
The `tiktok` CLI follows this pattern:
```bash
tiktok <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Download transcripts for one or more TikTok videos. | `tiktok transcripts download` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent. | `tiktok auth login` |
| Clear stored credentials. | `tiktok auth logout` |
| Check authentication status across profiles. Performs a live round-trip for every configured credential type so the report reflects ground truth — not on-disk belief. Saved credentials whose live verification fails are reported as ``authenticated: false`` with the failure reason in ``api_test``. | `tiktok auth status` |
| Manage authentication profiles | `tiktok auth profiles` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `tiktok` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `tiktok` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **transcripts** -- Download TikTok video transcripts
- **auth** -- Manage tiktok authentication
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
