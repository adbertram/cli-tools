# Facebook Ads CLI

## DESCRIPTION

Meta Marketing API CLI with full dispatch of generated resource operations in the official pinned Business SDK. Use it for versioned Graph API requests, multipart uploads, batching, pagination and asynchronous insights.

## Install

```bash
_repo/skills/cli-tool/scripts/install-cli-tool.sh facebook-ads
facebook-ads --version
facebook-ads --help
```

## Authentication

Create a Meta developer app with the Marketing API product. Generate a user or system-user access token with `ads_read` for reporting, `ads_management` for advertising mutations, and access to the intended ad account/assets. Other SDK resources need their own permissions and access levels. Facebook website credentials or a browser login do not grant Marketing API access.

```bash
facebook-ads auth login
facebook-ads auth login --force --profile default
facebook-ads auth status --profile default
facebook-ads auth test --profile default
facebook-ads auth logout --profile default
facebook-ads auth profiles list --properties name,active,auth_type
facebook-ads auth profiles create reporting
facebook-ads auth profiles select reporting
facebook-ads auth profiles delete reporting
facebook-ads app-secret --profile default
```

`auth login` prompts without echoing the token and stores reusable credentials in the CLI-tools secret manager; profile state contains a secret reference. `app-secret` optionally saves the app secret through the same store, enabling appsecret_proof for server API calls. Never place reusable credentials in `.env`, examples, shell command arguments, or source. PAT credentials do not support OAuth refresh; renew/revoke them in Meta and rerun `auth login`. Named profiles remain isolated. All network commands accept `--profile`.

## Full API coverage and discovery

Coverage means every generated `FacebookRequest` method shipped in the pinned SDK is discoverable and dispatchable: 1105 Graph resource/schema classes, including 362 callable resource classes and 1503 generated API operations. The manifest is derived directly from installed SDK source, not a manually selected endpoint list. `sdk schema` includes resource field types, all operations, operation parameter types and enum values. Every manifest operation has an offline pending-request construction test.

This is SDK dispatch coverage, not a claim that every Meta API endpoint has been exercised live. Generated `adobjects` covers Marketing API and other Business SDK Graph resources. Generic inherited CRUD helpers, unmodeled Graph endpoints, Conversions API event payloads and custom upload protocols use `graph request`; they are not misrepresented as generated method coverage. Account permissions, access review, field restrictions, deprecations and server-side availability still apply. SDK wrapper helpers outside generated Graph operations are excluded from the catalog.

```bash
facebook-ads sdk coverage
facebook-ads sdk resources list --limit 10000
facebook-ads sdk resources list --filter 'name:contains:Audience' --table
facebook-ads sdk methods list AdAccount --limit 1000 --properties name,method,endpoint
facebook-ads sdk resources get AdAccount
facebook-ads sdk methods get AdAccount get_campaigns
facebook-ads sdk schema AdAccount
facebook-ads sdk schema AdAccount --method get_insights
facebook-ads sdk call AdAccount get_campaigns act_123 --fields id,name,status --all-pages --limit 1000
facebook-ads sdk call Campaign api_update 123 --params '{"status":"PAUSED"}' --dry-run
facebook-ads sdk call AdAccount create_custom_audience act_123 --params @audience.json --yes
facebook-ads sdk call AdAccount create_ad_image act_123 --file filename=creative.jpg --yes
```

`--params` accepts a complete JSON object, `@file`, or `-` to read stdin. `--file FIELD=path` repeats for multiple files. Dispatch uses official SDK type/enum validation. `--all-pages` follows GET cursor pages until `--limit` (default 100); without it, return the first API page up to that limit. Response fields remain complete unless `--properties` selects output fields. The API itself controls fields returned by default; `--fields` requests desired fields explicitly.

## Common resources

`accounts` has `list` and `get`. `campaigns`, `adsets`, `ads`, and `creatives` each have `list`, `get`, `create`, `update`, and `delete`. Create takes the parent ad account ID; update/delete take the resource ID. All mutation parameters pass directly to the API without a narrow hand-maintained schema. Use SDK discovery for validation and operation details.

```bash
facebook-ads accounts list --parent me --limit 1 --fields id,name --table
facebook-ads accounts get act_123 --fields id,name,currency
facebook-ads campaigns list --parent act_123 --filter 'effective_status:in:ACTIVE|PAUSED' --limit 200 --properties id,name
facebook-ads campaigns get 123 --fields id,name,status --table
facebook-ads campaigns create act_123 --params @campaign.json --dry-run
facebook-ads campaigns update 123 --params '{"status":"PAUSED"}' --yes
facebook-ads campaigns delete 123 --dry-run
facebook-ads adsets list --parent act_123 --limit 1
facebook-ads adsets get 123
facebook-ads adsets create act_123 --params @adset.json --dry-run
facebook-ads adsets update 123 --params '{"status":"PAUSED"}' --dry-run
facebook-ads adsets delete 123 --dry-run
facebook-ads ads list --parent act_123 --limit 1
facebook-ads ads get 123
facebook-ads ads create act_123 --params @ad.json --dry-run
facebook-ads ads update 123 --params '{"status":"PAUSED"}' --dry-run
facebook-ads ads delete 123 --dry-run
facebook-ads creatives list --parent act_123 --limit 1
facebook-ads creatives get 123
facebook-ads creatives create act_123 --params @creative.json --dry-run
facebook-ads creatives update 123 --params '{"name":"Revised"}' --dry-run
facebook-ads creatives delete 123 --dry-run
```

