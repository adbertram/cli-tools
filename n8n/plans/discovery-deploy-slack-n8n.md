# Discovery: Deploy Slack CLI to n8n & Create Slack Reminders AI Tool

## Codebase Context

### Key Files
- `slack/slack_cli/main.py` - Slack CLI entry point. reminders was removed during testing (scope issues). Must be re-added.
- `slack/slack_cli/commands/reminders.py` - Uses `client.list_saved()` (Slack's "Later"/saved items API)
- `slack/slack_cli/config.py` - Uses `CredentialType.CUSTOM` with `ACCESS_TOKEN`
- `n8n/n8n_cli/commands/convert.py` - `n8n nodes create` generates n8n node packages from CLI tools
- `n8n/n8n_cli/commands/deploy.py` - Deploy pipeline: auth check → npm build → rsync → npm pack/install → venv → .env copy → n8n restart → credential creation → verify
- `n8n/n8n_cli/commands/workflow_nodes.py` - AI tools connected with `--type ai_tool`

### Critical Findings
1. reminders was removed from main.py (we did this during test fixes) - must re-add
2. The saved.list API returns `not_allowed_token_type` with xoxp token - need to fix token
3. slack-custom package already exists at ~/Dropbox/GitRepos/n8n-nodes/slack-custom/ but needs regeneration
4. SVG icon file is missing from generated package
5. Susan workflow (U7cK5XlQqmgG9CWlrB6wM) has 14 AI tools already
6. Built-in slackTool already exists in Susan's workflow

## Q&A Results

### Wave: Blocker
**Q:** We just removed reminders from slack CLI because saved.list API returns 'not_allowed_token_type' with xoxp token. How should we proceed?
**A:** Add reminders back and fix the token issue.

### Wave: Clarify Task
**Q:** Should we regenerate the slack-custom node with --force after adding reminders back?
**A:** Yes, regenerate with --force.

**Q:** Should we use /n8n-manager skill or run deploy.sh directly?
**A:** Use /n8n-manager skill.

### Wave: Technical Decisions
**Q:** Slack CLI uses CredentialType.CUSTOM with .env-based auth. Is this acceptable?
**A:** The deployment should auto-create the credential.

**Q:** Should the full slack-custom node be exposed to Susan or just reminders?
**A:** Reminders only via scoped tool.

**Q:** How to differentiate from the built-in Slack tool in Susan's workflow?
**A:** Rename the display name.

**Q:** Default --state parameter for reminders?
**A:** in_progress (active items).

### Wave: Success Criteria / Testing
**Q:** Server restart during deploy is OK?
**A:** Proceed now.

**Q:** How to test Susan workflow after adding tool?
**A:** Manual trigger via n8n workflows execute.

## Key Decisions
- Re-add reminders to main.py and fix token issue (xoxp → xoxc or find workaround)
- Regenerate slack-custom node with --force
- Deploy via /n8n-manager skill
- Deployment should auto-create credential
- Scope AI tool to reminders only (not full node)
- Rename display name to distinguish from built-in Slack
- Default to in_progress state
- Test via manual workflow execution
