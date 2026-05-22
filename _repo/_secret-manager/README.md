# Secret Manager

CLI-tools-only secret store backed by macOS Keychain.

```bash
_repo/_secret-manager/secrets.sh [--remote-host <host>] set <name> [value]
_repo/_secret-manager/secrets.sh [--remote-host <host>] get <name>
_repo/_secret-manager/secrets.sh [--remote-host <host>] has <name>
_repo/_secret-manager/secrets.sh [--remote-host <host>] delete <name>
_repo/_secret-manager/secrets.sh [--remote-host <host>] list
```

Service namespace: `cli-tools`

This helper is for CLI tool code and CLI-tool skills only. Do not use it from general agent instructions, project workflows, or non-CLI automation.

Remote mode runs the same secret-manager command on the target host over SSH. For `set`, the value is copied to a private temp file on the remote host and read there, so the secret never appears in the SSH command line and does not share the SSH stdin channel with a remote keychain unlock prompt. If the remote macOS login keychain is locked, the script unlocks it on the remote host before retrying the canonical Keychain operation. Re-run from an interactive terminal when the remote host needs a keychain-password prompt.

For non-interactive remote sessions, pass a local secret containing the remote keychain password:

```bash
_repo/_secret-manager/secrets.sh --remote-host adam-server --remote-unlock-secret adam-server-sudo set <name>
```

The unlock secret is copied to a private remote temp file and used to unlock the remote login keychain in the same SSH command before the requested secret operation runs. Without `--remote-unlock-secret`, a locked remote macOS login keychain still requires an interactive terminal.

## Access policy

Keychain item access is standardized in:

```bash
_repo/_secret-manager/access-policy.conf
```

The apply script is deployment-layout based. It does not require a Git checkout, `.git` metadata, or the `git` binary; it resolves the bundled logger from its installed `_repo/_secret-manager` path.

Apply it with:

```bash
_repo/_secret-manager/apply-access-policy.sh --prompt-keychain-password
```

For noninteractive use, provide the keychain password through stdin or a CLI-tools secret:

```bash
printf '%s\n' "$KEYCHAIN_PASSWORD" | _repo/_secret-manager/apply-access-policy.sh --keychain-password-stdin
_repo/_secret-manager/apply-access-policy.sh --keychain-password-secret <name>
```

The policy applies macOS partition IDs to each target generic-password item in the `cli-tools` service. This controls which signed process classes can read the item without a GUI prompt. It does not replace runtime keychain unlocking; launch jobs that run with a locked login keychain still need to unlock that keychain in the same session before reading secrets.

For n8n Codex nodes on adam-server, set the node's Codex binary path to:

```text
/Applications/Codex.app/Contents/Resources/codex
```

That binary is signed by the Team ID declared in `access-policy.conf`. Do not point n8n at the unsigned Homebrew `codex` shim unless the policy intentionally grants the broader `unsigned:` partition ID.
