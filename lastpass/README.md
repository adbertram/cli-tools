# LastPass CLI

## DESCRIPTION

The `lastpass` CLI wraps lpass with standardized cli-tools behavior.

Use it when you need the underlying command exposed through cli-tools JSON/table conventions for agents, automation, or terminal workflows.

## Prerequisites

This CLI wraps the `lpass` command-line tool. Install it first:

```bash
# macOS
brew install lastpass-cli

# Debian/Ubuntu
sudo apt install lastpass-cli

# Fedora
sudo dnf install lastpass-cli
```

## TLS certificate pin repair

The official LastPass CLI 1.6.1 pin list does not include GlobalSign Root E46.
LastPass now serves an E46 certificate chain, so affected installations fail
with `SSL peer certificate or SSH remote key was not OK` despite a valid
certificate chain and hostname. Wrapper errors identify TLS verification failures
without printing arbitrary upstream output or vault values.

On macOS, rebuild the official package with the verified E46 root pin:

```bash
brew install lastpass-cli cmake pkgconf
python3 scripts/repair-lpass-tls.py
python3 scripts/verify-lpass-tls.py
lastpass auth status
lastpass items list --filter 'name:like:%github%' --limit 0
```

Run these commands from this tool directory with Python 3.12 or later. The repair
verifies SHA256 digests of official 1.6.1 source, both official patches shipped by
Homebrew, and the GlobalSign root certificate. It independently derives and
checks the root SPKI pin. It adds that pin while retaining every existing pin,
CA-chain validation, hostname validation, and the OpenSSL pin callback. It builds
against Homebrew OpenSSL and curl, then atomically replaces only the executable
inside the official Homebrew `lastpass-cli` package. It refuses unmanaged binaries
and missing build prerequisites. It never reads or changes vault credentials.

A later Homebrew upgrade or reinstall replaces this rebuilt executable. Rerun the
repair if the upstream package still lacks E46. The verification script presents
an untrusted certificate for the correct LastPass hostname to the actual installed
binary, using an isolated temporary vault and a reserved synthetic email. It
requires TLS rejection before any application bytes are sent; it never disables
verification or uses real account credentials.

Root certificate source: [GlobalSign Root Certificates](https://support.globalsign.com/ca-certificates/root-certificates/globalsign-root-certificates).
E46 certificate SHA256: `cbb9c44d84b8043e1050ea31a69f514955d7bfd2e2c6b49301019ad61d9f5058`.
E46 SPKI SHA256 (Base64): `4EoCLOMvTM8sf2BGKHuCijKpCfXnUUR/g/0scfb9gXM=`.

## Quick Start

```bash
# Check if lpass is installed and you're logged in
lastpass auth status

# Login to LastPass
lastpass auth login --email you@example.com

# List vault entries
lastpass items list

# Get a specific entry
lastpass items get github.com

# Inspect field names without printing field values
lastpass items fields github.com

# Copy password to clipboard
lastpass items password github.com --clip
```

## Commands

### Authentication

```bash
# Login (prompts for master password)
lastpass auth login --email you@example.com
lastpass auth login -e you@example.com

# Check status
lastpass auth status
lastpass auth status

# Sync vault with server
lastpass auth sync

# Logout
lastpass auth logout
lastpass auth logout --force
```

### Vault Entries

```bash
# List all entries
lastpass items list
lastpass items list

# List entries in a folder
lastpass items list Work
lastpass items list "Work/Servers"

# Filter entries
lastpass items list --filter "name:like:%github%"

# Filter narrowed entries by LastPass category/note type
lastpass items list --filter "name:like:%hsa%" --category "Payment Cards" --table
lastpass items list Work --category "Credit Card" --table

# List only selected fields (dot notation supported)
lastpass items list --properties "id,name"

# Get entry details (password masked by default)
lastpass items get github.com
lastpass items get github.com --table

# Get only selected non-secret fields (dot notation supported).
# Absent fields project an explicit null.
lastpass items get github.com --properties "id,name,URL,Username"
lastpass items get github.com -p "id,name"

# Secret fields are refused through --properties — this errors and never
# prints the password. Use `items password` or `--show-password` instead.
# lastpass items get github.com --properties "password"   # Error, exit 1

# Get entry with secret fields visible (cannot be combined with --properties)
lastpass items get github.com --show-password

# List field names and sensitivity metadata only. Values are never printed.
lastpass items fields github.com
lastpass items fields github.com --table

# Get just the password
lastpass items password github.com

# Copy password to clipboard
lastpass items password github.com --clip

# Get just the username
lastpass items username github.com

# Update a password without placing it in process arguments
lastpass items update github.com --password-stdin <<<"$NEW_PASSWORD"
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting

### JSON Output Example

```bash
lastpass items list | jq '.[0]'
# {
#   "id": "1234567890123456789",
#   "name": "GitHub",
#   "group": "Work",
#   "full_path": "Work/GitHub"
# }
```

### Scripting Examples

```bash
# Get password for a site
PASSWORD=$(lastpass items password github.com)

# List all entries as JSON
lastpass items list > vault_backup.json

# Find entries with "github" in name
lastpass items list --filter "name:ilike:%github%"

# Find saved payment cards without printing card numbers.
# Narrow first; category filtering refuses broad vault scans.
lastpass items list --filter "name:ilike:%hsa%" --category "Payment Cards" --table
```

### Profiles

```bash
# List all profiles
lastpass auth profiles list

# Create a new profile
lastpass auth profiles create work

# Set a profile as default
lastpass auth profiles select work

# Delete a profile
lastpass auth profiles delete work --force
```

## How It Works

This CLI wraps the `lpass` CLI:

- **`auth` commands** delegate to `lpass login`, `lpass logout`, `lpass status`
- **`items` commands** call `lpass ls` and `lpass show`, parse output to JSON/table
- **`items fields`** projects names from the existing masked detail path; raw
  field values are never logged or included in command errors
- **Credentials** are handled entirely by lpass (stored in system keychain)

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Not authenticated / CLI not available |
| 3 | Ambiguous lookup — multiple entries matched (see below) |
| 130 | User interrupted (Ctrl+C) |

## Ambiguous Lookups (Multiple Matches)

`items get`, `items fields`, `items username`, and `items password` take an
entry name or ID. When a name matches more than one vault entry, the command
exits `3` and prints a parseable JSON object on stdout (not freeform text) so
automation can pick an entry by ID and re-run the lookup:

```bash
lastpass items username google.com
# exit 3
# {
#   "error": "multiple_matches",
#   "query": "google.com",
#   "matches": [
#     {"id": "8969039733861907751", "name": "google.com", "group": "Email", "full_path": "Email/google.com"},
#     {"id": "7600439653866760487", "name": "google.com", "group": "", "full_path": "google.com"}
#   ]
# }

# Disambiguate by ID — single matches return the raw value as before:
FIRST_ID=$(lastpass items username google.com | jq -r '.matches[0].id')
lastpass items username "$FIRST_ID"
```

## Requirements

- Python 3.9+
- `lpass` CLI installed and in PATH
- Dependencies (installed automatically):
  - typer
  - python-dotenv

## License

MIT

## Additional Commands

### Cache

```bash
lastpass cache --help
```
