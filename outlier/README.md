# Outlier CLI

## DESCRIPTION

A browser-automation command-line interface for the Outlier AI worker portal. Use it to discover the gig work assignments queued for the account, and to read Outlier's own reason when that queue is empty. Outlier publishes no public API, so this CLI calls the site's internal JSON API from inside an authenticated browser page and signs in through Outlier's passwordless emailed link without any terminal prompt.

## Docs

- Website: https://app.outlier.ai
- Sign-in: https://app.outlier.ai/login

## Installation

```bash
cd <cli-tools-root>/outlier
uv tool install -e . --force --refresh --python "$(command -v python3)"
```

Browser automation is driven by `browser-harness` (CDP), a transitive dependency of `cli-tools-shared`. No separate "install browsers" step is required.

After installation, the `outlier` command will be available in your terminal.

## Quick Start

```bash
# Configure the account address Outlier mails the sign-in link to (one time)
echo 'ACCOUNT_EMAIL=you@example.com' >> ~/.local/share/cli-tools/outlier/.env

# Authenticate (fully non-interactive; reads the emailed link from Gmail)
outlier auth login

# Confirm the saved session
outlier auth status

# List queued work assignments
outlier tasks list --table

# When the list is empty, ask why
outlier queue status --table
```

## Authentication

Outlier has **no password**. Sign-in is passwordless: submitting the account address on `https://app.outlier.ai/login` mails a one-time link (`https://app.outlier.ai/login/verify?token=...`), and opening that link establishes the session.

`outlier auth login` performs that whole flow headlessly, with no terminal prompt and no visible browser, so it works from automation that has no tty:

1. Opens `https://app.outlier.ai/login` in the CLI's persistent browser profile and submits `ACCOUNT_EMAIL`.
2. Reads the emailed link back through the repo-owned `google` CLI (`google gmail search`, then `google gmail get <id> --raw`), accepting only a message whose Gmail `internalDate` is at or after the moment the link was requested — a stale link is never reused.
3. Navigates to the link and persists the resulting session (`_jwt` cookie on `.outlier.ai`) in the CLI's own browser profile.

Requirements for `auth login`:

- `ACCOUNT_EMAIL` set in `~/.local/share/cli-tools/outlier/.env`.
- The `google` CLI installed and authenticated for that mailbox (`google auth status`).

There is no Outlier credential to store: no password, API key, or token exists for this account, so nothing about Outlier belongs in the CLI-tools secret manager.

```bash
# Non-interactive login (mails a fresh link and consumes it)
outlier auth login

# Force a fresh sign-in even when a session is already saved
outlier auth login --force
outlier auth login -F

# Check authentication status (JSON, per profile and credential type)
outlier auth status
outlier auth status --table

# Run the configured live auth test (reads /internal/logged_in_user)
outlier auth test

# Clear the saved browser session
outlier auth logout
```

### Profiles (`outlier auth profiles`)

```bash
# List all profiles
outlier auth profiles list

# Show a profile
outlier auth profiles get default

# Select the active profile for its auth type
outlier auth profiles select PROFILE_NAME

# Create a profile
outlier auth profiles create PROFILE_NAME

# Delete a profile
outlier auth profiles delete PROFILE_NAME
```

## Commands

### Tasks (`outlier tasks`)

Outlier's queue endpoint (`GET /internal/v2/tasks/peek_queue`) is the only representation the worker portal has of "work available to me". Each entry is an *assignment*: a project the account has been routed to, together with the qualification it must clear.

```bash
# List queued assignments (JSON, the default)
outlier tasks list

# Table output
outlier tasks list --table
outlier tasks list -t

# Cap the number of records
outlier tasks list --limit 10
outlier tasks list -l 10

# Filter (field:op:value)
outlier tasks list --filter "type:eq:OUTLIER_QUALIFICATION_IN_QUEUE"
outlier tasks list -f "qualification_status:eq:unstarted"

# Restrict output fields
outlier tasks list --properties "id,display_name,qualification_status"
outlier tasks list -p "id,url"

# Use a non-default profile
outlier tasks list --profile work

# Full detail for one assignment (id is the `id` field from `tasks list`)
outlier tasks get 66edda0f65beb7be44e8d0a7
outlier tasks get 66edda0f65beb7be44e8d0a7 --table
outlier tasks get 66edda0f65beb7be44e8d0a7 -p "id,display_name,required_qualifications"
```

