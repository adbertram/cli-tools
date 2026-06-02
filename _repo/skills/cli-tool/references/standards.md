# CLI Tool Standards (Index)

This file has been split into focused reference files. Load only what you need:

| File | Contents |
|------|----------|
| `output-standards.md` | Output streams, format rules, table/JSON truncation, response formats, list command requirements, hard requirements, `--properties/-p` field selection |
| `auth-standards.md` | Authentication by credential type, supported credential types, multiple credentials, dual-auth gates, COMMAND_CREDENTIALS, `--force`, `--credential-type`, wrapper auth, OAuth login flow |
| `config-standards.md` | `.env` file rules, config.py path resolution, env variable naming, token refresh pattern |
| `command-standards.md` | Command naming (noun-verb), option standards, exit codes, bidirectional list/get, no-args-is-help, help text, search commands |
| `model-standards.md` | Output-first data shapes, optional local models, AIInstruction, SerializeAsAny, no fallback logic |
| `infra-standards.md` | AI review checklist, warning suppression, activity logging, repository standards, documentation standards, global access/symlinks, shell completion, common patterns |
