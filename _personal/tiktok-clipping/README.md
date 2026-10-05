# tiktok-clipping

## DESCRIPTION

The tiktok-clipping CLI coordinates durable video jobs, bounded DeepSeek proposals, verified publication, campaign submissions, and measured strategy changes. Use it from n8n to enforce account, source, budget, retry, and ownership rules outside model discretion.

## Installation

This personal CLI was created with the repository lifecycle scaffold. Install or refresh it through the owning installer from the cli-tools checkout:

```bash
_repo/skills/cli-tool/scripts/install-cli-tool.sh tiktok-clipping
```

Python 3.11 or later is required. The JSON/SQLite core uses the standard library; the command surface uses Typer and cli-tools-shared. The Studio bridge imports the owning tiktok-cli SDK, participant readiness imports the owning whop-cli SDK, and execution reconciliation imports the owning n8n-cli SDK. Live rendering adapters additionally require ffmpeg with subtitles support and the installed youtube and whisper service CLIs. The source tree contains no credentials. Service credentials remain in each owning service CLI profile and its CLI-tools secret manager, never in this configuration or `.env` examples.

## Safe first boot

`config.example.json` deliberately has `account: null`, `sources: []`, `adapter_module: null`, and zero daily budgets. These values cannot publish or spend model calls. Copy it to an absolute path and set trusted verified values before enabling operation. The database and workspace must be absolute paths writable by the service account. Initial control state is paused.

The only allowed TikTok identity is `ata_clipper` (leading `@` is accepted). A distinct immutable account ID, owning service profile, timestamp, and live verification provenance are required. `atalearning`, `Fred`, and any other handle are rejected. Account, source, campaign, permissions, executable code, limits, and completion criteria are never model outputs.

## Commands

Every command prints JSON data on stdout and diagnostic errors on stderr. Commands requiring state take `--config` after the command. Help and version are available:

```bash
tiktok-clipping --help
tiktok-clipping --version
```

Prepare one durable job. Only `ready: true` may enter a DeepSeek node:

```bash
tiktok-clipping jobs prepare --kind clip --config /absolute/config.json
tiktok-clipping jobs prepare --kind learn --config /absolute/config.json
tiktok-clipping jobs prepare --kind metrics --config /absolute/config.json
```

Without `native_text`, legacy clip/learn envelopes contain `ready`, `job_id`, `lease_token`, `kind`, `prompt`, `input_digest`, `policy_digest`, and `input`. Metrics jobs execute through the trusted adapter and return `ready: false`; they never enter a model. Other explicit states include paused, stopped, unconfigured, idle, insufficient_samples, and adapter outcomes. Due validated retries execute without another model call.

Apply bounded model JSON from stdin; execute an already validated job; read back an ambiguous publication; revalidate blocked work or a proven pre-publication visual failure after a trusted integration repair:

```bash
tiktok-clipping jobs apply --config /absolute/config.json < /absolute/model-envelope.json
tiktok-clipping jobs run JOB_ID --config /absolute/config.json
tiktok-clipping jobs reconcile JOB_ID --config /absolute/config.json
tiktok-clipping jobs retry JOB_ID --config /absolute/config.json
```

Failed visual work may be revalidated only with a durable readiness-failure record, a retained verified asset/proposal, an expired lease, and no publication reservation, dispatch history, result or approved visual attempt. The exact observed legacy `submission_form_unavailable` readiness failure is recognized with its original job event. Recovery preserves attempts, revisions, receipts and spend; ambiguous writes always require reconciliation. `jobs get` retains the last failure and bounded owning-SDK form diagnostics (origin/route flags and counts only) after the browser closes.

Apply input exact keys are `job_id`, `lease_token`, `input_digest`, `policy_digest`, `proposal`. A clip proposal has `start_seconds`, `end_seconds`, `caption`, `style` and optional `segments` (up to four ordered `{start_seconds,end_seconds}` cuts). Cuts must be finite, inside the measured source and nonoverlapping. Bounding start/end must exactly equal the minimum/maximum cut bounds; all duration limits, caption timing and visual sampling use the sum of cut lengths. The ledger conservatively reserves the entire bounding source span, including gaps, so reordered edits cannot reuse those gaps as another accepted clip. A strategy proposal has only `weights`, `exploration`. `proposal` may instead contain the n8n DeepSeek node shape `{result: "<strict JSON>", reasoning: "..."}`; only `result` is parsed. Markdown fences, duplicate JSON keys, unknown proposal keys, NaN/infinity, oversized payloads, invalid durations, foreign styles, stale leases, changed policy, and forged digests are rejected. Exact duplicate apply does not repeat publication.

