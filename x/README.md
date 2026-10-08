# X CLI

## DESCRIPTION

The `x` CLI provides command-line access to X posts, post/media/audience analytics, API usage, Ads reporting, and X Developer Console workflows. Use it when agents or terminal automation need JSON-first analytics and tweet management or browser-session-backed API credit workflows.

## Installation

```bash
cd x
uv sync --dev
uv pip install -e .
```

## Authentication

Tweet commands use X API OAuth 1.0a credentials:

```bash
x auth profiles create api --auth-type custom
x auth login --profile api --credential-type custom
x auth profiles select api
```

Developer Console actions, including API credits, use a saved browser session:

```bash
x auth profiles create browser --auth-type browser_session
x auth login --profile browser --credential-type browser_session
x auth profiles select browser
```

## Credits

X API credits are purchased through the saved X Developer Console browser
session. After browser-session auth is complete, `x credits add` runs
headlessly against that CLI-owned profile, submits payment when `--yes` is
supplied, and returns purchase-success evidence from X.

If X has no default payment method, the command completes Stripe Embedded
Checkout using a configured LastPass credit-card item and billing fields:

```bash
export X_CREDIT_CARD_LASTPASS_ITEM_ID=LASTPASS_ITEM_ID
export X_BILLING_ADDRESS_LINE1="123 Example St"
export X_BILLING_CITY="Exampleville"
export X_BILLING_STATE="IN"
export X_BILLING_POSTAL_CODE="47725"
export X_BILLING_COUNTRY="US"
export X_BILLING_PHONE="8125550100"
```

```bash
# Preview without submitting payment
x credits add 25.00 --dry-run

# Purchase credits
x credits add 25.00 --profile browser --yes
```

After `x auth login --profile browser --credential-type browser_session`, the
saved CLI browser profile is the auth source of truth; do not switch to Codex's
in-app browser, Computer Use, or another visible browser to finish the same
workflow.

## Tweets

```bash
x tweet post "Hello from the X CLI"
x tweet list --limit 10
x tweet get TWEET_ID
x tweet delete TWEET_ID
```

## Cache

```bash
x cache --help
x cache clear
x cache clear --profile browser
```

Cache operations default to the active API profile. Use `--profile` to select a
specific browser or API profile. Auth status verifies each profile only through
its own authentication type.

## Analytics

The CLI previously returned only public engagement counts in `tweet get/list`.
`x analytics` now exposes the documented X API analytics and Ads reporting
operations. All commands return JSON by default and support `--table/-t` and
`--profile`. Reports preserve the complete API envelope (`data`, `includes`,
`meta`, and `errors`), including every metric X returns. Missing metrics stay
missing; they are never fabricated as zero. Partial errors retain successful
results on stdout and produce a nonzero exit status with a message on stderr.

### Post, media and audience metrics

```bash
x analytics posts 1234567890,1234567891
x analytics posts 1234567890 --metrics public_metrics,non_public_metrics,organic_metrics,promoted_metrics
x analytics media 13_1234567890 --metrics public_metrics,non_public_metrics
x analytics user
x analytics user --username example
x analytics user --user-id 1234567890 --auth-mode bearer
x analytics timeline --limit 100 --metrics public_metrics,organic_metrics
x analytics timeline --user-id 1234567890 --start-time 2026-10-01T00:00:00Z --end-time 2026-10-02T00:00:00Z --exclude replies,retweets
x analytics timeline --pagination-token TOKEN_FROM_META_NEXT_TOKEN
```

Post and media lookup accept up to 100 IDs per request. Post lookup includes
attached media and author public metrics. User metrics include follower,
following, post and list counts plus other fields returned by X. Timeline is
one page (5–100 posts); pass the returned `meta.next_token` to
`--pagination-token` for another page. No automatic bulk fetching or extra
usage is hidden behind these commands.

Default authentication is existing OAuth 1.0a user credentials. Public reads
also support `--auth-mode bearer` with the app bearer token. Non-public,
organic and promoted metrics require user credentials, owned content and
posts created within 30 days. Promoted metrics additionally require promoted
content. Video view totals can cover every post using that media, not only
the selected post. User metrics are current snapshots; the CLI does not
invent historical follower growth or account-wide dashboard totals.

### Post and media time series

```bash
x analytics post-series 1234567890 --start-time 2026-10-01T00:00:00Z --end-time 2026-10-02T00:00:00Z --granularity hourly
x analytics post-series 1234567890 --start-time 2026-10-01T00:00:00Z --end-time 2026-10-02T00:00:00Z --fields id,impressions,engagements,url_clicks,timestamped_metrics
x analytics media-series 13_1234567890 --start-time 2026-10-01T00:00:00Z --end-time 2026-10-02T00:00:00Z --granularity daily
```

Dedicated post analytics supports hourly, daily, weekly or total aggregation;
media analytics supports hourly, daily or total. The default requests all
supported fields, including engagement/click breakdowns for posts and watch
time, playback quartiles, views and CTA clicks for media. These endpoints
appear in X's Enterprise documentation and require account access plus user
authentication. A CLI command does not grant API entitlement. X authorization,
plan and credit errors are returned explicitly without downgrading metrics.
The documentation index mentions 28-hour and historical insights, but their
operations are absent from the verified OpenAPI contract, so this CLI does
not invent URLs for them.

### Search counts and API usage

