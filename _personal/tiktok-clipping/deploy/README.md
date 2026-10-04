# n8n deployment for @ata_clipper

This deployment is installed on adam-server but is not a live publishing system yet. All four schedules are inactive. Production configuration has no verified account, no approved campaign sources, no live adapter, and zero daily spending/posting budgets. Do not remove these gates to make a status check look successful.

## Workflows

| Purpose | Workflow | Schedule when enabled |
|---|---|---|
| Discover, choose and publish clips | iok4Q6LnQuJ4xMvg | Every 10 minutes |
| Collect measured performance | iaxAgwwMFnZ9ZmFa | Every 30 minutes |
| Propose bounded strategy changes | sftryxebi3TPw1Ti | Hourly at minute 7 |
| Recover work and submit/read rewards | cJwOXa8mzdYR6Nz7 | Every 5 minutes |

The definitions are in workflows/. CLI state is outside the deployment tree at /Users/adam/.local/share/tiktok-clipping. Redeploying code must preserve that state.

Native n8n DeepSeek Harness nodes use the headless profile and immutable per-attempt overlays. All tool plugins are disabled, and deepseek-boundary.mjs denies tool execution even if a tool is registered later. Only strict result JSON reaches the coordinator. Base64 preserves original receipt bytes through the shell; model strings never become shell syntax. Ownership leases, policy/input digests, account identity, budgets and every side effect are checked by the coordinator. Wrapper failure retains the original attempt and unknown usage; it cannot authorize publication.

Server commands select the measured FFmpeg-full installation with libass and the existing ggml-small.en.bin Whisper model explicitly. The coordinator uses one bounded operation deadline and a 900-second lease; model calls have a 120-second limit. Prepared outcome policy compares received creator rewards in USD at fourteen days of actual publication age (one-day tolerance), then falls back explicitly to measured views at twenty-four hours (one-hour tolerance). The baseline share is 0.10. Performance measurement remains due through fifteen days; reward inspection remains independent of that retirement age, including delayed approval/payment. Unknown earnings stay unknown. These are operating choices, not income promises.

The prepared configuration keeps accounts, sources and adapters unset, daily budgets zero, and monitoring disabled during staged installation. It sets a seven-second global minimum (campaign-specific bounds still apply) and twelve attempts so two rejected visual revisions can still reach a final approved publication. Native text is bound independently to the configured clip and learn workflow IDs. Schema3 visual review requires readable striking speech captions, visible required attribution and no added on-video Ad disclaimer; platform commercial disclosure and required description tags remain separate.

Every completed graph branch reaches one operational health gate. All four graphs reference the verified active Global Error Handler F79g2nlj6f1glf8u. `status get` includes durable capability evidence, actual last-success timestamps, provider cooldown and stale original publication/reward requests. When monitoring is explicitly enabled, actionable failures raise an n8n execution error for the existing queue/digest. Explicit pause/stop, bounded transient recovery, cooldown and staged configuration remain distinguishable. Individual inaccessible/unsupported sources do not establish global authentication failure or prove globally empty supply. Health reporting never blocks read-only reconciliation or measurement.

## Verified integration evidence

Strict n8n node validation returned zero failures and warnings for all four workflows. Native restricted DeepSeek execution 65466 returned valid JSON. Executions 65477–65480 exercised the four server commands and correctly returned account_identity_unverified without invoking publishing. Isolated execution 65484 exercised prepare → native DeepSeek → encoded transport → CLI proposal validation; it correctly stopped at capability_missing: verify_ready. Its synthetic account, source and state were isolated, then deleted. Neither test workflow remains installed.

A real server FFmpeg smoke generated a 720×1280 three-second synthetic video with audio, full decode verification and 11,645 white caption pixels. It was never published. Core, media and independent failure tests are recorded in the delivery report; no synthetic receipt counts as publishing or income.

## Activation gates

Complete the authenticated TikTok and Whop integrations before enabling these schedules. Verify the exact numeric identity of @ata_clipper, publishing access, linked participant account, campaign eligibility and rights, actual submission fields and deadline, and measured analytics/earnings. Public campaign discovery does not establish membership or eligibility. The public adapter deliberately reports missing capabilities for these authenticated operations.

Campaign-specific content requirements also need enforceable checks. For example, the inspected Boxabl campaign requires a whole-home visual, brand presence and demographic information; source-list access alone does not prove a finished clip meets them. Configure only sources whose complete requirements the system can verify.

After the authenticated operations work, populate trusted config with current evidence and explicit budgets, run one real eligible cycle through publishing, submission and readback, then enable schedules. Preserve pause/stop and unknown-outcome gates. No ambiguous upload or submission is repeated without authoritative reconciliation.

The visual definition adds a native image-review stage with an immutable per-attempt overlay and trusted execution identity. Code deployment preserves the paused state, zero budgets, unconfigured account and empty sources. Updating the source workflow file does not enable its schedule. The production-shaped isolated workflow smoke is a separate deployment gate; earlier text-only executions do not count as visual proof.

Use the owning n8n server integration to run `tiktok-clipping status get --config /opt/cli-tools/_personal/tiktok-clipping/deploy/config.json` or `tiktok-clipping control set paused --config /opt/cli-tools/_personal/tiktok-clipping/deploy/config.json` on adam-server. Preserve the external state directory during source refresh.
