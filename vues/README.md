# vues

Vues (operated by evrgreen) clipping-campaign CLI. Clippers post short-form
clips for brand campaigns and earn a CPM per 1,000 tracked views. This CLI gives
the Trawler clipping system everything it needs to treat Vues as a campaign
provider, mirroring the `clipster` CLI's command surface and JSON shapes.

## DESCRIPTION

Use this CLI to work with Vues campaigns, linked social accounts, submissions
and earnings on the Vues (evrgreen) creator clipping platform. Authenticated
reads and writes run over HTTP against the Vues API using a Supabase session
captured once at browser sign-in. stdout is always JSON unless `--table` is
passed.

## Authentication

Vues signs in only with **Google or Apple** (Supabase). There is no email /
password or API key. `vues auth login` uses the standard cli-tools browser
sign-in: it opens the shared Chrome profile at <https://vues.app/login>, you sign
in (click **Continue with Google** and pick your account, or nothing at all when
the shared profile is already signed in to Vues), then press **Enter** in the
terminal. The CLI reads the Supabase session from the vues.app
`sb-ycfkjzqusvyzbrisjziy-auth-token` cookie and saves it as runtime auth state.

```text
$ vues auth login
Opening browser for login...
Opening browser for login at: https://vues.app/login
Log in, then press Enter here to save the session and close the browser.
✓ Authentication complete.
✓ Browser session authenticated
```

After that every command, including `auth status` and `auth test`, runs over
plain HTTP and renews the 15-minute access token with the saved refresh token.
No browser opens again, so these commands never wait on the shared Chrome
profile, until the refresh token itself stops working and `auth status` reports
`authenticated: false`.

First time only: you need a Vues creator account. Sign up free at
<https://vues.app/login> with Google or Apple and link your TikTok account
(Trawler uses `@ata_clipper`) under **Accounts** in the Vues app. If the login
browser ends without a Vues account, `vues auth login` says so and points here.

No reusable credential is ever stored in a `.env` file. The Supabase tokens are
runtime auth state under
`~/.local/share/cli-tools/vues/authentication_profiles/<profile>/`.

```bash
vues auth login              # browser sign-in (Google/Apple), then press Enter
vues auth login --force      # -F: clear the saved session and sign in again
vues auth status             # JSON: per-profile auth state (live HTTP check)
vues auth test               # live identity check over HTTP
vues auth logout             # clear the saved session
```

## Commands

### account

```bash
vues account get                         # signed-in creator identity and balance (/users/me)
vues account get --table                 # field/value table
vues account get --properties id,email   # only these fields
```

### organizations

A clipper only sees campaigns from organizations they belong to (plus public
campaigns). `list` shows discoverable orgs with `is_member`; `--member` lists
only joined ones (`/clipper/orgs`); `applications` shows applications and their
`status` (`pending`, `approved`, `denied`). `join` takes the org `id` or
`short_id` and sends the web app's own request,
`POST /api/v1/organizations/{id}/apply` with body `{"message": null}` (or the
`--message` text). Membership and existing applications are checked first, so
it never applies twice. Result `status`:

- `joined`: auto-approve org, now a member (the response carries the approved application)
- `applied`: manual-approval org, application is pending
- `existing`: already a member (`reason: member`) or already applied (`reason: application`, including denied); nothing is sent
- `dry_run`: only with `--dry-run`, shows the request

`--yes` is required to send. For a manual-approval org it also affirms the
Terms of Service and the org's rules, as the web form's required checkbox does.

```bash
vues organizations list                  # discoverable orgs: id, short_id, name, description, auto_approve_applications, is_member
vues organizations list --member         # only joined orgs
vues organizations get SHORT_ID          # one org (id or short_id)
vues organizations list --filter auto_approve_applications:eq:true --table
vues organizations list --limit 5 --properties short_id,name
vues organizations applications          # applications and status
vues organizations join SHORT_ID --dry-run
vues organizations join SHORT_ID --yes
vues organizations join SHORT_ID --yes --message "Short intro"   # manual-approval orgs
```

### campaigns

These are the clipper campaigns the signed-in creator can see
(`/api/v1/clipper/campaigns`). Every campaign command accepts the campaign `id`
or its `short_id` and returns the campaign object exactly as the API provides it.

```bash
vues campaigns list                      # campaigns the creator can see (JSON)
vues campaigns list --limit 20           # -l: cap the number returned
vues campaigns list --table              # -t: table view
vues campaigns list --filter type:eq:CLIPPING   # -f: field:op:value (local)
vues campaigns list --properties id,name        # -p: only these fields
vues campaigns get CAMPAIGN_ID           # one campaign in full (cpm, max/min payout, budget, platforms, brief)
vues campaigns get CAMPAIGN_ID --table
vues campaigns applications CAMPAIGN_ID     # read back the applications gating the campaign (JSON)
vues campaigns applications CAMPAIGN_ID --table
vues campaigns join CAMPAIGN_ID --dry-run   # show what joining would send, sending nothing
vues campaigns join CAMPAIGN_ID --yes       # reach the campaign (applies to its organization when gated)
```