Ingest a trusted source record; run bounded maintenance on a five-minute cadence:

```bash
tiktok-clipping jobs ingest --config /absolute/config.json < /absolute/source-record.json
tiktok-clipping jobs maintain --config /absolute/config.json
```

Source record exact fields: `source_id`, `media_id`, `media_url`, `duration_seconds`, `transcript`, `transcript_segments`, `observed_at`, `provenance`, `categories`. Transcript segments are ordered, nonoverlapping `{start_seconds,end_seconds,text}` records measured against the actual source duration. No transcript or metadata is invented when unavailable. Sources require explicit HTTPS feeds, exact allowed media hosts, a reuse basis, and verified active Whop Content Rewards campaign evidence. Campaign exact fields: `id`, `enabled`, `categories`, `minimum_followers`, `expires_at`, `provenance`, `platform`, `submission_window_seconds`. Platform must be `whop_content_rewards`; gambling/politics categories and positive follower minima are rejected. The campaign-specific submission window must be explicit, between 1 and 1800 seconds. It is not assumed to be 30 minutes. The live adapter must recheck remaining campaign budget and all account/source requirements before publication.

Each source may reserve at most the configured `max_clips_per_source` active or public jobs. Proven pre-publication terminal failures release quota while retaining bounded version/window retry history. Prior windows appear as exclusions in the prompt. Atomic overlap checks forbid any overlapping accepted range, including near-identical clips. Active work deduplicates; new nonoverlapping clips require preceding work to finish. Exhausted sources create no more jobs. Rejected media candidates receive only the configured number of revisions and are never repeatedly published to test variants.

Inspect records and aggregate status:

```bash
tiktok-clipping jobs list --config /absolute/config.json --limit 10
tiktok-clipping jobs list --config /absolute/config.json --filter status:eq:ambiguous --properties id,status,error --table
tiktok-clipping jobs get JOB_ID --config /absolute/config.json
tiktok-clipping jobs get JOB_ID --config /absolute/config.json --table
tiktok-clipping status get
tiktok-clipping status get --config /absolute/config.json --table
```

`jobs list` supports `--table/-t`, `--limit/-l`, `--filter/-f`, and `--properties/-p`. `jobs get` supports `--table/-t`. Lease tokens are omitted from inspection output. Aggregate status includes account evidence, durable budgets, job counts, strategy version, setup reason, control state, and whether an adapter is configured. Configured does not mean authenticated or publication-ready.

Persist control state or restore baseline strategy:

```bash
tiktok-clipping control set running --config /absolute/config.json
tiktok-clipping control set paused --config /absolute/config.json
tiktok-clipping control set stopped --config /absolute/config.json
tiktok-clipping strategy rollback --config /absolute/config.json
```

Append trusted performance evidence; submit or inspect campaign rewards independently of uploaded state:

```bash
tiktok-clipping metrics record --config /absolute/config.json < /absolute/metric-snapshot.json
tiktok-clipping rewards submit JOB_ID --config /absolute/config.json
tiktok-clipping rewards refresh JOB_ID --config /absolute/config.json
```

