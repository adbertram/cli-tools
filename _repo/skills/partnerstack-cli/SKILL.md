---
name: partnerstack-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute partnerstack operations using the `partnerstack` CLI tool.
  CLI interface for PartnerStack Partner API: rewards, marketplace program discovery, Basic-auth form-templates/applications endpoints, and partnerships.
  Triggers: partnerstack, partnerstack cli, PartnerStack rewards, PartnerStack earnings, list PartnerStack rewards, get PartnerStack reward, PartnerStack payment status, PartnerStack partner data, my PartnerStack, PartnerStack marketplace, browse PartnerStack programs, PartnerStack form templates, PartnerStack form-templates, PartnerStack application schema, PartnerStack group_slug, PartnerStack apply, create PartnerStack application, PartnerStack partnerships, joined PartnerStack programs, PartnerStack discovery
---

<objective>
Execute PartnerStack Partner API operations using the `partnerstack` CLI. All PartnerStack interactions should use this CLI.
</objective>

<quick_start>
The `partnerstack` CLI follows this pattern:
```bash
partnerstack <command-group> <action> [arguments] [options]
```

| Command | Purpose |
|---------|---------|
| `partnerstack rewards list` | List rewards as JSON |
| `partnerstack rewards list --table` | List rewards as a table |
| `partnerstack rewards list --filter "payment_status:eq:withdrawn"` | Filter rewards by payment status |
| `partnerstack rewards list --properties "key,company.name,amount"` | Return selected reward fields |
| `partnerstack rewards get REWARD_KEY` | Get one reward by key |
| `partnerstack marketplace list` | Browse marketplace programs (discovery — non-joined programs) |
| `partnerstack marketplace list --filter "category:eq:artificial-intelligence" --table` | Filter marketplace programs by category |
| `partnerstack marketplace get COMPANY_KEY` | Retrieve a single marketplace program by key |
| `partnerstack form-templates list` | List Basic-auth application form templates |
| `partnerstack form-templates get FORM_TEMPLATE_KEY` | Get one Basic-auth form template |
| `partnerstack applications create --group-slug affiliates --meta '<json>'` | Create a Basic-auth PartnerStack application |
| `partnerstack applications create --group-slug affiliates --meta-field email=... --meta-field first_name=...` | Create an application from key/value meta fields |
| `partnerstack partnerships list` | List joined partnerships (post-approval) |
| `partnerstack partnerships list --filter "order_by:eq:-updated_at"` | Sort partnerships |
| `partnerstack partnerships get PARTNERSHIP_KEY` | Get one partnership by key |
| `partnerstack auth status` | Check Bearer API key authentication |
| `partnerstack auth login-basic` | Save Basic public/secret keys for form-templates and applications |
| `partnerstack auth basic-status` | Check whether Basic credentials are configured |
| `partnerstack cache clear` | Clear cached responses |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `partnerstack` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `partnerstack` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- `rewards` - List and retrieve PartnerStack rewards.
- `marketplace` - Browse marketplace programs (discovery — programs the partner has not yet joined). Wraps `GET /api/v2/marketplace/programs` and `GET /api/v2/marketplace/programs/{company_key}`.
- `form-templates` - List and retrieve application form templates. PartnerStack documents `GET /api/v2/form-templates` as `Credentials: Basic`; configure `USERNAME`/`PASSWORD` with `partnerstack auth login-basic`.
- `applications` - Create partner applications. PartnerStack documents `POST /api/v2/applications` as `Credentials: Basic`; configure `USERNAME`/`PASSWORD` with `partnerstack auth login-basic`.
- `partnerships` - List joined partnerships (post-approval relationships) via `GET /api/v2/partnerships`.
- `auth` - Manage PartnerStack Bearer API key credentials, Basic public/secret key credentials, and profiles.
- `cache` - Clear cached CLI responses.
</principle>

<principle name="Credential Types">
- Bearer commands (`rewards`, `marketplace`, `partnerships`) use profile field `API_KEY` and are configured with `partnerstack auth login`.
- Basic commands (`form-templates`, `applications`) use profile field `USERNAME` for the PartnerStack Basic public key and `PASSWORD` for the Basic secret/private key. Configure them with `partnerstack auth login-basic` and verify presence with `partnerstack auth basic-status`.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against usage.json
</success_criteria>