Vues has no per-campaign application. A campaign is reachable when it is public
or its organization has admitted the creator; otherwise it is gated behind its
organization, and the web app's "Join" applies to that organization. The
backend has no `/clipper/campaigns/{id}/apply` or `/clipper/campaigns/{id}/application`
route (both answer the router's own 404 for every method, verified 2026-10-20).
Both commands start from `GET /clipper/campaigns/{id}/teaser`, whose `outcome` is
`member` (reachable), `teaser` (gated) or `not_available`.

`campaigns applications` returns `{campaign_id, teaser, applications}`:
`teaser` is the teaser object verbatim and `applications` holds the creator's
`/clipper/applications` rows for the campaign's organization (matched on the
campaign's `organization_id` when reachable, on the teaser's
`organization.short_id` when gated), each with `id`, `status`
(`pending`/`approved`/`denied`), `message`, `created_at`, `reviewed_at` and
`organization`. No application is an empty list with exit 0; a campaign that is
`not_available`, unknown, or whose organization cannot be identified exits 1
with the reason on stderr, so a failed read is never mistaken for "none".

`campaigns join` never sends twice: `member` returns `status: existing,
reason: member` and sends nothing; a gated campaign runs `organizations join`
for its organization and returns that result (`joined`, `applied`, `existing`
or `dry_run`) plus `campaign_id` and `teaser`. `--yes` on a manual-approval
organization also affirms the Terms of Service and that organization's rules.

### social-accounts

```bash
vues social-accounts list                # linked accounts: handle, platform, status, is_verified, earnings
vues social-accounts list --limit 10
vues social-accounts list --table
vues social-accounts list --filter platform:eq:TIKTOK
vues social-accounts list --properties id,platform,username
```

### submissions

A URL is never submitted twice: `create` first checks the campaign's existing
submissions for the same TikTok video id and returns `status: existing` if found.
It also refuses campaigns that are closed to submissions or do not list TikTok in
`supported_platforms`. A real submission is queued by Vues; the CLI follows the
batch until Vues reports `created` or a rejection reason. `submissions get`
scans the submissions list, because Vues has no single-submission route.

```bash
vues submissions list                                  # this account's submissions (status, views, earnings)
vues submissions list --campaign-id CAMPAIGN_ID        # only one campaign's submissions (id or short_id)
vues submissions list --limit 25 --table
vues submissions list --filter status:eq:APPROVED
vues submissions get SUBMISSION_ID                     # one submission
vues submissions get SUBMISSION_ID --table
vues submissions create CAMPAIGN_ID --url https://www.tiktok.com/@ata_clipper/video/123 --dry-run
vues submissions create CAMPAIGN_ID --url https://www.tiktok.com/@ata_clipper/video/123 --yes
```

### earnings

```bash
vues earnings get                        # {balance: wallet in micro-dollars, stats: lifetime totals}
vues earnings get --table
vues earnings get --properties balance
```

## JSON shapes and field mapping

Every read returns the API's own objects verbatim (field names verified against
live responses on 2026-10-15):

- **campaign** (`campaigns list` / `campaigns get`): `id`, `short_id`, `name`,
  `cpm`, `max_payout`, `min_payout` (get), `budget`, `approved_spend`,
  `budget_progress_pct`, `supported_platforms` (e.g. `["TIKTOK"]`),
  `submissions_enabled`, `type`, `organization_id`, `organization_name`,
  `description`, `started_at`/`finished_at` (get), `visibility`.
- **linked account** (`social-accounts list`): `id`, `platform` (`TIKTOK`),
  `username`, `display_name`, `status` (`connected`), `is_verified`,
  `followers`, `total_views`, `total_earnings`, `pending_earnings`,
  `submission_count`.
- **submission** (`submissions list` / `get`): `id`, `post_link`,
  `campaign_id`, `campaign_name`, `status`, `views`, `earnings`,
  `post_timestamp`.
- **earnings** (`earnings get`): `balance` = `available_micro`,
  `pending_micro`, `withdrawn_micro`, `lifetime_earned_micro`,
  `last_withdrawal_at` (micro-dollars); `stats` = `total_views`,
  `total_earnings`, `pending_earnings`, submission counts by status,
  `active_campaigns`, `connected_accounts`.
- **creator** (`account get`): `id`, `email`, `first_name`, `last_name`,
  `is_approved`, `is_banned`, `short_id`.

Routes used (all under `https://api.evrgreen.ai/api/v1`, the same ones the
signed-in vues.app clipper pages call): `/users/me`, `/clipper/campaigns`,
`/clipper/campaigns/{id}`, `/clipper/campaigns/{id}/teaser`,
`/organizations/discoverable`, `/clipper/orgs`, `/clipper/applications`,
`/organizations/{id}/apply`,
`/clipper/bundle/accounts?grouped=true`, `/clipper/submissions`,
`/clipper/submissions/batches/{batch_id}`, `/clipper/balance`, `/clipper/stats`.

## Filtering

Every `list` command accepts `--filter/-f` as `field:op:value` (applied locally
after the API returns rows). There are no dedicated filter commands.

## Exit codes

- `0` success
- `1` client/usage error (bad arguments, refused mutation, failed request)
- `2` not authenticated / auth status reports no authenticated profile