Metric snapshot exact fields: `publication_id`, `observed_at`, `measured_at`, `provenance`, `views`, `likes`, `comments`, `shares`, `watch_seconds`, `revenue`, `revenue_currency`. Unknown numbers and currency stay `null`. The example uses views as a proxy objective; actual revenue optimization requires objective `revenue`, a mature campaign-specific cohort age, and authoritative observed earnings. Legacy trusted adapter earnings retain their separate snapshot unit contract. The live Whop SDK instead retains independently nullable `pending_cents`, `received_cents`, and `total_earned_cents` as exact signed integer strings with `amount_basis: creator_net`, currency, actual scan interval, moderation freshness, and source provenance. These cents are not converted to floats or copied into the legacy learning objective. The optional outcome policy below selects exact net-cent fields at explicit age horizons; views or a CPM rate never establish earnings. Revenue snapshots cannot overwrite ordinary view observations. Known revenue requires currency. Snapshots preserve revisions, timestamps, and provenance. Cohorts select the latest revision at comparable post age; revisions to unknown replace older known values. Different revenue currencies are never pooled. Insufficient known samples prevent learning. Experiments change only existing style weights within configured per-weight delta and exploration bounds. Approved-source queue priority uses mature comparable-age objective evidence only after the configured minimum samples; bounded seeded exploration retains other sources. Clip prompts include source/media, caption, duration, style and revenue performance context. Seeded weighted style assignment uses the active strategy; the proposed style must equal the assigned style. Results retain the strategy version used at proposal, plus source/style and actual revenue evidence. The same evidence cannot repeatedly create versions. Measured regressions restore baseline.

## Comparable outcome selection

Existing configurations keep their single legacy objective. Add `outcome_policy` inside `learning` to use separately labeled measured income and engagement horizons. This example is a policy template, not a production activation:

```json
"outcome_policy": {
  "objectives": [
    {"id": "received-usd-14d", "channel": "creator_net", "field": "received_cents", "horizon_seconds": 1209600, "tolerance_seconds": 86400, "currency": "USD"},
    {"id": "views-24h", "channel": "engagement", "field": "views", "horizon_seconds": 86400, "tolerance_seconds": 3600, "currency": null}
  ],
  "baseline_share": 0.10
}
```

Objectives are considered in the configured order. Each decision uses one field, age window and currency. Sparse income may select the explicitly configured engagement proxy; missing values are never zero. With no mature samples the decision is labeled cold-start. Engagement horizons support 6h,24h,7d; creator-net horizons support 7,14,30,60,90d. Tolerances are explicit and must fit measured polling cadence. Revenue requires actual completed fresh observations at that age. Day10 income cannot enter day7; a14d±1d decision needs a real day13–15 observation. Received money can be independently known when pending money is unknown. Actual decreases/reversals and original scan timestamps are preserved; retained last-known money is never forwarded to a later horizon.

A durable bounded candidate window records every presented queued job and its evidence version. Repeated jobs for the same video collapse to one selection unit. Mature video outcomes take priority; otherwise compatible campaign/source regimes supply measured source evidence. Different campaign/rate/policy regimes do not pool. Static configured sources remain the current admission mechanism; renewable catalog admission replaces only that window adapter.

The fixed baseline share B must be positive, and B plus learned exploration E must sum to at most1. Both choose uniformly over N distinct admitted videos. Exploitation chooses the best comparable measured candidate, or the oldest candidate during cold-start. Each video's recorded probability is `(B+E)/N`, plus `1-B-E` for the exploitation winner. Baseline branches use original style weights, exploration uses uniform allowed styles, and exploitation uses current learned weights. The input binds the full selection/style distribution, branch, candidate/evidence/window identity and assigned strategy version. Models cannot supply these fields or change eligibility, disclosure, identities or budgets. Models still choose bounded clip timing/caption within admitted footage.

Each measurement descriptor has its own durable baseline and strategy history. Learning and rollback compare enough measured publications within one compatible regime; baseline controls must have been assigned after the active strategy started. A sparse compatible regime continues to the next configured objective with an explicit fallback reason. Native learning receives exact all-data counts/rational means for only current/baseline styles and branches, plus at most20 recent real examples reduced to fit the existing payload limit. The view is labeled incomplete; the full cohort digest fences callbacks and all-data samples govern eligibility and rollback; exact signed-cent arithmetic preserves large amounts and negative reversals. Revised evidence fences pending learning, and the same unchanged evidence cannot repeatedly create strategy versions. Descriptor migration preserves historical measurements, publication identities and spending counters.

## Native text accounting

The updated clip and learn graphs require `jobs prepare --native-text`. An absent `native_text` block returns explicit unconfigured state without spending a model call. Existing visual-only/manual configurations remain valid; the legacy `jobs apply` proposal boundary remains available only while `native_text` is absent. Each text kind requires its own configured native workflow ID. Learning never falls back to the clipping workflow.

