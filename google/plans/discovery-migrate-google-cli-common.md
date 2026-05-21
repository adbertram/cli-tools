# Discovery: Migrate Google CLI to cli-tools-shared Framework

## Codebase Context

### Key Files
- `google_cli/config.py` — Custom Config class (not BaseConfig). Manages credentials.json and token.json paths. Has searchconsole_site and analytics_property_id properties.
- `google_cli/client.py` — GoogleClient with _authenticate() using InstalledAppFlow. Global _client singleton. SCOPES list. get_client() returns cached singleton.
- `google_cli/commands/auth.py` — Hand-rolled login, status, logout. Login accepts --oauth-client-id/--oauth-client-secret.
- `google_cli/main.py` — Registers 9 sub-apps (analytics, auth, calendar, cloud, docs, drive, gmail, searchconsole, sheets). No profiles.
- `google_cli/filters.py` — Local duplicate of cli_tools_shared.filters.
- `google_cli/filter_translator.py` — Google-specific filter translation (Gmail, Drive, Calendar, Cloud, Docs).
- `google_cli/output.py` — Already re-exports from cli_tools_shared.output.
- `.env.example` — No IS_DEFAULT_PROFILE, no GOOGLE_SEARCHCONSOLE_SITE, no GOOGLE_ANALYTICS_PROPERTY_ID.
- `pyproject.toml` — Missing cli-tools-shared dependency.
- No `.gitignore` — credentials.json and token.json exposed.

### Reference CLIs
- `cloudflare` — Config(BaseConfig) with CREDENTIAL_TYPES = [CredentialType.API_KEY]. Profile-keyed _configs dict.
- `slack` — CREDENTIAL_TYPES = [CredentialType.CUSTOM] with login_handler pattern.

### Integration Points
- All 9 command files call get_client() → GoogleClient. get_client() reads from get_config().
- searchconsole.py and analytics.py call get_config() directly for site/property env vars.
- filters.py is local duplicate — can be replaced with cli_tools_shared.filters.

## Q&A Results

### Wave: Clarify Task

**Q:** Where should per-profile tokens be stored?
**A:** Profile data dir — authentication_profiles/<name>/token.json using config.get_profile_data_dir()

**Q:** Do profiles share one OAuth app (credentials.json) or each gets its own?
**A:** Per-profile — each profile gets its own credentials.json

**Q:** How should initial setup work after removing --oauth-client-id/--oauth-client-secret?
**A:** Drop flags, file only — users must place credentials.json in authentication_profiles/<name>/ manually before first login

**Q:** What should CUSTOM_REQUIRED_FIELDS contain?
**A:** Empty + override — CUSTOM_REQUIRED_FIELDS=[] and override has_credentials() to check token.json exists in profile data dir

**Q:** Should GOOGLE_SEARCHCONSOLE_SITE and GOOGLE_ANALYTICS_PROPERTY_ID be per-profile?
**A:** Yes, per-profile in each .env file

### Wave: Technical Decisions

**Q:** Should data commands support --profile flag?
**A:** All commands — every command gets --profile

**Q:** Replace local filters.py with cli_tools_shared?
**A:** Yes, replace with common

**Q:** How should client.py handle multiple profiles?
**A:** This needs to be Phase 1 as it's a prereq — refactor the global client to properly support profiles

**Q:** Use auth profiles from create_auth_app() or hand-written?
**A:** Use create_auth_app(); it mounts the standard profiles app under auth.

**Q:** Where should per-profile credentials.json be stored?
**A:** In authentication_profiles/<name>/ alongside token.json

**Q:** Remove redundant pip install cli-tools-shared from install.sh?
**A:** Leave as-is

### Wave: Success & Scope

**Q:** What should .gitignore contain?
**A:** Standard set: .env, .env.*, .venv/, token.json, credentials.json, __pycache__/, *.egg-info/, authentication_profiles/

**Q:** What's Phase 1 scope?
**A:** Phase 1 = refactoring the global client to properly support profiles. Phase 2 = full framework migration (BaseConfig, create_auth_app, auth profiles command, test compliance, filters, etc.)

### Wave: Token Migration

**Q:** Auto-copy existing token.json to default profile?
**A:** No authentication_profiles/default — all profiles go in authentication_profiles/<name> folders with explicitly named profiles. No auto-migration; require fresh login.

## Key Decisions

1. **Two-phase approach**: Phase 1 = profile-aware client. Phase 2 = cli-tools-shared framework migration.
2. **Per-profile isolation**: Each profile gets its own directory in authentication_profiles/<name>/ containing both credentials.json and token.json.
3. **CredentialType.CUSTOM** with empty required fields + has_credentials() override checking token.json existence.
4. **--profile on ALL commands** — not just auth, but drive, gmail, calendar, etc.
5. **No auto-migration** of existing token.json — require fresh auth login per profile.
6. **Replace local filters.py** with cli_tools_shared.filters.
7. **create_auth_app()** for auth commands, including `auth profiles`.
8. **Drop --oauth-client-id/--oauth-client-secret** flags — users place credentials.json manually.