```bash
x analytics counts 'from:example' --granularity day
x analytics counts 'from:example' --archive --start-time 2026-09-01T00:00:00Z --end-time 2026-10-01T00:00:00Z --granularity day
x analytics counts 'from:example' --next-token TOKEN_FROM_META_NEXT_TOKEN
x analytics usage --days 30
x analytics credits
```

Counts support minute/hour/day buckets, recent seven-day or full-archive
access, and `--since-id`/`--until-id`. Counts return one page and preserve its
continuation token. Usage returns 1–90 days of project/app post consumption;
credits reads credit usage and never purchases credits. These commands use
`X_BEARER_TOKEN`, an app-only bearer token, rather than OAuth 1.0a. Save reusable
tokens through the CLI-tools secret manager (never in a repository `.env`);
normal post analytics continues to use the existing OAuth 1.0a setup.

Save an app bearer token through piped stdin. The command refuses interactive
input and requires `--stdin`. It stores the token in the CLI-tools secret manager and binds it to the selected
API profile; no secret is written to a repository `.env` or emitted in output.
A bearer-only API profile supports public reads, counts and usage. Auth status
verifies bearer-only profiles with a live credit-usage request. Posting and
private analytics still require OAuth 1.0a user credentials.

```bash
# Read without echoing the token, then pass it through stdin:
printf 'X app bearer token: '
IFS= read -r -s X_APP_BEARER_TOKEN
printf '\n'
printf '%s' "$X_APP_BEARER_TOKEN" | x auth bearer-token --profile api --stdin
unset X_APP_BEARER_TOKEN
# Or pipe an existing secret-manager value directly without printing it:
/Users/adam/Dropbox/GitRepos/cli-tools/_repo/_secret-manager/secrets.sh get x-bearer-token | x auth bearer-token --profile api --stdin
x analytics usage --profile api --days 30
```

### X Ads analytics

```bash
x analytics ads-accounts --limit 100
x analytics ads-accounts --cursor NEXT_CURSOR
x analytics ads-active ACCOUNT_ID --entity LINE_ITEM --start-time 2026-10-01T00:00:00Z --end-time 2026-10-02T00:00:00Z
x analytics ads-stats ACCOUNT_ID ENTITY_ID --entity CAMPAIGN --start-time 2026-10-01T00:00:00Z --end-time 2026-10-02T00:00:00Z --metric-groups ENGAGEMENT,BILLING,VIDEO
x analytics ads-job-create ACCOUNT_ID ENTITY_ID --entity LINE_ITEM --start-time 2026-09-01T00:00:00Z --end-time 2026-10-01T00:00:00Z --segmentation AGE
x analytics ads-jobs ACCOUNT_ID JOB_ID
x analytics ads-download ACCOUNT_ID JOB_ID
x analytics ads-reach ACCOUNT_ID CAMPAIGN_ID --start-time 2026-10-01T00:00:00Z --end-time 2026-10-02T00:00:00Z
x analytics ads-reach ACCOUNT_ID FUNDING_INSTRUMENT_ID --funding-instruments --start-time 2026-10-01T00:00:00Z --end-time 2026-10-02T00:00:00Z
```

Ads commands require an approved Ads API application and an accessible Ads
account using OAuth 1.0a. `ads-accounts` discovers account IDs and timezones,
with `--query` name-prefix search, `--account-ids`, `--with-deleted` and
`--cursor` pagination. Reports support ACCOUNT, CAMPAIGN,
FUNDING_INSTRUMENT, LINE_ITEM, PROMOTED_ACCOUNT and PROMOTED_TWEET entities,
up to 20 IDs, HOUR/DAY/TOTAL granularity, and ALL_ON_TWITTER/SPOTLIGHT/TREND
placements. Six metric groups expose engagement, billing, video, web/mobile
conversions and lifetime mobile conversion value. Request MOBILE_CONVERSION
separately. Availability depends on entity type and campaign objective.

Synchronous reports allow seven days; asynchronous reports allow 90 days, or
45 days with segmentation. Current segmentation options are AGE, GENDER,
METROS, REGIONS, PLATFORMS and CONVERSION_TAGS. METROS/REGIONS need a
`--country` targeting ID. CONVERSION_TAGS requires WEB_CONVERSION alone.
All Ads times must contain a timezone and whole hours. DAY boundaries must
match midnight in the Ads account's timezone; the API validates that timezone.
End times are exclusive. Spend is returned in local-currency micros.

`ads-job-create` creates only a reporting job; it does not create or purchase
ads and never retries POST automatically. Check jobs with `ads-jobs` (up to
200 job IDs), then `ads-download` checks SUCCESS, downloads from the documented
X CDN without API credentials, decompresses gzip and emits JSON. Processing
jobs fail explicitly until ready. `ads-active` supports mutually exclusive
`--campaign-ids`, `--funding-instrument-ids` or `--line-item-ids` scopes (200 IDs).
Server-directed waits over the client's retry budget fail with a retry-after
message instead of retrying before X permits it.

Official contracts verified October 7, 2026:
[OpenAPI](https://docs.x.com/openapi.json),
[metrics](https://docs.x.com/x-api/fundamentals/metrics),
[post analytics](https://docs.x.com/x-api/posts/get-post-analytics),
[media analytics](https://docs.x.com/x-api/media/get-media-analytics),
[Ads analytics](https://docs.x.com/x-ads-api/analytics).