Configure this optional trusted block only after installing and verifying its native workflows and SDK paths:

```json
"native_text": {
  "workflow_ids": {"clip": "VERIFIED_CLIP_WORKFLOW_ID", "learn": "VERIFIED_LEARN_WORKFLOW_ID"},
  "model": {"provider": "deepseek-official", "model": "deepseek-flash"},
  "max_output_tokens": 2048,
  "max_result_bytes": 16384,
  "timeout_seconds": 120,
  "continuation_seconds": 30,
  "retention_seconds": 86400,
  "sdk_package": "/absolute/installed/dsh/package.json",
  "python_executable": "/absolute/coordinator/venv/bin/python"
}
```

Timeout plus continuation must fit the configured job lease. Existing daily call/runtime budgets and explicit token/output caps apply; token prices are not required. Issuance commits the original lease, immutable manifest/overlay hashes and one atomic model-call/runtime reservation before writing artifacts. Its reservation retains the original UTC day across restarts and midnight. Native runtime proof binds the exact attempt envelope, original process identity, durable terminal receipt hash and measured monotonic start/end. Valid timing settles once against the original UTC reservation day; invalid, missing or legacy timing keeps the runtime ceiling reserved. Optional timing-write failure preserves the original native receipt and usage. Verified proof survives artifact cleanup in the reservation ledger.

```bash
tiktok-clipping jobs prepare --kind clip --native-text --config /absolute/config.json --n8n-execution-id EXECUTION_ID --n8n-workflow-id CLIP_WORKFLOW_ID
tiktok-clipping jobs apply-text --config /absolute/config.json --n8n-execution-id EXECUTION_ID --n8n-workflow-id CLIP_WORKFLOW_ID < /absolute/native-receipt.json
tiktok-clipping jobs retry-text JOB_ID --config /absolute/config.json
```

`prepare` returns `ready`, the original `text` envelope, its exact serialized `task`, and the transport byte limit. Only the native DeepSeekHarness node receives that task and trusted overlay. The runner disables tools/retries and durably writes the receipt before stdout. Native bridges preserve result bytes for Python strict JSON parsing, use the original prepare identity, ignore reasoning, and strip failure messages. If escaping exceeds the transport budget or stdout is lost, the coordinator reads only the exact owned original `result.json`.

`jobs apply-text --no-execute` accounts and validates without adapter actions, leaving accepted proposals ready for an operator or the next normal workflow. Receipt accounting is independent of permission to act. Four measured disjoint token buckets are retained with session/sequence provenance; unavailable usage stays null. Identical replay accounts once. Paused, stopped, expired or superseded leases can still record usage but cannot authorize a proposal. Validated proposals and applied-attempt state commit together. Late responses and typed transient/timeouts requeue under existing attempts/backoff; positive provider Retry-After is durable across clip, learn and visual calls, including HTTP 503 and delays longer than a day.

`queued` means autonomous bounded recovery. `blocked` means an unknown original worker or a prerequisite failure. `retry-text` is explicit prerequisite revalidation for blocked work with no proposal or public-action history and a terminated original native attempt. It preserves attempts, reservations and provider cooldown, never refunds unknown usage, and never bypasses publication reconciliation.

Active maintenance handles deadline-bound reward submission and uncertain public actions before text recovery. Paused maintenance can ingest local receipts. Expired text attempts remain fenced until exact native termination is proven. Original runner markers bind process PID/start identity; cleanup additionally checks the terminal owning n8n execution. A persisted trusted native-node return can establish completion when failure occurred before the runner marker, with preparation-worker absence and separately annotated provenance. If the callback was also lost and no marker exists, the launch remains explicitly unknown (`text_native_launch_proof_missing`); timer expiry alone never reissues that token. This residual crash gap is visible in the attempt's durable cleanup issue.

Maintenance rotates bounded text inspections and prunes only known owned artifacts after retention, receipt ingestion and process proof. Hash inventory commits before unlink; interrupted cleanup resumes without deleting new/changed files. Ledger receipts, token provenance, original reservation and termination evidence survive pruning.

