# Secret Standards

## Scope

The CLI-tools secret manager is only for CLI-tool credentials. Nothing outside CLI tools should use it.

Use it for any token, API key, username, password, or other secret that:

- belongs to a CLI tool under `<cli-tools-root>`;
- must survive sessions; and
- must be readable by CLI-tool agents, scripts, or service-specific CLI workflows.

Do not use it for Cody, CourseCraft, generic agent workflows, project-specific automation outside `cli-tools`, or non-CLI secrets.

For CLI-tool work, reusable human-supplied secrets must be stored and retrieved through the CLI-tools secret manager. Do not tell users or agents to place those secrets in any `.env` file.

## Canonical Store

The secret manager lives at:

```bash
<cli-tools-root>/_repo/_secret-manager/secrets.sh
```

It is backed by a dedicated macOS Keychain file in the CLI-tools user profile
directory:

```text
~/.local/share/cli-tools/cli-tools.keychain-db
```

The Keychain service namespace is `cli-tools`.

Supported commands:

```bash
<cli-tools-root>/_repo/_secret-manager/secrets.sh [--remote-host <host>] set --tool <cli-tool> --type <type> [value]
<cli-tools-root>/_repo/_secret-manager/secrets.sh [--remote-host <host>] set <name> [value]
<cli-tools-root>/_repo/_secret-manager/secrets.sh [--remote-host <host>] rename <old-name> --tool <cli-tool> --type <type>
<cli-tools-root>/_repo/_secret-manager/secrets.sh [--remote-host <host>] get <name>
<cli-tools-root>/_repo/_secret-manager/secrets.sh [--remote-host <host>] has <name>
<cli-tools-root>/_repo/_secret-manager/secrets.sh [--remote-host <host>] delete <name>
<cli-tools-root>/_repo/_secret-manager/secrets.sh [--remote-host <host>] list
```

Use stdin or `SECRET_VALUE` for secret values so they do not appear in shell history:

```bash
printf '%s' "$SECRET_VALUE" | <cli-tools-root>/_repo/_secret-manager/secrets.sh set --tool <cli-tool> --type <type>
SECRET_VALUE="$SECRET_VALUE" <cli-tools-root>/_repo/_secret-manager/secrets.sh set --tool <cli-tool> --type <type>
```

For remote hosts, run the same command with `--remote-host <host>`. The secret-manager copies `set` payloads to a private temp file on the remote host instead of placing them in the SSH command line or streaming them over SSH stdin.

For non-interactive remote sessions where `CLI_TOOLS_KEYCHAIN` points at a
custom locked remote keychain, include `--remote-unlock-secret
<local-secret-name>`. The value of that local secret is copied to a private
remote temp file and used to unlock the remote keychain in the same SSH command
before the requested secret operation runs:

```bash
CLI_TOOLS_KEYCHAIN=/path/to/custom.keychain-db \
  <cli-tools-root>/_repo/_secret-manager/secrets.sh --remote-host <host> --remote-unlock-secret <unlock-secret-name> set --tool <cli-tool> --type <type>
```

Use the explicit unlock option instead of running `security unlock-keychain` in a separate SSH command. macOS Keychain access can be session-scoped, so a separate SSH unlock does not reliably apply to the later secret-manager command.

## Required Workflow

Before asking Adam for any CLI-tool credential:

1. Run `list` or `has <name>` against the CLI-tools secret manager.
2. If the secret exists, retrieve it with `get <name>` and use it.
3. If the secret is missing, use the `lastpass` CLI tool to look it up (e.g., `lastpass items list --filter "name:like:%<service-name>%" --table`). If found, retrieve the value with the `lastpass` CLI and store it in the CLI-tools secret manager with `set --tool <cli-tool> --type <type>`.
4. If not found in LastPass, inspect the service's login page using browser automation (e.g., via `playwright-cli` or `ui-web-test-engineer`) to see if it supports third-party authentication providers (like Google, Microsoft, Apple). If it does, ask Adam if he would like to use one of those providers.
5. Ask Adam for manual credentials only if the credential cannot be found in the secret manager, cannot be found via the `lastpass` CLI, and third-party auth is either unsupported or declined by Adam.
6. Store any newly provided reusable CLI-tool credential immediately with `set <name>`.

Never print secret values in logs, final answers, test output, screenshots, or command examples.

When a missing credential is an expected diagnostic result, do not run
`has <name>` as a bare command. Shape the expected miss so the non-zero status
is consumed and the result is explicit:

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

## Interactive Prompt Automation

Prefer non-echoing command input such as stdin, `SECRET_VALUE`, or a first-class CLI flag over automating an interactive credential prompt. Do not automate CLI credential prompts with `expect` while user logging is enabled. `expect` can echo sent input into terminal output, transcripts, and logs even when the underlying prompt would hide the value.

When `expect` is unavoidable, disable logging before sending any secret and re-enable it only after the prompt has advanced past the secret input:

Before launching `auth login --force`, capture every value the automation will
send from the CLI-tools secret manager or from a pre-force snapshot of the
profile. Do not read CLIENT_ID, CLIENT_SECRET, passwords, API keys, or other
prompt inputs from the target profile after the forced login process has
started. A forced auth flow is allowed to clear stale runtime profile state
before prompting, and older/custom CLIs may have cleared static credential
fields as well; reading from the profile at that point can turn the sent value
empty and make Expect loop on prompts such as `Enter Client ID:`. Treat the
secret manager (or the pre-force snapshot) as the source for Expect environment
variables, validate only that each variable is non-empty without printing it,
then spawn the forced login.

