# progress-servicenow

## DESCRIPTION

Progress ServiceNow CLI automates common Employee Center workflows from the command line. Use it to check authentication, inspect ticket templates, browse catalog entries, and work with ServiceNow tickets through the existing browser-session automation.

## Authentication

`progress1.service-now.com` authenticates through the Progress Entra (Microsoft)
tenant, so an expired session turns every ServiceNow URL into a Microsoft
sign-in page.

`auth login` refreshes that session **non-interactively** — no prompt, no
browser window on your screen:

* the account password is read at sign-in time from the managed `lastpass` CLI
  (entry `4250464594169840461`); it is never stored in this repository, in the
  profile `.env`, or printed anywhere;
* when Entra requests Microsoft Authenticator approval, the CLI switches to the
  account's SMS factor and reads the verification code through the `imessage`
  CLI.

The CLI stops and asks for help only when Entra offers no code-based factor —
i.e. when approval genuinely requires the enrolled device.

```bash
progress-servicenow auth status            # exit 0 when the session is live
progress-servicenow auth test              # same live round-trip, verbose form
progress-servicenow auth login             # refresh an expired session
progress-servicenow auth login --force     # discard the profile and sign in fresh
progress-servicenow auth logout
progress-servicenow auth profiles list
```

Every ticket and catalog command verifies that the page it read came from
`service-now.com` and is not a sign-in page. An expired session fails with a
non-zero exit and an explicit error — it never returns an empty result and never
reports sign-in page text as ticket data:

```
Error: Not authenticated: ServiceNow redirected to the SSO login page at
login.microsoftonline.com instead of returning ServiceNow data. The saved browser
session has expired. Refresh it with 'progress-servicenow auth login --force',
then retry.
```

## Usage

### Tickets

```bash
progress-servicenow ticket list --view open --table
progress-servicenow ticket get RITM0360937 --comments --table
progress-servicenow ticket get d224f82b4780c7d04dd5454a516d432a --table
progress-servicenow ticket comment RITM0360937 "Any update on this?"
progress-servicenow ticket close RITM0360937
progress-servicenow ticket create
progress-servicenow ticket create -T other_development_request \
  -F product=Sitefinity -F req_impact=Medium -F description="..." --dry-run
progress-servicenow ticket create -T other_development_request \
  -F product=Sitefinity -F req_impact=Medium -F description="..." --draft
```

### Ticket templates (offline — no auth required)

```bash
progress-servicenow ticket template list --table
progress-servicenow ticket template get other_development_request
progress-servicenow ticket template fields other_development_request --table
progress-servicenow ticket template refresh
```

### Product options and live form inspection

```bash
progress-servicenow ticket product list --table
progress-servicenow ticket product get Sitefinity
progress-servicenow ticket form inspect -T other_development_request --table
progress-servicenow ticket form lookup "Requested for" --search "Bertram"
```

### Catalog

```bash
progress-servicenow catalog list --table
progress-servicenow catalog get 838c9810dbe5db0408f33a1b7c961930
progress-servicenow catalog search "vpn" --table
```

### Cache

```bash
progress-servicenow --no-cache ticket list --view open --table
progress-servicenow cache clear
```

## Bytecode delivery

The original source for `client`, `parsers`, `config`, `main`, `browser`, `template_data`, `commands/*` and `models/*` was lost; those modules run from the preserved Python 3.14 bytecode in `progress_servicenow_cli/**/_bytecode_cache/*.pyc` (loaded by `_bytecode.py`). Those 17 files are tracked in git through narrow `.gitignore` exceptions, and `~/Dropbox/ai_harness_root/manifest.json` has a matching `include` for the adam-server replica, so a clone or `push.sh` always carries them. Do not delete them.