## Native visual review

When `visual` is configured, a geometry-checked render pauses at `visual_pending`. Its private attempt contains hash-bound sampled JPEGs, manifest and DeepSeek overlay. The coordinator records ownership and reserves a model call plus worst-case runtime before writing files. The envelope binds the original lease, input/proposal/policy and asset hashes, nonce, owning n8n execution/workflow, model deadline and continuation deadline.

The trusted workflow supplies `--n8n-execution-id` and `--n8n-workflow-id` to `jobs prepare`, `jobs apply`, and `jobs run`. After the native node returns, `jobs apply-visual` requires both flags and accepts the bounded receipt on stdin. Native model output never supplies this execution identity. Each visual attempt has a separate model budget reservation; a failed or receiptless attempt retains that reservation. Observed usage stores four disjoint token counts; unavailable usage remains null.

The runner uses the native DeepSeek image attachments and public session usage projection. Its JSONL sessions and image objects stay inside the exact attempt directory. No tools are available. The receipt persists before output, including failed-call usage. Exact receipt replay resumes an interrupted decision transaction without spending or publishing again. Expired or reclaimed leases cannot authorize publication. Rate limits persist a provider-wide cooldown and preserve the reported delay.

A rejected review passes bounded checks, reason and the rejected proposal back as untrusted observations for the next proposal. Composition failures select another eligible style when possible. Rights, accounts, policy, revision limits and budgets remain trusted configuration. Sampled frames cannot establish audio rights or prove every frame of a video.

Retention preserves result, usage, immutable artifact inventory and execution/process termination evidence. Maintenance removes only exact owned artifacts after retention, a terminal owning execution and original process absence; a missing execution or marker remains an explicit recoverable cleanup issue. Interrupted preparation uses its separately persisted worker identity. Partial cleanup resumes after restart, and rotating bounded inspection prevents blocked attempts from starving later cleanable work. Unknown directories, files and live processes are preserved.

The Studio bridge reserves the stable request identity before private preparation. Immediately before Post, its callback atomically verifies the original lease, running control, reservation, exact actor/draft/asset/policy binding and records `dispatch_pending`. Interrupted public actions reconcile only. An accepted receipt remains authoritative even if later browser cleanup fails.

## Durable safety and recovery

SQLite `BEGIN IMMEDIATE` atomically claims work, reserves budgets, and records ownership. Lease expiry requeues only bounded safe work. Interrupted publication becomes ambiguous; only verified published readback or authoritative absence can resolve it. Unknown uploads are never automatically repeated. One coordinator owns transient/rate-limit retries, bounded exponential delay, Retry-After, attempts, and capability circuits. Account/profile and asset digest form a durable publication idempotency key. UTC budgets survive process restart; exhausted posting/runtime budgets keep valid work ready until the next UTC day.

Stop/pause is checked before adapter work and upload. A configured whole-operation wall deadline is shared across nested calls. The process boundary enforces the remaining deadline and kills worker-owned descendants, including media processes with separate sessions. Each adapter-backed outer operation reserves its full ceiling durably before work. Nested calls share that reservation. A completed or failed operation settles once to the ceiling of its trusted monotonic elapsed seconds, against the original UTC reservation day. A crash or missing timing proof retains the full reservation; legacy counters are never refunded. n8n must separately enforce the model node's own wall deadline; this coordinator durably enforces its model-call count and lease.

Publication requires a fresh independent readiness record proving publishing, submission, source reuse, account/campaign eligibility, and positive remaining campaign budget. Assets must reside in the configured workspace and match their actual SHA-256 and size. Independent quality verifies portrait dimensions, measured duration, audio, captions, and coherent boundaries. Publication receipts must match exact account and TikTok post URL. Upload is never called monetized. Verified upload commits durable receipt, then immediately submits campaign reward; maintenance repairs pending submission and inspects unknown/submitted outcomes without blind resubmission.

