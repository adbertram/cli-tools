---
name: linkedin-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute LinkedIn operations using the `linkedin` CLI tool.
  Create and manage LinkedIn member and page posts through LinkedIn's official OAuth APIs only.
  Triggers: linkedin, linkedin cli, linkedin user posts, linkedin page posts, linkedin member posts, linkedin personal posts, linkedin company page posts, affiliate magic linkedin page, linkedin auth, linkedin profile, list linkedin posts, create linkedin post
---

<objective>
Execute LinkedIn operations using the `linkedin` CLI. All LinkedIn interactions should use this CLI.
</objective>

<quick_start>
The `linkedin` CLI follows this pattern:
```bash
linkedin <surface-or-group> <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `linkedin auth status` |
| Start OAuth login | `linkedin auth login` |
| List personal posts | `linkedin user posts list --limit 10` |
| Get one personal post | `linkedin user posts get <post_urn>` |
| List page posts | `linkedin page posts list --page <page_urn> --limit 10` |
| Get one page post | `linkedin page posts get <post_urn> --page <page_urn>` |
| Create a page post | `linkedin page posts create "Hello LinkedIn" --page <page_urn>` |
| Use non-default app profile | `linkedin page posts list --profile affiliate-magic-page --limit 10` |
| List auth profiles | `linkedin auth profiles list` |
| Check post readiness | `linkedin auth readiness --table` |
| Clear cached responses | `linkedin cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `linkedin` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `linkedin` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **user** -- authenticated-member resources; `linkedin user posts list|get|search|create|update|delete` use LinkedIn's official Posts API with OAuth tokens only. Member writes require `w_member_social`; member reads require `r_member_social`.
- **page** -- LinkedIn page resources; `linkedin page posts list|get|search|create|update|delete` use LinkedIn's official Posts API with OAuth tokens only. Page writes require `w_organization_social`; page reads require `r_organization_social`.
- Post commands accept `--profile` to select a non-default LinkedIn profile.
- **auth** -- OAuth login, status, test, readiness, logout, refresh, and nested `auth profiles` management. Missing restricted scopes fail through the API permission path with the exact scope LinkedIn denied.
- **cache** -- Remove cached LinkedIn API responses
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
