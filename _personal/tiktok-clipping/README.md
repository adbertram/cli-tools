# tiktok-clipping

## DESCRIPTION

The tiktok-clipping CLI coordinates durable video jobs, bounded DeepSeek proposals, verified publication, campaign submissions, and measured strategy changes. Use it from n8n to enforce account, source, budget, retry, and ownership rules outside model discretion.

## Installation

This personal CLI was created with the repository lifecycle scaffold. Install or refresh it through the owning installer from the cli-tools checkout:

```bash
_repo/skills/cli-tool/scripts/install-cli-tool.sh tiktok-clipping
```

Python 3.11 or later is required. The JSON/SQLite core uses the standard library; the command surface uses Typer and cli-tools-shared. The Studio bridge imports the owning tiktok-cli SDK, and execution reconciliation imports the owning n8n-cli SDK. Live rendering adapters additionally require ffmpeg with subtitles support and the installed youtube and whisper service CLIs. The source tree contains no credentials. Service credentials remain in each owning service CLI profile and its CLI-tools secret manager, never in this configuration or `.env` examples.

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

Clip/learn envelopes contain `ready`, `job_id`, `lease_token`, `kind`, `prompt`, `input_digest`, `policy_digest`, and `input`. Metrics jobs execute through the trusted adapter and return `ready: false`; they never enter a model. Other explicit states include paused, stopped, unconfigured, idle, insufficient_samples, and adapter outcomes. Due validated retries execute without another model call.

Apply bounded model JSON from stdin; execute an already validated job; read back an ambiguous publication; revalidate a blocked job after a trusted integration repair:

```bash
tiktok-clipping jobs apply --config /absolute/config.json < /absolute/model-envelope.json
tiktok-clipping jobs run JOB_ID --config /absolute/config.json
tiktok-clipping jobs reconcile JOB_ID --config /absolute/config.json
tiktok-clipping jobs retry JOB_ID --config /absolute/config.json
```

Apply input exact keys are `job_id`, `lease_token`, `input_digest`, `policy_digest`, `proposal`. A clip proposal has only `start_seconds`, `end_seconds`, `caption`, `style`. A strategy proposal has only `weights`, `exploration`. `proposal` may instead contain the n8n DeepSeek node shape `{result: "<strict JSON>", reasoning: "..."}`; only `result` is parsed. Markdown fences, duplicate JSON keys, unknown proposal keys, NaN/infinity, oversized payloads, invalid durations, foreign styles, stale leases, changed policy, and forged digests are rejected. Exact duplicate apply does not repeat publication.

Ingest a trusted source record; run bounded maintenance on a five-minute cadence:

```bash
tiktok-clipping jobs ingest --config /absolute/config.json < /absolute/source-record.json
tiktok-clipping jobs maintain --config /absolute/config.json
```

Source record exact fields: `source_id`, `media_id`, `media_url`, `duration_seconds`, `transcript`, `transcript_segments`, `observed_at`, `provenance`, `categories`. Transcript segments are ordered, nonoverlapping `{start_seconds,end_seconds,text}` records measured against the actual source duration. No transcript or metadata is invented when unavailable. Sources require explicit HTTPS feeds, exact allowed media hosts, a reuse basis, and verified active Whop Content Rewards campaign evidence. Campaign exact fields: `id`, `enabled`, `categories`, `minimum_followers`, `expires_at`, `provenance`, `platform`, `submission_window_seconds`. Platform must be `whop_content_rewards`; gambling/politics categories and positive follower minima are rejected. The campaign-specific submission window must be explicit, between 1 and 1800 seconds. It is not assumed to be 30 minutes. The live adapter must recheck remaining campaign budget and all account/source requirements before publication.

Each source may generate at most the configured `max_clips_per_source` jobs. Prior windows appear as exclusions in the prompt. Atomic overlap checks forbid any overlapping accepted range, including near-identical clips. Active work deduplicates; new nonoverlapping clips require preceding work to finish. Exhausted sources create no more jobs. Rejected media candidates receive only the configured number of revisions and are never repeatedly published to test variants.

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