Maintenance prioritizes up to five deadline-bound submissions and uncertain-publication reconciliations, then inspects at most `metrics_batch_size` due reward records. One owning-SDK payout scan is shared by the due batch; each exact submission read uses `refresh_payouts=False`. Per-record `next_at` survives restart, ordinary polls use `metrics_poll_seconds`, and typed provider cooldown/backoff is never shortened. Generated-media and visual-artifact cleanup runs last while time remains. A full media budget does not block small remote submission/reconciliation; media writers still check physical space before allocation. Confirmed publication plus confirmed submitted/accepted/rejected campaign status permits removal of its generated clip; publication, source/window, metrics, and campaign receipts remain durable. Ambiguous uploads retain media. Metrics use persisted due times and `metrics_batch_size`, prefer oldest due publications, poll by `metrics_poll_seconds`, deliberately schedule comparable-age cohorts, and stop normal statistics polling after `metrics_max_age_seconds`. Revenue/reward state remains separate. Expiring one campaign does not disable final metrics, campaign readback, or other active sources.

Production render ownership is committed before temporary directories or final media files are created. Final paths include the original job/input/proposal/policy binding; receipt evidence survives cleanup. Maintenance rotates at most20 rendered assets and20 temporary records, hashes under the remaining deadline outside SQLite, then rechecks eligibility and deletes exact unchanged files in a short transaction that fences job claims. Superseded revisions and terminal pre-publication failures may be reclaimed; active leases, recoverable visual work, and uncertain/public action assets remain protected. Direct encoders inherit the media lock. Whisper temporary WAV/JSON files require the exact recorded CLI process group to be absent and the observed owning filename contract; unknown descendants, files, or changed directories stay preserved with a durable cleanup issue. Interrupted deletion resumes from its committed hash/inode inventory. No unowned directory is adopted by scanning.

## Trusted adapter protocol

`adapter_module` names a trusted installed Python module exposing `create_adapter(config)`. It receives fixed coordinator-selected methods only and must not own retry loops. The process worker treats its stdout as bounded strict JSON and passes no model executable code, paths, account changes, or limits.

- `discover(source)` returns source records using approved feed and reuse/campaign evidence.
- `verify_ready(job)` returns exact `{allowed,publish_capable,submission_capable,source_reuse_verified,remaining_budget_cents,account_id,campaign_id,checked_at,provenance}`. Required booleans must be true; identifiers must match; remaining budget is positive; checked timestamp is fresh within the operation deadline.
- `render(job,proposal)` returns `{path,sha256,bytes,provenance}` for a real workspace asset.
- `quality(job,proposal,asset)` returns `{passed,width,height,duration_seconds,audio_present,captions_present,coherent_boundaries,provenance}`. All flags must be true; portrait width/height is 0.5 to 0.65; measured duration matches proposal within 1 second and configured limits.
- `publish(job,asset,idempotency_key)` returns `{publication_id,publication_url,account_id,handle,published_at,provenance}` after independent actual post readback.
- `reconcile(job,idempotency_key)` returns `{state:"published",publication}` or `{state:"absent",authoritative:true,provenance}` or `{state:"unknown",provenance}`.
- `metrics(publication)` returns the metric snapshot fields except publication_id, which the coordinator adds.
- `metrics_batch(publications,continuation,max_pages)` is required by process-isolated adapters. The live implementation uses authenticated own-account Studio reads for immutable due-ID manifests. It returns only native measured records, exact actor and caller-owned continuation; missing IDs and missing native timestamps remain unknown. Independent fresh and historical scan lanes share at most 20 provider pages per invocation: a new head check, fair cohort-prioritized fresh continuation, and historical progress. Newly due IDs enter a separate immutable manifest rather than changing an existing checkpoint. A modeled capacity gate covers 1,800 active posts at 120 posts/day with a 30-minute scheduler, batch size 200 and a 1 MiB transport limit; it verifies 24-hour measurements within one hour while a 36,000-row historical inventory continues. This is a tested capacity/configuration boundary, not a live inventory claim. Scans expire after bounded 30–90 days; cancellation never retires an unresolved publication. Final retirement requires a valid native measurement at the configured final age. Duplicate retained records keep their original timestamps and do not count as new collections. Provider cooldown covers all TikTok metric reads. Existing injected adapters may retain the single-record protocol.
- `submit_rewards(job,reward_ledger)` returns `{submission_id,campaign_id,publication_id,status:"pending",submitted_at,provenance}` after verified submission readback.
- `reconcile_rewards(job,reward_ledger)` reads the original owning-SDK request without redispatch and returns submitted creation proof, exact reserved/pre-action proof, rejected, or unknown.
- `sync_reward_revenue()` advances the owning Whop SDK shared payout pass.
- `reward_status(job,reward_ledger,refresh_payouts=True)` returns `{status,publication_id,campaign_id,observed_at,provenance,earnings}`, with optional `readback_fresh` and the exact bounded `revenue` SDK observation. Status is pending/accepted/rejected/unknown; moderation and monetary completeness are evaluated separately. The live SDK leaves legacy `earnings` null. The coordinator stores current `revenue_observation` separately from independently retained `last_known_revenue` field proofs. Unknown/current misses do not erase historical known amounts or relabel them fresh. Only a newer validated observation replaces an amount, including a genuine decrease/reversal. Original-token CAS rejects stale workers and old cached scans cannot overwrite newer known values.

