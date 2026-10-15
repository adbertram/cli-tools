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

Vues signs in only with **Google or Apple** (Supabase GoTrue). There is no email
/ password or API key, so authentication is a one-time, human step:

1. Open <https://vues.app/login> and **sign up free with Google or Apple**.
2. In the Vues app, **link your TikTok account** (for Trawler: `@ata_clipper`).
3. Run `vues auth login` and complete the Google/Apple sign-in in the browser
   that opens.

`vues auth login` opens a real browser for the provider sign-in (it cannot be
automated), then captures the Supabase session. Every later command runs over
plain HTTP with that saved session and refreshes it automatically; no browser is
opened again until the refresh token itself expires.

No reusable credential is ever stored in a `.env` file. The captured Supabase
tokens are runtime auth state under
`~/.local/share/cli-tools/vues/authentication_profiles/<profile>/`.

```bash
vues auth login              # one-time browser sign-in (Google/Apple)
vues auth login --force      # -F: clear the saved session and sign in again
vues auth status             # JSON: per-profile, per-credential-type auth state
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

### campaigns

Vues gates all campaign data (CPM rate, minimum views, budget, brief, rules)
behind login; nothing campaign-level is readable unauthenticated. Each command
returns the campaign object exactly as the API provides it.

```bash
vues campaigns list                      # campaigns the creator can see (JSON)
vues campaigns list --limit 20           # -l: cap the number returned
vues campaigns list --table              # -t: table view
vues campaigns list --filter status:eq:active   # -f: field:op:value (local)
vues campaigns list --properties id,name        # -p: only these fields
vues campaigns get CAMPAIGN_ID           # one campaign in full (rate, min views, budget, brief, rules)
vues campaigns get CAMPAIGN_ID --table
vues campaigns join CAMPAIGN_ID --dry-run   # show the join request without sending
vues campaigns join CAMPAIGN_ID --yes       # apply to / join the campaign
```

### social-accounts

```bash
vues social-accounts list                # linked accounts: handle, platform, verification/eligibility
vues social-accounts list --limit 10
vues social-accounts list --table
vues social-accounts list --filter platform:eq:tiktok
vues social-accounts list --properties id,platform,username
```

### submissions

A URL is never submitted twice: `create` first checks existing submissions for
the same TikTok video id and returns `status: existing` if found.

```bash
vues submissions list                                  # this account's submissions (status, views, earnings)
vues submissions list --campaign-id CAMPAIGN_ID        # only one campaign's submissions
vues submissions list --limit 25 --table
vues submissions list --filter status:eq:approved
vues submissions get SUBMISSION_ID                     # one submission
vues submissions get SUBMISSION_ID --table
vues submissions create CAMPAIGN_ID --url https://www.tiktok.com/@ata_clipper/video/123 --dry-run
vues submissions create CAMPAIGN_ID --url https://www.tiktok.com/@ata_clipper/video/123 --yes
```

### earnings

```bash
vues earnings get                        # balance, pending, paid, withdrawal minimum (as exposed)
vues earnings get --table
vues earnings get --properties balance,pending
```

## JSON shapes and field mapping

Every read returns the API's own object in full (no fields dropped), so Trawler
can map:

- **rate / CPM per 1,000 views, minimum views per clip, max payout per clip,
  budget total/spent/left, end date, brief and structured requirements** → the
  corresponding fields of the `campaigns get` object.
- **creator identity and balance** → `account get`.
- **linked TikTok handle, verification/eligibility** → `social-accounts list`.
- **submission status (pending/approved/rejected + reason), tracked views,
  earnings** → `submissions list` / `submissions get`.
- **balance, pending, paid, withdrawal minimum** → `earnings get`.

Vues advertises **no minimum view threshold**; `campaigns get` reports whatever
the API actually states per campaign.

The exact field names in the campaign, submission, earnings and social-account
objects are returned verbatim from the Vues API and are finalised against the
first authenticated response (Vues exposes none of them to the public site or
its JavaScript bundle). The confirmed, directly wired routes are `GET
/api/v1/users/me`, `/api/v1/organizations`, `/api/v1/campaigns` and
`/api/v1/campaigns/{id}`. The linked-account, submission, earnings and join
endpoints are resolved at runtime from the backend's own authenticated OpenAPI
document (`/api/openapi.json`) rather than from a hard-coded guess.

## Filtering

Every `list` command accepts `--filter/-f` as `field:op:value` (applied locally
after the API returns rows). There are no dedicated filter commands.

## Exit codes

- `0` success
- `1` client/usage error (bad arguments, refused mutation, failed request)
- `2` not authenticated / auth status reports no authenticated profile
