# Secret Manager

CLI-tools-only secret store backed by macOS Keychain.

```bash
secret-manager/secrets.sh set <name> [value]
secret-manager/secrets.sh get <name>
secret-manager/secrets.sh has <name>
secret-manager/secrets.sh delete <name>
secret-manager/secrets.sh list
```

Service namespace: `cli-tools`

This helper is for CLI tool code and CLI-tool skills only. Do not use it from general agent instructions, project workflows, or non-CLI automation.