Adapters raise `AdapterFailure(category,message,retry_after=None,provider=None,code=None,status=None)` from `engine.py`; categories are auth, transient, rate_limit, permanent, ambiguous. Trusted provider metadata crosses the isolated worker boundary. A Whop rate limit sets a durable provider-wide cooldown across readiness, publication and submission calls, honoring an uncapped positive finite Retry-After. Uncertain writes stay reconcile-only while carrying that cooldown separately. Unknown publish/submission exceptions and timeouts become ambiguous. Missing capabilities explicitly raise a permanent `capability_missing` error and cannot be mistaken for successful integration. `live.py` implements public campaign/source discovery, local rendering and exact native execution/process inspection. `studio_adapter.py` provides the guarded owning Studio SDK bridge; `live.py` rechecks scoped source rights and owning-SDK participant readiness before private upload and again immediately before public action, then the Studio guard performs its final lease/control/reservation check. Actual first publication and accepted submission still require their live proof. Revenue and analytics remain explicitly unavailable until their owning read contracts and authenticated proofs are integrated. `media.py` performs real download, timed transcription, burned subtitles, decoding, and media checks.

## Tests

```bash
uv run --project _personal/tiktok-clipping --with pytest python -m pytest _personal/tiktok-clipping/tests -q
_repo/skills/cli-tool/scripts/validate-cli-tool.sh tiktok-clipping
_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name tiktok-clipping
```

Tests include concurrent claims, stale/forged ownership, policy changes, crash recovery, ambiguous publication, authoritative reconciliation, stop between stages, persistent budgets, rate limiting, bad model JSON, nonfinite/oversized numbers, corrupt assets, bounded revisions, multiple nonoverlapping source clips, scheduled metric cohorts, revisions, small samples, learning versioning, and rollback. Synthetic test adapters are confined to tests and do not represent real publication evidence. Full live publication/measurement remains a separate end-to-end acceptance gate.

## Explicit rights and readiness

Live publishing requires `rewards_account` with exact `account_id`, `username`, named `profile: rewards`, `verified_at` and verification provenance. Its current actor and exact linked TikTok account are verified through the owning Whop SDK. Real readiness/create/reconcile methods must be available before private preparation. The SDK checks active funded intake separately from its stable requirements digest; changed requirements block unsent publication. Revenue capability is a separate gate and absence never means zero earnings.

Each live source requires an explicit version 2 `publication_policy`, binding `campaign_id`, exact `brief_url` and `brief_content_sha256`, exact `source_url`, `source_sha256` and `source_bytes`. Permissions must authorize video reuse and accompanying original source audio only, forbid external audio and full-source reposts, and specify `minimum_clip_seconds`, `required_caption_tokens`, `required_on_screen_text` and bounded `clip_rules`. New renders never add an advertising disclaimer overlay. Campaigns requiring one are excluded. Native commercial disclosure and required description tags remain enforced. Version 1 receipts remain readable for historical audit and reconciliation, but cannot authorize another public action. Clip rules bind exact ordered segments to truthful additional caption tokens and rendered text. A brief URL alone cannot authorize a download or publication; fresh complete brief content must match its bound hash.

