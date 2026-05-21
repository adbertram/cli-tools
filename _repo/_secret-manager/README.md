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