Metric snapshot exact fields: `publication_id`, `observed_at`, `measured_at`, `provenance`, `views`, `likes`, `comments`, `shares`, `watch_seconds`, `revenue`, `revenue_currency`. Unknown numbers and currency stay `null`. The example uses views as a proxy objective; actual revenue optimization requires objective `revenue`, a mature campaign-specific cohort age, and authoritative observed earnings. Whop reward readback is copied into a separate revenue snapshot channel using its own observation timestamp, currency, and provenance; it never derives earnings from views or a CPM rate. These records reuse the existing ledger read and do not require another remote Whop request. Revenue snapshots cannot overwrite ordinary view observations. Known revenue requires currency. Snapshots preserve revisions, timestamps, and provenance. Cohorts select the latest revision at comparable post age; revisions to unknown replace older known values. Different revenue currencies are never pooled. Insufficient known samples prevent learning. Experiments change only existing style weights within configured per-weight delta and exploration bounds. Approved-source queue priority uses mature comparable-age objective evidence only after the configured minimum samples; bounded seeded exploration retains other sources. Clip prompts include source/media, caption, duration, style and revenue performance context. Seeded weighted style assignment uses the active strategy; the proposed style must equal the assigned style. Results retain the strategy version used at proposal, plus source/style and actual revenue evidence. The same evidence cannot repeatedly create versions. Measured regressions restore baseline.

## Native visual review

When `visual` is configured, a geometry-checked render pauses at `visual_pending`. Its private attempt contains hash-bound sampled JPEGs, manifest and DeepSeek overlay. The coordinator records ownership and reserves a model call plus worst-case runtime before writing files. The envelope binds the original lease, input/proposal/policy and asset hashes, nonce, owning n8n execution/workflow, model deadline and continuation deadline.

The trusted workflow supplies `--n8n-execution-id` and `--n8n-workflow-id` to `jobs prepare`, `jobs apply`, and `jobs run`. After the native node returns, `jobs apply-visual` requires both flags and accepts the bounded receipt on stdin. Native model output never supplies this execution identity. Each visual attempt has a separate model budget reservation; a failed or receiptless attempt retains that reservation. Observed usage stores four disjoint token counts; unavailable usage remains null.

The runner uses the native DeepSeek image attachments and public session usage projection. Its JSONL sessions and image objects stay inside the exact attempt directory. No tools are available. The receipt persists before output, including failed-call usage. Exact receipt replay resumes an interrupted decision transaction without spending or publishing again. Expired or reclaimed leases cannot authorize publication. Rate limits persist a provider-wide cooldown and preserve the reported delay.

A rejected review passes bounded checks, reason and the rejected proposal back as untrusted observations for the next proposal. Composition failures select another eligible style when possible. Rights, accounts, policy, revision limits and budgets remain trusted configuration. Sampled frames cannot establish audio rights or prove every frame of a video.

Retention preserves result, usage, immutable artifact inventory and execution/process termination evidence. Maintenance removes only exact owned artifacts after retention, a terminal owning execution and original process absence; a missing execution or marker remains an explicit recoverable cleanup issue. Interrupted preparation uses its separately persisted worker identity. Partial cleanup resumes after restart, and rotating bounded inspection prevents blocked attempts from starving later cleanable work. Unknown directories, files and live processes are preserved.

The Studio bridge reserves the stable request identity before private preparation. Immediately before Post, its callback atomically verifies the original lease, running control, reservation, exact actor/draft/asset/policy binding and records `dispatch_pending`. Interrupted public actions reconcile only. An accepted receipt remains authoritative even if later browser cleanup fails.

## Durable safety and recovery

SQLite `BEGIN IMMEDIATE` atomically claims work, reserves budgets, and records ownership. Lease expiry requeues only bounded safe work. Interrupted publication becomes ambiguous; only verified published readback or authoritative absence can resolve it. Unknown uploads are never automatically repeated. One coordinator owns transient/rate-limit retries, bounded exponential delay, Retry-After, attempts, and capability circuits. Account/profile and asset digest form a durable publication idempotency key. UTC budgets survive process restart; exhausted posting/runtime budgets keep valid work ready until the next UTC day.

Stop/pause is checked before adapter work and upload. A configured whole-operation wall deadline is shared across nested calls. The process boundary enforces the remaining deadline and kills worker-owned descendants, including media processes with separate sessions. The full runtime reservation persists on crashes. n8n must separately enforce the model node's own wall deadline; this coordinator durably enforces its model-call count and lease.