The renderer burns required creator/show attribution throughout the edit, shifts timed captions across the ordered cuts and uses only video/audio from the bound source. Caption style version 2 uses bold white text with a black outline and a deterministic yellow final-word accent. Transcript text stays verbatim; literal ASS control characters are escaped, and unsupported font glyphs fail explicitly. The cache and receipt bind the style version, exact cuts, source audio provenance, overlays and rights-policy digest. Visual manifest version 3 requires `required_attribution_visible` and `no_added_ad_disclaimer`, with typography evaluated where trusted transcript cues expect captions. Historical visual checks remain audit-readable. Music consent in the Studio policy is true only after this exact source/audio/render receipt verifies and the current campaign brief still authorizes that use. Model output cannot add permissions, supply audio, change disclosure or change budgets.

The coordinator retains complete bounded campaign/brief/policy and participant-readiness evidence in the job before preparation and again before Post. External reads hold no SQLite write lock. Original Studio operation policy remains available for reconciliation after campaign expiry or brief changes; accepted or uncertain public actions never become a fresh upload.

Reward submission gets its own durable lease, stable request UUID and exact original Studio receipt. The SDK callback verifies fresh participant identity/readiness, then commits the coordinator dispatch boundary before the one provider write. Crash recovery reads the same owning-SDK request. Only an exact reserved journal with `public_action_dispatched: false` permits retrying that same UUID. Missing/corrupt journals, dispatch-pending and uncertain results never permit another write. Deadline-bound submission/reconciliation is processed before routine reward observations; provider Retry-After is never shortened to meet a campaign deadline. Historical verified creation proof can survive a later read miss; it is retained separately from fresh moderation and earnings.

Operational health is included in `status get`: durable per-capability success/failure, actual last successful publication/submission/measurement, provider cooldown and stale original requests. Optional `monitoring` declares `enabled`, `ambiguity_age_seconds` and `stalled_job_age_seconds`; the prepared deployment disables alerts until activation. Explicit user pause/stop remains quiet, and health reporting never prevents reconciliation or metrics. Terminal rejected/failed clips remain visible in `terminal_failed_jobs`; they do not permanently mark a recovered service unhealthy. Native visual wrapper failure preserves the original attempt and unknown usage, while valid receipts retain their original UTF-8 bytes.

## Renewable source admission

Optional `source_discovery` uses the owning Whop, Google and YouTube SDKs. Its exact keys are `google_profile`, `page_budget`, `campaign_budget`, `brief_budget`, `asset_budget`, `refresh_seconds`, `retry_base_seconds`, `retry_max_seconds`, `authorization_seconds`, `refresh_timeout_seconds`, `materialize_timeout_seconds`, `max_source_bytes`, `max_resolution`, and `submission_window_seconds`. A verified `rewards_account` is required. Discovery and materialization run as durable separate bounded passes under the parent operation deadline; completed full media is reused across restart. Unknown rights and unavailable document suggestions remain ineligible. Campaign-level discovery funding never substitutes for fresh participant readiness before Post.

Dynamic source records add trusted `catalog_admission` and `source_window` references. Immutable evidence lives in the workspace catalog; current validation rechecks the code-owned permission compiler, exact source and fresh dependencies. The coordinator keeps admitted policy and expiry separately from global configuration. Updated evidence can shorten current authority but cannot renew an existing job. Only a new job can receive renewed authorization.

Full provider captions retain their original source timeline and raw hash. Deterministic windows cover the episode fairly, each at most 600 seconds and 24 KiB of serialized cues plus transcript. Cuts must stay within the admitted window. Window cursors commit with admission or a durable exhausted-window skip; windows remain one video for selection weighting. Exact selected-cut Whisper measurements still supply rendered word timing. Commission rights permit only the supplied episode and embedded original audio. No added on-video advertising disclaimer is permitted; creator/show attribution, required description tags and native disclosure remain separate.

Owned media acquisition markers allow exact dead-worker recovery. Completed receipts are immutable; changed bytes are rejected on every retry. Cache eviction fences claims and admissions, preserves active or uncertain public dependencies and compact receipts, and deletes only hash/inode-verified ledger-owned full media. Unknown stages or worker ownership require explicit recovery rather than takeover.
