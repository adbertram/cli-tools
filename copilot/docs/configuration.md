# Configuration & Storage

Copilot follows the cli-tools user profile layout. Profile data and secret
storage are aligned with the shared CLI contract.

## Path Layout

| Purpose | Linux / macOS | Windows |
| --- | --- | --- |
| Tool config `.env` | `~/.local/share/cli-tools/copilot/.env` | `%APPDATA%\cli-tools\copilot\.env` |
| Profile `.env` files | `~/.local/share/cli-tools/copilot/authentication_profiles/<name>/.env` | `%APPDATA%\cli-tools\copilot\authentication_profiles\<name>\.env` |
| Token caches | `~/.local/share/cli-tools/copilot/authentication_profiles/<name>/cache/` | `%APPDATA%\cli-tools\copilot\authentication_profiles\<name>\cache\` |
| Secrets | CLI-tools secret manager; profile `.env` contains `secret://...` placeholders | CLI-tools secret manager; profile `.env` contains `secret://...` placeholders |

## Override Env Vars

The shared cli-tools runtime follows `XDG_DATA_HOME` on Linux/macOS:

```bash
XDG_DATA_HOME=$HOME/.local/share copilot auth status
```

Copilot no longer uses `COPILOT_CONFIG_DIR`, `COPILOT_CACHE_DIR`,
`XDG_CONFIG_HOME`, or `XDG_CACHE_HOME` for active profile storage.

## Secrets

The following fields are stored by the CLI-tools secret manager. The active
profile `.env` stores only a `secret://<name>` placeholder for each configured
secret:

- `AZURE_CLIENT_SECRET`
- `M365_SDK_CLIENT_SECRET`
- `DIRECTLINE_SECRET`

They are **never** written to profile `.env` files as plain text.

To set or replace a secret:

```bash
copilot config set-secret AZURE_CLIENT_SECRET            # prompts (hidden)
copilot config set-secret AZURE_CLIENT_SECRET --value '…' --profile staging
```

For the active profile, that command writes a profile reference like:

```dotenv
AZURE_CLIENT_SECRET=secret://copilot-azure-client-secret
```

## Inspect Resolved Paths

```bash
copilot config show               # table of all paths + active profile
copilot config show --json        # same data as JSON

copilot config path config        # ~/.local/share/cli-tools/copilot
copilot config path cache         # active profile cache directory
copilot config path profiles      # ~/.local/share/cli-tools/copilot/authentication_profiles
copilot config path active        # the .env currently in use
```

## Cutover Requirement

The Copilot CLI reads only the canonical cli-tools profile layout. It does not
move or inspect legacy profile files at runtime.

Before running the tool, place profile files under:

```bash
~/.local/share/cli-tools/copilot/authentication_profiles/<profile>/.env
```

Store reusable secrets with `copilot config set-secret`; do not place raw
secret values in the profile `.env` files.
