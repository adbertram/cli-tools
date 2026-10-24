# google-ads CLI

## DESCRIPTION

Full versioned Google Ads API access through every service and RPC exposed by the pinned official Python SDK. Use this CLI to discover complete request schemas, run GAQL reports, manage account resources and uploads, and inspect long-running operations with strict protobuf JSON validation and explicit mutation controls.

## API coverage

SDK 33.0.0 targets wire API v25, including the v25.2 schema released with that SDK. The measured manifest includes 110 Google Ads services, 170 Google Ads RPCs, and four official long-running Operations RPCs (111 services, 174 RPCs total). Full support means every method is reachable for this pinned schema; account access and Cloud project approval still govern live use. Live endpoint testing requires Ads-scoped OAuth credentials.

## Installation

Run the repository installer:

```bash
_repo/skills/cli-tool/scripts/install-cli-tool.sh google-ads
```

## Authentication

Enable Google Ads API and apply for API access in the Google Cloud project that owns your OAuth client. Google Ads permission and `https://www.googleapis.com/auth/adwords` scope are required. Developer tokens were sunset September 9, 2026; SDK 32.0.0 removed their mandatory validation. This CLI does not require or send a developer token.

OAuth login uses the shared CLI-tools handler. Enter app credentials when prompted; the CLI stores reusable secrets in its secret manager and owns token state in the selected runtime profile. Never put reusable credentials into `.env` files. Use an OAuth client whose registered redirect URI matches the URI supplied during login (default `http://localhost`). The browser authorization grants offline access. Paste the final redirect URL or authorization code back into the terminal.

Existing app credentials can be copied by explicit secret-manager names. This imports only the app ID and secret, clears any prior Ads tokens, and requires fresh Ads consent. It never imports another CLI's access or refresh token.

```bash
google-ads auth client import --client-id-secret google-client-id --client-secret-secret google-client-secret --profile default
google-ads auth login --profile default
google-ads auth login --profile default --force
google-ads auth status
google-ads auth test
google-ads auth refresh
google-ads auth logout --force
```

`auth status` validates credentials by calling `CustomerService.list_accessible_customers`. Its JSON reports the shared per-profile and per-credential-type status. `--force` preserves static app credentials while replacing OAuth token state.

Profiles are provided by the shared auth app:

```bash
google-ads auth profiles list
google-ads auth profiles get default
google-ads auth profiles create work
google-ads auth profiles select work
google-ads auth profiles delete work --force
google-ads auth profiles remove work --force
google-ads auth profiles rename work business
google-ads cache clear
```

## Complete API discovery

These commands need no credentials. Service names and RPC names come from the installed official SDK. Python RPC names use snake_case. Minor API releases share the major-version namespace, so v25.2 uses `--api-version v25`, not `v25_2`.

```bash
google-ads api versions
google-ads api services
google-ads api methods CampaignService
google-ads api schema CampaignService mutate_campaigns
google-ads api coverage
```

`api schema` prints complete request/response protobuf definitions, nested message references, JSON field names, enum values, repeated fields and oneofs. `api coverage` exports the measured method manifest. Version selection supports the pinned SDK's v23, v24 and v25 schemas; v25 is the fixed default. Older server versions can sunset independently.

## Calling any RPC

`api call SERVICE METHOD` reaches every cataloged method. Supply a protobuf JSON object through `--body`, `--body-file FILE`, or `--body-file -` for stdin. Field names may use protobuf snake_case or JSON camelCase. Unknown fields, invalid enum values and conflicting oneofs fail before network access. Bytes use base64; int64 output follows protobuf JSON string encoding. Bare `NaN` and `Infinity` are invalid input JSON; supported protobuf special floating-point values must be quoted strings.

```bash
google-ads api call CustomerService list_accessible_customers --body '{}'
google-ads api call GoogleAdsFieldService search_google_ads_fields --body '{"query":"SELECT name,category,data_type WHERE name LIKE '\''campaign.%'\''"}' --all-pages
google-ads api call ConversionUploadService upload_click_conversions --body-file conversions.json --validate-only
google-ads api call BatchJobService add_batch_job_operations --body-file operations.json --dry-run
google-ads api call CampaignService mutate_campaigns --body-file campaign.json --yes
cat request.json | google-ads api call CampaignService mutate_campaigns --body-file - --dry-run
```

Read-only methods (`get_*`, `list_*`, `search*`) run without mutation confirmation. All other methods, including planning/generation methods whose side effects are not classified, require `--yes`, valid server `validate_only`, or `--dry-run`. `--dry-run` parses and prints a request without credentials or network access. `--validate-only` works only where the official request schema has `validate_only`; other methods fail explicitly. This CLI has no automatic ad launch or spend workflow.

