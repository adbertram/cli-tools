---
name: cli-tool-secrets
description: >
  MANDATORY: Use this skill for ALL CLI-tools secret-manager work: checking,
  storing, retrieving, deleting, naming, documenting, or troubleshooting reusable
  CLI-tool credentials. DO NOT put reusable CLI-tool secrets in `.env` files,
  LastPass, source files, general agent instructions, or non-CLI project
  workflows. Triggers: CLI tool secret, cli-tools secret manager, secret store,
  reusable CLI credentials, API key for a CLI, CLI username password, client
  secret, access token.
---

<objective>
Use the CLI-tools-only secret store correctly, with one source of truth for
reusable credentials used by CLI tools and CLI-tool agents.
</objective>

<source_of_truth>
The canonical helper is:

```bash
<cli-tools-root>/_repo/_secret-manager/secrets.sh
```

It is backed by the macOS Keychain service namespace `cli-tools`.
The default Keychain file is
`~/.local/share/cli-tools/cli-tools.keychain-db`, alongside the CLI-tools user
profile directories.

For full lifecycle policy, read
`<cli-tools-root>/_repo/skills/cli-tool/references/secrets.md`.
If the task is broader CLI creation, update, testing, or auth implementation,
also load the repo-owned `cli-tool` skill and follow its agent-routing rules.
</source_of_truth>

<scope>
Use this store only for reusable human-supplied credentials that belong to CLI
tools under `<cli-tools-root>` and must survive sessions:
API keys, usernames, passwords, client secrets, personal access tokens, and
other long-lived raw credentials.

Do not use it for Cody, CourseCraft, generic project automation, non-CLI
workflows, or service runtime state owned by a CLI's auth system.
</scope>

<quick_start>
1. Choose the CLI tool name and the secret type. The canonical naming schema is `<cli-tool>-<type>`, where both parts are lowercase hyphenated strings and `<cli-tool>` is the CLI command name.
2. Check for an existing name before asking Adam for a credential:
   ```bash
   <cli-tools-root>/_repo/_secret-manager/secrets.sh list
   <cli-tools-root>/_repo/_secret-manager/secrets.sh has <name>
   ```
   When a missing secret is an expected diagnostic result, shape `has` so the
   non-zero status is consumed and reported explicitly:
   ```bash
   if output="$(<cli-tools-root>/_repo/_secret-manager/secrets.sh has <name> 2>&1)"; then
     printf 'SECRET_PRESENT:%s\n' '<name>'
   else
     rc=$?
     if [ "$rc" -eq 1 ]; then
       printf 'EXPECTED_MISSING_SECRET:%s\n' '<name>'
       exit 0
     fi
     printf '%s\n' "$output" >&2
     exit "$rc"
   fi
   ```
3. If the secret exists, retrieve it with `get <name>` and use it without
   printing the value.
4. Ask Adam only for missing reusable credentials.
5. Store new values immediately through stdin or `SECRET_VALUE`, not inline in
   command examples or `.env` files:
   ```bash
   printf '%s' "$SECRET_VALUE" | <cli-tools-root>/_repo/_secret-manager/secrets.sh set --tool <cli-tool> --type <type>
   SECRET_VALUE="$SECRET_VALUE" <cli-tools-root>/_repo/_secret-manager/secrets.sh set --tool <cli-tool> --type <type>
   ```
6. Verify storage with `has <name>`. Do not verify by echoing the secret value.
</quick_start>

<commands>
```bash
<cli-tools-root>/_repo/_secret-manager/secrets.sh set --tool <cli-tool> --type <type> [value]
<cli-tools-root>/_repo/_secret-manager/secrets.sh set <name> [value]
<cli-tools-root>/_repo/_secret-manager/secrets.sh rename <old-name> --tool <cli-tool> --type <type>
<cli-tools-root>/_repo/_secret-manager/secrets.sh get <name>
<cli-tools-root>/_repo/_secret-manager/secrets.sh has <name>
<cli-tools-root>/_repo/_secret-manager/secrets.sh delete <name>
<cli-tools-root>/_repo/_secret-manager/secrets.sh list
```

Remote host form:

```bash
<cli-tools-root>/_repo/_secret-manager/secrets.sh --remote-host <host> <command> [args]
```

For `set`, prefer stdin or `SECRET_VALUE` so the secret does not appear in shell
history. Remote `set` copies the value through a private temporary file on the
remote host.
</commands>

<boundaries>
- Secret manager: reusable raw credentials that an agent or script needs before
  or during a CLI auth flow.
- CLI auth profiles: runtime tokens, browser session state, profile metadata,
  and auth-tied cache under
  `~/.local/share/cli-tools/<tool>/authentication_profiles/<profile>/`.
- Tool root `.env` files under `~/.local/share/cli-tools/<tool>/`: non-secret
  configuration only.

Never store or document reusable credentials in repo-local `.env` files,
profile `.env` files, `.env.example`, source files, final answers, screenshots,
logs, or general instructions.
</boundaries>

<operational_notes>
- Reuse existing secret names. Run `list` before inventing a new name.
- The canonical naming schema is `<cli-tool>-<type>`.
- New human-entered secrets must be created with `set --tool <cli-tool> --type
  <type>` so the helper constructs `<cli-tool>-<type>`.
- Use `rename <old-name> --tool <cli-tool> --type <type>` when moving old
  names into the canonical schema.
- Never print secret values. If a command returns a value, pipe it directly into
  the consuming command or store it in a local shell variable that is not echoed.
- If macOS prompts for Keychain access, ask Adam to click Allow. Do not route
  around the Keychain prompt.
- A missing secret is not a reason to use LastPass or `.env`; ask Adam for that
  specific missing value and store it here.
</operational_notes>

<success_criteria>
- The needed CLI-tool credential names were checked with `list` or `has`.
- Existing credentials were retrieved without exposing their values.
- Missing reusable credentials were stored with `set` through stdin or
  `SECRET_VALUE`.
- CLI runtime state was left to the CLI's normal auth/profile system.
- No reusable CLI-tool credential was placed in `.env`, docs, source, logs, or
  the final answer.
</success_criteria>
