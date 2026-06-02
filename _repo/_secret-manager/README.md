# Secret Manager

CLI-tools-only secret store backed by a dedicated macOS Keychain file in the
CLI-tools user profile directory.

```bash
_repo/_secret-manager/secrets.sh [--remote-host <host>] set --tool <cli-tool> --type <type> [value]
_repo/_secret-manager/secrets.sh [--remote-host <host>] set <name> [value]
_repo/_secret-manager/secrets.sh [--remote-host <host>] rename <old-name> --tool <cli-tool> --type <type>
_repo/_secret-manager/secrets.sh [--remote-host <host>] get <name>
_repo/_secret-manager/secrets.sh [--remote-host <host>] has <name>
_repo/_secret-manager/secrets.sh [--remote-host <host>] delete <name>
_repo/_secret-manager/secrets.sh [--remote-host <host>] list
```

Canonical secret names use `<cli-tool>-<type>`. Store human-entered values with
the explicit tool/type form so the helper constructs the name:

```bash
printf '%s' "$SECRET_VALUE" | _repo/_secret-manager/secrets.sh set --tool venmo --type username
```

Service namespace: `cli-tools`

Default keychain: `~/.local/share/cli-tools/cli-tools.keychain-db`

## Portability and access

The default managed keychain is created with an empty keychain-file unlock
password so CLI tools can unlock it non-interactively. That password is not a
CLI service credential and no CLI service password is hardcoded in source.

If this keychain file is copied to another macOS computer, it can be unlocked
there with an empty password. The main protections are local filesystem
permissions on the keychain file and macOS Keychain item access controls. Keep
the file private and do not copy it to another machine unless you intend to move
the stored CLI-tool secrets with it.

The access policy applies macOS partition IDs to the items in this keychain.
Those IDs control which local signed process classes can read secrets without a
GUI prompt after the keychain is unlocked. They are not a protection boundary
against someone who already has a copy of the keychain file and can unlock it.

This helper is for CLI tool code and CLI-tool skills only. Do not use it from general agent instructions, project workflows, or non-CLI automation.

Remote mode runs the same secret-manager command on the target host over SSH. For `set`, the value is copied to a private temp file on the remote host and read there, so the secret never appears in the SSH command line and does not share the SSH stdin channel with a remote keychain unlock prompt. The default managed keychain is created and unlocked by the helper on the target host.

For non-interactive remote sessions that explicitly set `CLI_TOOLS_KEYCHAIN` to
a custom locked keychain, pass a local secret containing that remote keychain
password:

```bash
CLI_TOOLS_KEYCHAIN=/path/to/custom.keychain-db \
  _repo/_secret-manager/secrets.sh --remote-host remote-host --remote-unlock-secret remote-keychain-password set --tool <cli-tool> --type <type>
```

The unlock secret is copied to a private remote temp file and used to unlock the
custom remote keychain in the same SSH command before the requested secret
operation runs. Without `--remote-unlock-secret`, a locked custom remote
keychain still requires an interactive terminal.

## Access policy

Keychain item access is standardized in:

```bash
_repo/_secret-manager/access-policy.conf
```

The apply script is deployment-layout based. It does not require a Git checkout, `.git` metadata, or the `git` binary; it resolves the bundled logger from its installed `_repo/_secret-manager` path.

Apply it with:

```bash
_repo/_secret-manager/apply-access-policy.sh
```

The default managed keychain does not need a password prompt. For a custom
keychain, provide the keychain password through stdin or a CLI-tools secret:

```bash
printf '%s\n' "$KEYCHAIN_PASSWORD" | _repo/_secret-manager/apply-access-policy.sh --keychain-password-stdin
_repo/_secret-manager/apply-access-policy.sh --keychain-password-secret <name>
```

The policy applies macOS partition IDs to each target generic-password item in the `cli-tools` service. This controls which signed process classes can read the item without a GUI prompt. It does not replace runtime keychain unlocking for custom keychains; the default managed keychain is unlocked by the helper.

## Import and export

Use the repo-owned import/export utility when moving the CLI-tools keychain and
authentication profiles:

```bash
_repo/_scripts/import_export.py export /path/to/cli-tools-export.tar.gz
_repo/_scripts/import_export.py import /path/to/cli-tools-export.tar.gz
```

Exports include the managed `cli-tools.keychain-db`, tool-level `.env` files,
and authentication profile directories. Browser profiles keep auth-bearing state
such as cookies and local storage, while generated cache/model directories are
left out. By default, profile `.env` files keep their `secret://...`
placeholders.

For a temporary migration archive that must not depend on the source keychain,
explicitly inline profile secrets:

```bash
_repo/_scripts/import_export.py export /path/to/cli-tools-export.tar.gz --plain-text-secrets
```

On import, any plain-text sensitive values found in authentication profile
`.env` files are stored through `_repo/_secret-manager/secrets.sh` and replaced
with `secret://...` placeholders.
