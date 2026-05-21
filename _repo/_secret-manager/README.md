# Secret Manager

CLI-tools-only secret store backed by macOS Keychain.

```bash
_repo/_secret-manager/secrets.sh set <name> [value]
_repo/_secret-manager/secrets.sh get <name>
_repo/_secret-manager/secrets.sh has <name>
_repo/_secret-manager/secrets.sh delete <name>
_repo/_secret-manager/secrets.sh list
```

Service namespace: `cli-tools`

This helper is for CLI tool code and CLI-tool skills only. Do not use it from general agent instructions, project workflows, or non-CLI automation.