Publication requires a fresh independent readiness record proving publishing, submission, source reuse, account/campaign eligibility, and positive remaining campaign budget. Assets must reside in the configured workspace and match their actual SHA-256 and size. Independent quality verifies portrait dimensions, measured duration, audio, captions, and coherent boundaries. Publication receipts must match exact account and TikTok post URL. Upload is never called monetized. Verified upload commits durable receipt, then immediately submits campaign reward; maintenance repairs pending submission and inspects unknown/submitted outcomes without blind resubmission.

Maintenance is bounded to five records per reconciliation/reward category. Confirmed publication plus confirmed submitted/accepted/rejected campaign status permits removal of its generated clip; publication, source/window, metrics, and campaign receipts remain durable. Ambiguous uploads retain media. Metrics use persisted due times and `metrics_batch_size`, prefer oldest due publications, poll by `metrics_poll_seconds`, deliberately schedule comparable-age cohorts, and stop normal statistics polling after `metrics_max_age_seconds`. Revenue/reward state remains separate. Expiring one campaign does not disable final metrics, campaign readback, or other active sources.

## Trusted adapter protocol

`adapter_module` names a trusted installed Python module exposing `create_adapter(config)`. It receives fixed coordinator-selected methods only and must not own retry loops. The process worker treats its stdout as bounded strict JSON and passes no model executable code, paths, account changes, or limits.

- `discover(source)` returns source records using approved feed and reuse/campaign evidence.
- `verify_ready(job)` returns exact `{allowed,publish_capable,submission_capable,source_reuse_verified,remaining_budget_cents,account_id,campaign_id,checked_at,provenance}`. Required booleans must be true; identifiers must match; remaining budget is positive; checked timestamp is fresh within the operation deadline.
- `render(job,proposal)` returns `{path,sha256,bytes,provenance}` for a real workspace asset.
- `quality(job,proposal,asset)` returns `{passed,width,height,duration_seconds,audio_present,captions_present,coherent_boundaries,provenance}`. All flags must be true; portrait width/height is 0.5 to 0.65; measured duration matches proposal within 1 second and configured limits.
- `publish(job,asset,idempotency_key)` returns `{publication_id,publication_url,account_id,handle,published_at,provenance}` after independent actual post readback.
- `reconcile(job,idempotency_key)` returns `{state:"published",publication}` or `{state:"absent",authoritative:true,provenance}` or `{state:"unknown",provenance}`.
- `metrics(publication)` returns the metric snapshot fields except publication_id, which the coordinator adds.
- `submit_rewards(job,reward_ledger)` returns `{submission_id,campaign_id,publication_id,status:"pending",submitted_at,provenance}` after verified submission readback.
- `reward_status(job,reward_ledger)` returns `{status,publication_id,campaign_id,observed_at,provenance,earnings}`. Status is pending/accepted/rejected/unknown. Earnings are null or `{amount,currency,provenance,observed_at}` from an actual service observation.

Adapters raise `AdapterFailure(category,message,retry_after=None)` from `engine.py`; categories are transient, rate_limit, permanent, ambiguous. Unknown publish/submission exceptions and timeouts become ambiguous. Missing capabilities explicitly raise a permanent `capability_missing` error and cannot be mistaken for successful integration. `live.py` implements public campaign/source discovery, local rendering and exact native execution/process inspection. `studio_adapter.py` provides the guarded owning Studio SDK bridge; account publishing, reward submission, and analytics remain explicitly unavailable until authenticated live proofs exist. `media.py` performs real download, timed transcription, burned subtitles, decoding, and media checks.

## Tests

```bash
uv run --project _personal/tiktok-clipping --with pytest python -m pytest _personal/tiktok-clipping/tests -q
_repo/skills/cli-tool/scripts/validate-cli-tool.sh tiktok-clipping
_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name tiktok-clipping
```

Tests include concurrent claims, stale/forged ownership, policy changes, crash recovery, ambiguous publication, authoritative reconciliation, stop between stages, persistent budgets, rate limiting, bad model JSON, nonfinite/oversized numbers, corrupt assets, bounded revisions, multiple nonoverlapping source clips, scheduled metric cohorts, revisions, small samples, learning versioning, and rollback. Synthetic test adapters are confined to tests and do not represent real publication evidence. Full live publication/measurement remains a separate end-to-end acceptance gate.