Lists support `--table/-t`, `--limit/-l`, `--filter/-f`, `--properties/-p`, `--fields`, `--params`, and `--profile`. Limits are sent to the API with cursor paging; list stdout is a bare array. Get stdout is the resource object and supports `--table/-t`, `--properties/-p`, `--fields`, and `--profile`. Property selection uses shared nested dot notation. Native filtering translates `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `nin`, and `contains`. API filtering support varies by edge/field; unsupported CLI operators fail explicitly, while server filter errors are preserved. Use `--params` for native `filtering` details. Local SDK discovery filters run locally.

## Graph requests, upload and batch

```bash
facebook-ads graph request GET me --params '{"fields":"id,name"}'
facebook-ads graph request GET act_123/campaigns --params '{"fields":"id,name","limit":10}'
facebook-ads graph request POST act_123/adimages --file filename=creative.jpg --yes
facebook-ads graph request POST act_123/advideos --video-host --params '{"upload_phase":"start","file_size":"12345"}' --yes
facebook-ads graph request POST act_123/campaigns --params @campaign.json --dry-run
facebook-ads graph request DELETE 123 --dry-run
facebook-ads graph batch '[{"method":"GET","relative_url":"me?fields=id"}]'
facebook-ads graph batch @batch.json --file image1=creative.jpg --yes
```

Graph requests support all JSON parameters and GET/POST/DELETE/PUT/PATCH, restricted to relative paths on `https://graph.facebook.com` or the official video upload host selected with `--video-host`. Multipart files support image/video upload and batch attachment protocols. For resumable video upload, issue the official start/transfer/finish calls with their returned session IDs and chunk files through the same Graph command; it does not invent protocol defaults. Generic Graph output retains response envelopes and cursors; sensitive token fields and auth values in paging URLs are redacted. Redirects are refused to prevent credential forwarding.

Batch input is the complete official operation array (up to 50), including dependency names, attached_files and omit_response_on_success options. Batch output preserves each HTTP code, headers and parsed body; any individual HTTP/API failure exits 1 after printing the full array. Mutating batch entries require `--yes` or `--dry-run`. Read-only batches can execute without mutation confirmation.

## Insights and asynchronous reports

```bash
facebook-ads insights list act_123 --fields campaign_name,spend,impressions --params '{"date_preset":"last_7d","level":"campaign"}' --limit 1000
facebook-ads insights start act_123 --params @insights.json
facebook-ads insights status 123
facebook-ads insights get 123
facebook-ads insights wait 123 --timeout 600 --interval 5
facebook-ads insights results 123 --limit 1000
```

Async start creates a reporting job only; it does not create or activate ads. Status exposes `async_status`/completion, wait detects failures and bounded timeout, results uses cursor paging. The report ID remains usable after wait timeout. All insights parameters, metrics, breakdowns, attribution settings, filtering, and time ranges can pass through `--params`; discover them with `sdk schema AdAccount --method get_insights`.

## Cache and output

```bash
facebook-ads cache clear
```

The shared cache clear command removes any stored cache data; requests are not cached by this CLI. JSON data goes to stdout, messages/errors to stderr. Mutating calls require `--yes` or `--dry-run`; dry runs need no access token and make no HTTP request. Top-level `method` or `_method` parameters (including batch URL/body parameters) are conservatively treated as potentially mutating: they require `--yes` or `--dry-run`, and GET calls carrying them are not retried automatically. Actual Meta support for these override parameters is not asserted; the CLI preserves their availability with explicit confirmation. Nested business fields do not trigger this classification. Nonfinite JSON numbers, timeout/interval values, and retry settings fail before network requests. Network timeouts default to 60 seconds. GET retry uses exponential delay with jitter and Retry-After, configurable through non-secret `MAX_RETRIES`, `BASE_DELAY`, `MAX_DELAY`, `RETRY_JITTER`; mutations and batch POST are never retried automatically, avoiding duplicate effects. `HTTP_TIMEOUT` and `API_VERSION` are non-secret root configuration values. Changing API version does not change the pinned SDK schema; use generic Graph requests for new version-specific fields/operations and update the SDK pin deliberately.

## Validation

```bash
uv run --project facebook-ads --with pytest python -m pytest facebook-ads/tests
_repo/skills/cli-tool/scripts/validate-cli-tool.sh facebook-ads
_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name facebook-ads
```

Mocked transport, schema construction, and safeguards do not prove real account permissions. Live verification requires a token and an explicit read-only account smoke. Validation never launches ads or spends money.

## Official sources

[Meta Business SDK source](https://github.com/facebook/facebook-python-business-sdk), [pinned package](https://pypi.org/project/facebook-business/26.0.2/), [Marketing API documentation](https://developers.facebook.com/docs/marketing-api/), [Graph batch documentation](https://developers.facebook.com/docs/graph-api/making-multiple-requests/).
