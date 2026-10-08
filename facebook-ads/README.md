# Facebook Ads wrapper for the official Meta Ads CLI

## DESCRIPTION

A thin wrapper for Meta's official Ads CLI, installed privately with a pinned upstream release. Use it to run every upstream advertising and commerce command while preserving native arguments, output, stdin, prompts and exit status.

## Installation

```bash
_repo/skills/cli-tool/scripts/install-cli-tool.sh facebook-ads
facebook-ads --version
facebook-ads --help
facebook-ads run -- --version
facebook-ads run -- --help
```

The wrapper pins official PyPI package `meta-ads==1.2.0`, published by Meta's `facebook` maintainer. Its upstream executable is `meta` (entrypoint `meta.cli:cli`). Python 3.12 or later and an upstream wheel for the host platform are required. The canonical installer provisions Meta's package inside the wrapper's isolated environment; no separate global `meta` installation is required. The wrapper resolves that private executable, so unrelated `meta` commands on PATH cannot intercept it.

Wrapper version is 0.2.0; `run -- --version` reports upstream version. Every native invocation uses `facebook-ads run -- <native arguments>`. The separator protects native flags from wrapper parsing. Root `--help` explains the wrapper; `run -- --help` displays the full official command tree. The wrapper does not add flags, output conversions, API fallbacks, credential profiles, caching, retries or ad-spend behavior.

## Authentication and account selection

The official upstream CLI accepts a Meta system-user access token through the `ACCESS_TOKEN` process environment, an ad account through `AD_ACCOUNT_ID` or native `--ad-account-id`, and optional `BUSINESS_ID` or `--business-id`. The token needs appropriate Marketing API scopes and access to the intended assets.

Upstream exposes `auth status` only. It has no `auth login`, OAuth flow, browser login, or wrapper profile commands. Without a token, native status exits 3 and prints `Not authenticated. Set the ACCESS_TOKEN environment variable.` to stderr. Status checks whether a token is configured; successful status alone does not establish real account permissions.

Store a reusable token in the CLI-tools secret manager by piping hidden terminal input into its supported stdin interface. Then retrieve it directly into the upstream process environment without printing it or putting the raw value in shell history:

```bash
python3 -c 'import getpass,sys; sys.stdout.write(getpass.getpass("Meta system-user access token: "))' | \
  _repo/_secret-manager/secrets.sh set --tool facebook-ads --type personal-access-token
ACCESS_TOKEN="$(_repo/_secret-manager/secrets.sh get facebook-ads-personal-access-token)" \
  facebook-ads run -- auth status
ACCESS_TOKEN="$(_repo/_secret-manager/secrets.sh get facebook-ads-personal-access-token)" \
  facebook-ads run -- --output json ads adaccount list --limit 1
ACCESS_TOKEN="$(_repo/_secret-manager/secrets.sh get facebook-ads-personal-access-token)" \
  facebook-ads run -- --output json ads --ad-account-id act_123 campaign list --limit 10
```

Use the exact existing secret name if a token is already stored under another name. Never place reusable credentials in `.env`, docs, command arguments, screenshots, or logs. The wrapper never reads, modifies or deletes prior `facebook-ads` authentication profiles or secret-manager items. Facebook website passwords/browser sessions do not grant Marketing API access.

## Complete upstream command passthrough

Upstream release 1.2.0 contains 55 leaf commands across `ads` and `auth`, including 14 advertising/commerce resource groups. Every command and option passes through; the wrapper keeps no command whitelist. The scope is the official CLI's shipped capabilities, not universal Graph/Marketing API coverage. The previous custom SDK/Graph gateway and its command syntax have been replaced.

```bash
facebook-ads run -- ads --help
facebook-ads run -- ads adaccount list --help
facebook-ads run -- ads campaign create --help
facebook-ads run -- ads adset get --help
facebook-ads run -- ads creative create --help
facebook-ads run -- ads catalog --help
facebook-ads run -- ads dataset --help
facebook-ads run -- ads product-set --help
facebook-ads run -- ads product-item --help
facebook-ads run -- ads product-feed --help
facebook-ads run -- ads insights get --help
facebook-ads run -- ads guidance list --help
facebook-ads run -- ads study list --help
facebook-ads run -- auth status
```

The service skill's `usage.json` describes the wrapper itself. Native command help provides the complete upstream command and option reference, including option placement and behavior.

Global native output is `--output table|json|plain` (`-o`), with table as its native default. To get JSON, place the global output option before `ads`:

```bash
facebook-ads run -- --output json ads --ad-account-id act_123 campaign list --limit 10
facebook-ads run -- --output json ads --ad-account-id act_123 adset get 123 --fields name,targeting,promoted_object
facebook-ads run -- --output json ads --ad-account-id act_123 insights get --date-preset last_7d
facebook-ads run -- --no-color --no-input ads --ad-account-id act_123 campaign list
```

These read-only commands require `ACCESS_TOKEN` in their environment. Native `--no-input` disables prompts. Native commands may accept flags different from the retired custom client (for example `--execution-options validate_only` for campaign validation). Discover them from native help; the wrapper does not invent `--dry-run`, `--yes`, `--profile`, or unsupported filter/property flags. Advertising mutations remain upstream operations and require explicit user authorization; they are never run as a test.

## Streams, exit codes and interactive input

The wrapper replaces its process with the private native executable. Standard input, terminal access, stdout, stderr, binary data, large streamed output, native prompts, signals and native exit codes remain unchanged. It uses no shell and performs no output parsing. Upstream errors remain upstream errors; missing private installation exits 127, an executable failure exits 126, and both instruct reinstallation. It does not open a browser or authenticate automatically.

## Validation

```bash
uv run --project facebook-ads --with pytest python -m pytest facebook-ads/tests
_repo/skills/cli-tool/scripts/validate-cli-tool.sh facebook-ads
_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name facebook-ads
_repo/skills/cli-tool/scripts/regenerate-usage-json facebook-ads --check
```

Tests compare every native leaf's complete help and root/error/auth-status output through the wrapper. Synthetic executable tests cover unchanged arguments, binary/large stdin and stdout, stderr, native nonzero status and signal termination. These are passthrough tests, not authenticated account or advertising-operation tests. Live account verification remains dependent on a system-user token and asset access.

## Official sources

[Meta Ads CLI overview](https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-cli/ads-cli-overview), [official package and Meta publisher metadata](https://pypi.org/project/meta-ads/), [pinned release](https://pypi.org/project/meta-ads/1.2.0/).
