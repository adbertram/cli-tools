---
name: codex-helper-cli
description: Use this skill for Codex Helper CLI commands that report local Codex app-server account and plan usage. Load this skill before running `codex-helper` commands.
---

<objective>
Use `codex-helper` to inspect local Codex ChatGPT plan usage through the Codex app-server without printing tokens or reusable credentials.
</objective>

<commands>
Read the adjacent `usage.json` before running commands. Key command:

```bash
codex-helper usage --json
```

Use `--table` only for human-readable display.
</commands>

<auth>
`codex-helper` uses the upstream Codex CLI's existing authentication. It does not own credentials, does not create auth commands, and must not print secrets or tokens.
</auth>

<output_contract>
`codex-helper usage --json` emits one JSON object with:
- `account`: `email`, `plan_type`
- `limits`: one object for `codex` plus additional `rateLimitsByLimitId` entries such as `codex_bengalfox`
- `credits`: `has_credits`, `unlimited`, `balance`
- `rate_limit_reset_credits`: `available_count`
</output_contract>
