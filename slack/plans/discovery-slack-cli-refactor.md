# Discovery: Slack CLI Refactor to cli_tools_shared Compliance

## Codebase Context

### Key Files
- `slack_cli/config.py` - Custom Config class (580 lines) with WorkspaceCredentials and multi-workspace JSON storage in ~/.slack-cli/workspaces.json. Reads SLACK_*-prefixed env vars. Does NOT extend BaseConfig.
- `slack_cli/commands/auth.py` - Fully custom auth (887 lines): login, logout, status, refresh. No create_auth_app(). Missing --force/-F, --profile/-p. Has Slack-specific flags (--token-type, --team-id, --all, --code, --no-browser).
- `slack_cli/browser.py` - Custom BrowserAutomationService (965 lines). Not a BrowserAutomation subclass. Uses persistent browser context.
- `slack_cli/main.py` - Registers 12 command groups. No profiles group. No create_profiles_app() or create_auth_app().
- `slack_cli/filters.py` - Missing contains/startswith/endswith operators. Differs from template.
- `slack_cli/commands/channels.py` - Has 'info' (not 'get'), missing --properties/-p on list.
- `slack_cli/commands/users.py` - Has 'info' (not 'get'), missing --properties/-p on list.
- `slack_cli/commands/workspace.py` - Has list missing --limit/--filter/--properties.
- `pyproject.toml` - Missing cli-tools-shared dependency.
- `.env.example` - All vars SLACK_-prefixed. Missing IS_DEFAULT_PROFILE.
- `.gitignore` - Missing profiles/ and .env* patterns.

### Test Results: 61 passed, 45 failed, 8 skipped

### Passing CLI Example
- cloudflare/cloudflare_cli/config.py - Thin BaseConfig subclass with CREDENTIAL_TYPES, DEFAULT_BASE_URL

### Core Challenge
The Slack CLI multi-workspace model (workspaces.json, 3 token types per workspace) is fundamentally different from BaseConfig's profile-per-.env-file model.

## Q&A Results

### Wave: Architecture

**Q:** Workspace model mapping strategy?
**A:** Convert workspaces to profiles. Each Slack workspace becomes a separate .env file (profile). workspaces.json is removed.

**Q:** How to preserve custom auth login logic with create_auth_app()?
**A:** Convert to support auth types as closely as possible. If none fit, stop and ask. The Slack-specific flags (--token-type, --team-id, --all) are NOT needed - all should be stored in profiles.

**Q:** How to handle browser.py (custom BrowserAutomationService)?
**A:** Must use the shared BrowserAutomation subclass. But it needs to have support for saving state and reusing it (like the custom Slack one does with persistent context).

**Q:** Credential types declaration?
**A:** CUSTOM type with custom fields. CREDENTIAL_TYPES = [CredentialType.CUSTOM] with CUSTOM_REQUIRED_FIELDS = ['ACCESS_TOKEN'].

### Wave: Technical Decisions

**Q:** Env var rename (SLACK_ prefix)?
**A:** Rename all SLACK_ vars in .env. Clean break. SLACK_CLIENT_ID -> CLIENT_ID, etc.

**Q:** 'info' vs 'get' commands?
**A:** Rename 'info' to 'get' everywhere. Breaking change acceptable.

**Q:** Workspace list missing flags?
**A:** Remove workspace group entirely. Use profiles instead.

**Q:** Filters template alignment?
**A:** Replace with exact template copy. Template is canonical source.

### Wave: Risks & Implementation

**Q:** COMMAND_CREDENTIALS for multi-credential mapping?
**A:** Yes, add to all command files.

**Q:** Losing --token-type/--team-id/--all flags in auth login help?
**A:** We don't need them. They should all be stored in profiles.

**Q:** Data migration from workspaces.json?
**A:** Cut over at once. No fallbacks or migration needed.

**Q:** auth status exit code?
**A:** Always exit 0. Use authenticated: true/false JSON field.

### Wave: Scope

**Q:** Refactor approach?
**A:** All areas in one pass.

**Q:** Persistent browser context?
**A:** browser.py needs support for saving state and reusing it (like the custom Slack one does with persistent context). Must be BrowserAutomation subclass.

**Q:** Workspace command group?
**A:** Remove entirely. All ops handled through profiles.

## Key Decisions

1. **Workspace = Profile**: Each Slack workspace maps to a separate .env profile. workspaces.json is eliminated.
2. **create_auth_app() with login_handler**: Slack-specific flags removed. All workspace config stored in profiles.
3. **BrowserAutomation subclass**: Rewrite browser.py as SlackBrowser(BrowserAutomation). Must support persistent state save/restore.
4. **CUSTOM credential type**: Single CredentialType.CUSTOM with ACCESS_TOKEN as required field.
5. **Clean env var rename**: Remove all SLACK_ prefixes. BaseConfig handles natively.
6. **'info' -> 'get' rename**: Breaking change across channels, users, files.
7. **Remove workspace group**: Profiles replace all workspace management.
8. **Template filters.py**: Replace with canonical copy.
9. **COMMAND_CREDENTIALS**: Add to all 12 command files.
10. **All in one pass**: Complete refactor in single session.
11. **Always exit 0 from auth status**: Use JSON field for auth state.