Outlier exposes no per-assignment endpoint, so `tasks get` reads the same queue and returns the matching entry in full. An id that is not currently queued is an error, not an empty result.

### Queue (`outlier queue`)

```bash
# Queue state, including Outlier's own reason for an empty queue
outlier queue status
outlier queue status --table
outlier queue status --properties "is_empty_queue,empty_queue_reason"
outlier queue status --profile work
```

`empty_queue_reason` carries Outlier's `preAssignmentEmptyQueueReason` verbatim. Values observed in Outlier's own frontend include `KYCInfoCollection`, `PaySetup`, `TaxSetup`, `AccountVerification`, `PausedProject`, `NoTasks`, and `NoTasksMatchingSpecializations`. Outlier renders the first three as "To continue, please complete the required pay setup."

### Onboarding (`outlier onboarding`)

```bash
# Live onboarding state: current step, its status, and every step
outlier onboarding status
outlier onboarding status --table
outlier onboarding status --properties "step_type,step_status,next_step_id"
outlier onboarding status --profile work

# Every onboarding step Outlier requires, one row each
outlier onboarding steps list
outlier onboarding steps list --table
outlier onboarding steps list --limit 3
outlier onboarding steps list --filter "status:eq:unstarted"
outlier onboarding steps list --properties "id,status"

# One step by id
outlier onboarding steps get complete-profile
outlier onboarding steps get complete-profile --table

# The worker profile the Create Profile step is prefilled from
outlier onboarding profile
outlier onboarding profile --table

# Identity-verification state behind the Persona / Verify identity step
outlier onboarding identity
outlier onboarding identity --table

# Complete the Create Profile step end to end: submit the form, read the
# verification SMS off this Mac, and enter it
outlier onboarding phone verify --phone 8125551234
outlier onboarding phone verify --phone 8125551234 --channel whatsapp
outlier onboarding phone verify --phone 8125551234 --first-name Adam --last-name Bertram

# Attach a resume to the Import skills step (.pdf or .docx)
outlier onboarding skills upload-resume --file ~/resume.pdf
outlier onboarding skills upload-resume --file ~/resume.pdf --table
```

`onboarding status` and `onboarding steps` read
`GET /internal/experts/qualification/onboarding/v2`; `onboarding profile` reads
`GET /internal/worker/get_pii`. None of them is cached — they are what an action
is judged by.

`onboarding phone verify` drives the real Create Profile form rather than
Outlier's own `bypass-*` / `complete-phone-verification` endpoints, so the
site's validation, resend cooldown, and fraud-session plumbing all run as they
do for a person. Outlier keeps the code-entry screen in client-side state only
— reloading `/onboarding/complete-profile` puts the phone form back — so
requesting the code and entering it have to happen in one browser session. The
CLI therefore reads the SMS itself through the repo-owned `imessage` CLI
(matching how `auth login` reads the sign-in email through the `google` CLI),
and only accepts a code received at or after the moment it submitted the form.

Outlier re-sends the *same* code inside its 30-second resend window, so an
unchanged code is not a stale one; only the receive time decides freshness.

### Cache (`outlier cache`)

```bash
# Clear cached read responses
outlier cache clear

# Bypass the cache for one execution
outlier --no-cache tasks list
```

## Output Contract

### `outlier tasks list` record

One record per entry in `peek_queue.assignments`. Every field is `null` when Outlier does not return it — nothing is defaulted or invented.