`--timeout` sets the timeout in seconds per RPC attempt (default 60). Retry uses bounded exponential backoff with jitter for read/validation calls on server failures or rate limits, with a 120-second retry budget. Mutating calls disable SDK retries to avoid replaying changes. Google Ads failures retain request IDs and complete structured failure payloads. Partial-failure responses retain the complete response in the error and exit nonzero rather than hiding rejected operations.

## Paging, streaming and long-running operations

A paginated call returns one complete response envelope, including any next-page token. `--all-pages` returns `{"pages":[...]}`, preserving every page's full metadata. Repeated pagination tokens fail before another page request. Server-streaming RPCs print one full response batch per JSONL line and consume batches lazily. Unset/default protobuf fields follow official protobuf JSON serialization; populated API fields are not dropped.

```bash
google-ads api call GoogleAdsService search --body-file query.json --all-pages
google-ads api call GoogleAdsService search_stream --body-file query.json
google-ads api call BatchJobService run_batch_job --body '{"resource_name":"customers/123/batchJobs/456"}' --yes
google-ads api call OperationsService get_operation --body '{"name":"customers/123/operations/456"}'
google-ads api call OperationsService list_operations --body '{"name":"customers/123","filter":"done=false","page_size":100}' --all-pages
google-ads api call OperationsService cancel_operation --body '{"name":"customers/123/operations/456"}' --yes
google-ads api call OperationsService delete_operation --body '{"name":"customers/123/operations/456"}' --yes
```

Long-running RPCs return the full operation envelope immediately. Poll through `OperationsService.get_operation`. Operations methods use the pinned SDK's official operations transport; servers may return `UNIMPLEMENTED` for methods they don't support. Operation `Any` payloads remain in the complete protobuf JSON response. No automatic blocking wait or mutation retry is added.

## GAQL reporting

GAQL covers all supported resources, metrics, segments and fields. Put filtering and bounds in GAQL `WHERE` and `LIMIT`; the CLI passes the query unchanged. Use `customer_client` to inspect a manager account's descendants. Set `--customer-id` explicitly or configure non-secret `CUSTOMER_ID` through CLI-tools runtime configuration. `LOGIN_CUSTOMER_ID` and `LINKED_CUSTOMER_ID` are optional non-secret SDK selectors.

```bash
google-ads query search 'SELECT campaign.id, campaign.name, campaign.status FROM campaign WHERE campaign.status = PAUSED LIMIT 100' --customer-id 1234567890
google-ads query search 'SELECT campaign.id, metrics.clicks, metrics.cost_micros FROM campaign WHERE segments.date DURING LAST_30_DAYS' --customer-id 1234567890 --all-pages
google-ads query search 'SELECT customer_client.id, customer_client.descriptive_name FROM customer_client' --customer-id 1234567890 --stream
google-ads query search 'SELECT campaign.id FROM campaign' --customer-id 1234567890 --page-token TOKEN
```

`--stream` cannot be combined with `--all-pages` or `--page-token`.

## Accessible customers

```bash
google-ads customers list --limit 100
google-ads customers list --filter 'resource_name:like:%123%' --properties resource_name --table
google-ads customers get 1234567890
google-ads customers get customers/1234567890 --table
```

The accessible-customer API exposes no filter or limit parameters. These options apply locally after account discovery, as documented in command help. `customers get` queries account identity, status, currency, timezone, manager and test flags; generic GAQL/API commands expose additional fields.

## Output and verification

Stdout carries JSON, JSONL, tables or help; diagnostics go to stderr. Default API output preserves complete populated response data. Only explicit `--properties` on customer discovery reduces fields. Exit codes: 0 success, 1 API/validation failure, 2 credential failure.

```bash
google-ads --version
google-ads --help
uv run --project google-ads python -m pytest google-ads/tests
_repo/skills/cli-tool/scripts/validate-cli-tool.sh google-ads
_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name google-ads
```

## Sources

- [Official SDK releases](https://github.com/googleads/google-ads-python/releases)
- [Official client library and version documentation](https://developers.google.com/google-ads/api/docs/client-libs)
- [Developer token sunset and Cloud project migration](https://developers.google.com/google-ads/api/docs/api-policy/developer-token)
- [Google Ads Query Language](https://developers.google.com/google-ads/api/docs/query/overview)
- [Python OAuth authentication](https://developers.google.com/google-ads/api/docs/client-libs/python/oauth-installed)