```tcl
set timeout -1
log_user 1
spawn <cli> auth login
expect "Client ID:"
send -- "$env(CLIENT_ID)\r"
expect "Client Secret:"
log_user 0
send -- "$env(CLIENT_SECRET)\r"
expect {
    "Redirect URI:" {
        log_user 1
        send -- "$env(REDIRECT_URI)\r"
    }
    eof {
        log_user 1
    }
}
```

Never leave `log_user 1` active while sending passwords, API keys, OAuth client secrets, refresh tokens, recovery codes, or MFA values. Do not paste secrets into Terminal.app or GUI prompts through Computer Use; use the CLI-tools secret manager or the CLI's own non-echoing input path.

If you write an `expect` helper script to a task workspace, do not execute the
generated file path directly from Bash. Agent-created helper files are not
guaranteed to have an executable bit, so direct execution can fail with
`Permission denied` before Expect runs. Invoke the interpreter explicitly:

```bash
expect /path/to/auth_login.expect
```

Use `chmod +x` only when a durable checked-in script intentionally has a valid
shebang and direct execution is part of its contract; it is not the default fix
for generated auth helpers.

## Naming

The canonical naming schema is `<cli-tool>-<type>`.

```text
<cli-tool>-<type>
```

Examples:

```text
venmo-password
venmo-username
impact-password
impact-username
github-pat
```

Use the tool/type parameters when storing human-entered values:

```bash
<cli-tools-root>/_repo/_secret-manager/secrets.sh set --tool venmo --type username
<cli-tools-root>/_repo/_secret-manager/secrets.sh set --tool venmo --type password
```

Use `rename <old-name> --tool <cli-tool> --type <type>` to move old names into
the canonical schema. Reuse existing names. Check `list` before inventing a new
name.

## Boundary with CLI Runtime State

The secret manager does not replace `cli_tools_shared.config.BaseConfig`.

`auth login`, OAuth refresh, profile switching, and browser session state still write the active profile under:

```text
~/.local/share/cli-tools/<tool>/authentication_profiles/<profile>/
```

The tool user profile folder is `~/.local/share/cli-tools/<tool>`. Non-authentication configuration lives in its root `.env`; authentication profile directories contain auth state such as `.env`, browser session data, `profile.json`, and auth-tied cache files.

Use the secret manager as the cross-session source for reusable raw credentials that an agent or script needs before or during a CLI auth flow. Let the CLI's normal auth flow persist runtime tokens and sessions through `BaseConfig`.

This is the boundary:
- Secret manager: reusable raw credentials supplied by a human or another external system
- `.env` files under `~/.local/share/cli-tools/...`: non-secret config and CLI-managed runtime auth state written by the tool itself

Agents must not ask users to edit `.env` files with passwords, API keys, client secrets, refresh tokens, or other reusable secrets.

## Prohibited Stores

Do not store CLI-tool secrets in:

- old user-level secret manager scripts;
- LastPass;
- general agent instructions;
- project docs outside `cli-tools`;
- repo-local `.env` files under `<cli-tools-root>/<tool>`;
- user-data `.env` files under `~/.local/share/cli-tools/<tool>/` or `authentication_profiles/<profile>/` when the value is a reusable raw credential;
- committed `.env.example` files.

Service-specific CLIs still own their own auth behavior. Do not shadow a service CLI's saved runtime state in the secret manager unless an agent or script genuinely needs raw reusable access outside that CLI's auth state.

## Keychain Prompt

The first read of a Keychain item by a new binary may trigger a macOS GUI prompt. That is expected. Ask Adam to click Allow instead of working around the prompt.

## Keychain Item Access Policy

The canonical access policy for CLI-tools Keychain items lives at:

```bash
<cli-tools-root>/_repo/_secret-manager/access-policy.conf
```

The apply script is deployment-layout based. It does not require a Git checkout, `.git` metadata, or the `git` binary; it resolves the bundled logger from its installed `_repo/_secret-manager` path.

Apply it with:

```bash
<cli-tools-root>/_repo/_secret-manager/apply-access-policy.sh
```

For noninteractive apply runs, provide the keychain password through stdin or an existing CLI-tools secret:

```bash
printf '%s\n' "$KEYCHAIN_PASSWORD" | <cli-tools-root>/_repo/_secret-manager/apply-access-policy.sh --keychain-password-stdin
<cli-tools-root>/_repo/_secret-manager/apply-access-policy.sh --keychain-password-secret <name>
```

The policy uses `allow-process <partition-id> <path>` records. The path makes the policy reviewable, while the partition ID is what macOS applies with `security set-generic-password-partition-list`. This avoids one-off permissions fixes for launch jobs and other noninteractive CLI-tool workflows.

This policy controls item access. The default managed keychain is created and
unlocked by the helper; custom keychains still need to be unlocked in the same
session before reading secrets.

For noninteractive automation hosts, configure the job to use the signed binary paths listed in `access-policy.conf`. Avoid unsigned shim binaries unless the policy intentionally grants the broader `unsigned:` partition ID.