| Field | Type | Source |
|-------|------|--------|
| `id` | string \| null | `assignment.projectId` — Outlier assignments have no id of their own; the frontend keys them on the project id |
| `url` | string \| null | absolute form of `JSONResponse.qualificationCallToAction.url` when its `type` is `relative_url` |
| `type` | string \| null | `assignment.type` (e.g. `OUTLIER_QUALIFICATION_IN_QUEUE`, `ACCOUNT_VERIFIACTION_IN_QUEUE`) |
| `assignment_type` | string \| null | `assignment.assignmentType` (e.g. `chosen`) |
| `node_type` | string \| null | `assignment.nodeType` |
| `project_id` | string \| null | `assignment.projectId` |
| `review_level` | integer \| null | `assignment.reviewLevel` |
| `onboarding_flow_id` | string \| null | `assignment.onboardingFlowId` |
| `name` | string \| null | `JSONResponse.name` |
| `display_name` | string \| null | `JSONResponse.displayName` |
| `description` | string \| null | `JSONResponse.externalDescription` |
| `qualification_id` | string \| null | `JSONResponse.id` |
| `qualification_type` | string \| null | `JSONResponse.qualificationType` (e.g. `course`, `worker_skill`) |
| `qualification_status` | string \| null | `JSONResponse.qualificationStatus` (e.g. `unstarted`, `worker_pending`) |
| `qualification_list_status` | string \| null | `qualificationList.qualificationListStatus` |
| `qualification_estimated_time` | number \| null | `JSONResponse.qualificationEstimatedTime`, verbatim — Outlier never renders a unit for it, so none is asserted |
| `is_assessment` | boolean \| null | `JSONResponse.isAssessment` |
| `is_pay_multiplier` | boolean \| null | `JSONResponse.isPayMultiplier` |
| `created_at` | string \| null | `JSONResponse.createdAt` (ISO 8601) |
| `updated_at` | string \| null | `JSONResponse.updatedAt` (ISO 8601) |

Outlier's queue response carries **no pay amount, no currency, and no slot count** — pay lives on a separate rate card (`/internal/scaler/pay_rate_card/...`) and is not part of an assignment.

### `outlier tasks get` record

Every field above, plus:

| Field | Type | Source |
|-------|------|--------|
| `qualification_list_id` | string \| null | `qualificationList.qualificationListId` |
| `required_qualifications` | array | `qualificationList.requiredQualificationListInfo[]`, each normalized to `{id, name, display_name, description, qualification_type, qualification_status, is_assessment, url}` |
| `metadata` | object \| null | `JSONResponse.metadata` (e.g. `{courseId, courseDuration, courseVersion}`) |
| `user_project_onboarding_state` | object \| null | `assignment.userProjectOnboardingState` |
| `json_response` | object \| null | the complete raw `JSONResponse`, unfiltered |

### `outlier queue status` record

| Field | Type | Source |
|-------|------|--------|
| `is_empty_queue` | boolean \| null | `isEmptyQueue` |
| `assignment_count` | integer | length of `assignments` |
| `missions_created` | boolean \| null | `missionsCreated` |
| `empty_queue_reason` | string \| null | `emptyQueueEvent.preAssignmentEmptyQueueReason` |
| `empty_queue_reasons_by_project` | object \| null | `emptyQueueEvent.emptyQueueReasons` |
| `user_id` | string \| null | `emptyQueueEvent.userId` |
| `active_worker_team` | string \| null | `emptyQueueEvent.activeWorkerTeam` |
| `requested_at` | string \| null | `emptyQueueEvent.requestedAt` |
| `available_projects` | array \| null | `emptyQueueEvent.availableProjects` |
| `onboarded_projects` | array \| null | `emptyQueueEvent.onboardedProjects` |
| `onboarded_and_active_projects` | array \| null | `emptyQueueEvent.onboardedAndActiveProjects` |
| `current_chosen_project_id` | string \| null | `emptyQueueEvent.currentChosenProjectLayer.projectId` |
| `current_assigned_project_layers` | array \| null | `emptyQueueEvent.currentAssignedProjectLayers` |
| `server_side_request_id` | string \| null | `emptyQueueEvent.serverSideRequestId` |

### `outlier onboarding status` record

