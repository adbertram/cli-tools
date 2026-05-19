# Configuration & Storage

Copilot follows the XDG Base Directory specification on Linux and macOS,
and uses the standard `%APPDATA%` / `%LOCALAPPDATA%` paths on Windows.
Profile data and secret storage are aligned with public-CLI conventions.

## Path Layout

| Purpose            | Linux / macOS                            | Windows                                    |
|--------------------|------------------------------------------|--------------------------------------------|
| Profile `.env` files | `~/.config/copilot/profiles/<name>.env` | `%APPDATA%\copilot\profiles\<name>.env`    |
| Token caches       | `~/.cache/copilot/`                      | `%LOCALAPPDATA%\copilot\Cache\`            |
| State / logs       | `~/.local/state/copilot/`                | `%LOCALAPPDATA%\copilot\State\`            |
| Secrets            | OS keychain (libsecret / `pass`)         | Windows Credential Manager                 |
| Secrets (macOS)    | macOS Keychain                           | —                                          |

## Override Env Vars

You can override any directory:

```bash
COPILOT_CONFIG_DIR=/opt/copilot/etc copilot auth status      # absolute override
XDG_CONFIG_HOME=$HOME/.dotfiles copilot auth status          # XDG override
```

Precedence: `COPILOT_CONFIG_DIR` > `XDG_CONFIG_HOME/copilot` > platform default.
The same precedence applies to `COPILOT_CACHE_DIR` / `XDG_CACHE_HOME`.

## Secrets in the OS Keychain

The following fields are stored in the OS keychain (service name
`copilot-cli`, username `<profile>:<field>`):

- `AZURE_CLIENT_SECRET`
- `M365_SDK_CLIENT_SECRET`
- `DIRECTLINE_SECRET`

They are **never** written to plain-text `.env` files. To inspect or rotate:

```bash
# macOS — list all copilot-cli entries
security find-generic-password -s copilot-cli

# Linux (libsecret)
secret-tool search service copilot-cli

# Windows (PowerShell)
cmdkey /list:copilot-cli
```

To set or replace a secret:

```bash
copilot config set-secret AZURE_CLIENT_SECRET            # prompts (hidden)
copilot config set-secret AZURE_CLIENT_SECRET --value '…' --profile staging
```

**Linux server prerequisites:** install `libsecret` (e.g.
`sudo apt install libsecret-1-0 gir1.2-secret-1`) for desktop environments,
or `pip install keyrings.alt` plus configure a `pass`-based backend for
headless servers.

## Inspect Resolved Paths

```bash
copilot config show               # table of all paths + active profile
copilot config show --json        # same data as JSON

copilot config path config        # ~/.config/copilot
copilot config path cache         # ~/.cache/copilot
copilot config path profiles      # ~/.config/copilot/profiles
copilot config path active        # the .env currently in use
```

## Migrating From Pre-XDG Installs

Earlier versions of copilot stored `.env` and `.env.<profile>` files inside
the repo or alongside the package source. To move them to the new XDG
layout and stash secrets in the keychain:

```bash
copilot config migrate --dry-run        # preview (no writes)
copilot config migrate                  # interactive, prompts per secret
copilot config migrate --yes            # auto-confirm all secrets
copilot config migrate --skip-secrets   # non-secret values only
```

The migration is idempotent — a `.env.<name>.migrated` marker is written
next to each consumed legacy file. The original `.env` / `.env.<name>`
files are **not** deleted; review the new profiles, run
`copilot auth status`, then delete the legacy files manually.

If a legacy file is detected on startup the CLI prints a one-time
deprecation warning pointing at `copilot config migrate`.
