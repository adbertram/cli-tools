# n8n deployment for @ata_clipping

This deployment is installed on adam-server but is not a live publishing system yet. All four schedules are inactive. Production configuration has no verified account, no approved campaign sources, no live adapter, and zero daily spending/posting budgets. Do not remove these gates to make a status check look successful.

## Workflows

| Purpose | Workflow | Schedule when enabled |
|---|---|---|
| Discover, choose and publish clips | iok4Q6LnQuJ4xMvg | Every 10 minutes |
| Collect measured performance | iaxAgwwMFnZ9ZmFa | Every 30 minutes |
| Propose bounded strategy changes | sftryxebi3TPw1Ti | Hourly at minute 7 |
| Recover work and submit/read rewards | cJwOXa8mzdYR6Nz7 | Every 5 minutes |

The definitions are in workflows/. CLI state is outside the deployment tree at /Users/adam/.local/share/tiktok-clipping. Redeploying code must preserve that state.

Native n8n DeepSeek Harness nodes use the headless profile with deepseek-analysis.yml. All tool plugins are disabled, and deepseek-boundary.mjs denies tool execution even if a tool is registered later. Only strict result JSON reaches the coordinator. Base64 transports that JSON through the shell; model strings never become shell syntax. Ownership leases, policy/input digests, account identity, budgets and every side effect are checked by the coordinator.

Server commands select the measured FFmpeg-full installation with libass and the existing ggml-small.en.bin Whisper model explicitly. The coordinator uses one bounded operation deadline and a 900-second lease; model calls have a 120-second limit. Initial production optimization is observed revenue, compared at eight days of age with one-hour tolerance; metrics remain eligible through ten days. Missing earnings remain unknown. These are declared operating choices, not income promises.

## Verified integration evidence

Strict n8n node validation returned zero failures and warnings for all four workflows. Native restricted DeepSeek execution 65466 returned valid JSON. Executions 65477–65480 exercised the four server commands and correctly returned account_identity_unverified without invoking publishing. Isolated execution 65484 exercised prepare → native DeepSeek → encoded transport → CLI proposal validation; it correctly stopped at capability_missing: verify_ready. Its synthetic account, source and state were isolated, then deleted. Neither test workflow remains installed.

A real server FFmpeg smoke generated a 720×1280 three-second synthetic video with audio, full decode verification and 11,645 white caption pixels. It was never published. Core, media and independent failure tests are recorded in the delivery report; no synthetic receipt counts as publishing or income.

## Activation gates

Complete the authenticated TikTok and Whop integrations before enabling these schedules. Verify the exact numeric identity of @ata_clipping, publishing access, linked participant account, campaign eligibility and rights, actual submission fields and deadline, and measured analytics/earnings. Public campaign discovery does not establish membership or eligibility. The public adapter deliberately reports missing capabilities for these authenticated operations.

Campaign-specific content requirements also need enforceable checks. For example, the inspected Boxabl campaign requires a whole-home visual, brand presence and demographic information; source-list access alone does not prove a finished clip meets them. Configure only sources whose complete requirements the system can verify.

After the authenticated operations work, populate trusted config with current evidence and explicit budgets, run one real eligible cycle through publishing, submission and readback, then enable schedules. Preserve pause/stop and unknown-outcome gates. No ambiguous upload or submission is repeated without authoritative reconciliation.

The immediate browser-access gate is macOS Accessibility and Screen Recording for CuaDriver:

```sh
/Users/adam/.local/bin/cua-driver permissions grant
```

For server state or an immediate pause:

```sh
ssh adam-server /Users/adam/.local/bin/tiktok-clipping status get --config /opt/cli-tools/_personal/tiktok-clipping/deploy/config.json
ssh adam-server /Users/adam/.local/bin/tiktok-clipping control set paused --config /opt/cli-tools/_personal/tiktok-clipping/deploy/config.json
```