| Field | Type | Source |
|-------|------|--------|
| `result` | string \| null | `currentState.result` |
| `flow_display_name` | string \| null | `currentState.state.flowDisplayName` |
| `step_display_name` | string \| null | `currentState.state.stepDisplayName` |
| `step_type` | string \| null | `currentState.state.stepType` |
| `step_status` | string \| null | `currentState.state.stepStatus` |
| `checkpoint` | integer \| null | `currentState.state.checkpoint` |
| `next_step_id` | string \| null | `nextStep.id` |
| `next_step_title` | string \| null | `nextStep.title` |
| `next_step_status` | string \| null | `nextStep.status` |
| `steps` | array | `qualifications` (see below) |

### `outlier onboarding steps list` / `steps get` record

| Field | Type | Source |
|-------|------|--------|
| `id` | string \| null | `qualifications[].id` |
| `title` | string \| null | `qualifications[].title` |
| `description` | string \| null | `qualifications[].description` |
| `status` | string \| null | `qualifications[].status` |
| `disallow_mobile` | boolean \| null | `qualifications[].disallowMobile` |
| `metadata` | object \| null | `qualifications[].metadata` |

Step ids are Outlier's own `QualificationId` values: `complete-profile`,
`identity`, `skill-selection`, `skill-screenings`, `task-training`,
`intro-to-outlier`, `fraud_checkpoint`, `banking-setup`, `assessment`,
`sample-assessment`. Statuses are `unstarted`, `worker_pending`,
`corp_pending`, `qualified`, `failed`.

### `outlier onboarding identity` record

| Field | Type | Source |
|-------|------|--------|
| `persona_identity_verification` | boolean \| null | `personaIdentityVerification` from `GET /internal/identity-verification/assignments` |
| `idv_audit_status` | any \| null | the verbatim body of `GET /internal/tns-audits/idv_audit_status` |

**Outlier names the identity step two different ways, and this matters when
reading `onboarding status`.** The onboarding endpoint reports
`step_type: "persona"` / `step_display_name: "Persona"` — the vendor, Persona
Identities — while the dashboard row and `nextStep.id` are `identity` /
"Verify identity". They are the same step: government ID plus a selfie. A
`step_type` of `persona` therefore means the account is sitting on identity
verification, which this CLI never starts, consents to, or completes.

`idv_audit_status` is passed through verbatim because it returned a bare
`null` at capture time — no audit exists until an inquiry has been attempted —
so no sub-fields are invented for it.

### `outlier onboarding profile` record

| Field | Type | Source |
|-------|------|--------|
| `worker_id` | string \| null | `worker` |
| `status` | string \| null | `status` |
| `first_name` | string \| null | `firstName` |
| `last_name` | string \| null | `lastName` |
| `country_code` | string \| null | `countryCode` |
| `state` | string \| null | `addressSubdivision` |
| `state_code` | string \| null | `addressSubdivisionCode` |
| `phone_number` | string \| null | `phoneNumber` |
| `phone_number_verified` | boolean \| null | `phoneNumberVerified` |

### `outlier onboarding skills upload-resume` record

| Field | Type | Source |
|-------|------|--------|
| `resume_file` | string | the resolved `--file` path as uploaded |
| `uploaded` | boolean | true; the command raises rather than returning false |
| `url` | string | the URL the browser was on when the upload finished |

The Import skills screen carries no `<input>` until the Resume card's
"File Upload" button is clicked, so the command clicks it first and only then
targets the file input it mounts. Progress is judged by Outlier's own copy
(`uploading...`, `parsing...`, `processing...`): the marker must appear,
proving the file was accepted, and then clear, proving the parse finished.

### `outlier onboarding phone verify` record

| Field | Type | Source |
|-------|------|--------|
| `phone_number` | string | the `--phone` value as submitted |
| `channel` | string \| null | the channel picked, or null when Outlier never asked |
| `requested_at_ms` | integer | epoch ms the form was submitted at |
| `verified` | boolean | true; the command raises rather than returning false |
| `url` | string | the URL Outlier landed on after the code was accepted |

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--force` | `-F` | Re-authenticate even when a session is saved (`auth login`) |
| `--profile` |  | Use a named authentication profile |
| `--version` | `-v` | Show version and exit |
| `--no-cache` |  | Bypass cached read responses for this execution |

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/outlier/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/outlier/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state. Outlier has no reusable credential of any kind, so it owns no secret-manager entry.

Root config variables:

```bash
# Required: the address Outlier mails the passwordless sign-in link to
ACCOUNT_EMAIL=you@example.com

# Optional: override the default site URL
BASE_URL=https://app.outlier.ai

# Browser settings (true = invisible, false = visible browser)
HEADLESS=true

# Optional browser-harness runtime settings
# BROWSER_USER_AGENT=
# BROWSER_WINDOW_SIZE=1440,900

# Response cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

Browser-auth selectors, login URLs, and other authenticated-page signals are defined in `browser.py` as `BrowserAutomation` class constants, each annotated with the live capture it came from.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Architecture

This CLI uses `cli_tools_shared.auth.BrowserAutomation` with browser-harness-backed Chrome automation.

| File | Role |
|------|------|
| `browser.py` | Declarative auth hooks plus the magic-link `AUTH_LOGIN_HANDLER` |
| `magic_link.py` | Reads the emailed sign-in link back through the `google` CLI |
| `config.py` | `BaseConfig` subclass: `ACCOUNT_EMAIL`, headless flag, live `test_connection` |
| `client.py` | Authenticated in-page `fetch` of `/internal/*` with `X-CSRF-Token` |
| `parsers.py` | Normalizes Outlier's JSON into the documented records |
| `main.py` | Typer command contract, filtering, properties, rendering |

Authentication signals (validated live 2026-09-02):

- **Session**: `_jwt` cookie on `.outlier.ai` (JWT carrying `userId` and `loginMethod: "magic_link"`, ~3-day expiry). Nothing is kept in `localStorage`.
- **CSRF**: every `/internal/*` call needs `X-CSRF-Token` copied from the `_csrf` cookie; without it the API returns `401 {"status_code":401,"error":"Request does not have user"}`.
- **Logged out**: `https://app.outlier.ai/` redirects to `/login`, whose card renders `input[type="email"][data-testid="email-input"]`.

## Known Account Gate

As of 2026-09-03, `outlier tasks list` returns `[]` and `outlier queue status`
reports `empty_queue_reason: "KYCInfoCollection"` on Adam's account.
`outlier onboarding status` is the command that says why:

| Step | Status |
|------|--------|
| `complete-profile` (Create profile) | `qualified` |
| `skill-selection` (Import skills) | `qualified` |
| `identity` (Verify identity) | `unstarted` — **current gate** |
| `skill-screenings` (Verify skills) | `unstarted` |
| `fraud_checkpoint` (Fraud Checkpoint) | `unstarted` |

`Create profile` was completed through `outlier onboarding phone verify`.
`Import skills` needed a resume (`outlier onboarding skills upload-resume`)
plus a LinkedIn OAuth consent, which a human completed.

The account now reports `step_type: "persona"`, `checkpoint: 2`. That is the
**Verify identity** step under its vendor name — see
`outlier onboarding identity`. It requires a government ID and a selfie, so
this CLI stops there by design and never starts, consents to, or completes an
inquiry.

`Verify skills` is gated behind it:
`https://app.outlier.ai/expert/onboarding/unified-skills-screenings` still
redirects to `/onboarding` now that `skill-selection` is `qualified`, and the
dashboard renders "Verify skills" as step 4 behind "Verify identity" as
step 3. Pay setup and tax forms are likewise out of scope by design.

An empty list from `outlier tasks list` is a real, verified empty queue, not a
parser failure.

## Debugging

```bash
# Run with a visible browser
HEADLESS=false outlier tasks list
```

## Requirements

- Python 3.11+
- The repo-owned `google` CLI, authenticated for `ACCOUNT_EMAIL`'s mailbox (needed only by `auth login`)
- The repo-owned `imessage` CLI, with Full Disk Access (needed only by `onboarding phone verify`)
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - cli-tools-shared (transitively pulls in browser-harness)

## License

MIT
