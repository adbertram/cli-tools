---
name: tiktok-clipping-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute TiktokClipping operations using the `tiktok-clipping` CLI tool.
  CLI interface for TiktokClipping.
  Triggers: tiktok-clipping, tiktok-clipping cli
---

<project_overrides>
Before service operations, run `~/.agents/skills/skill-expert/scripts/load-skill-overrides.sh tiktok-clipping-cli`. Apply printed instructions alongside this skill; nonzero means stop and report the broken override.
</project_overrides>

<objective>
Execute TiktokClipping operations using the `tiktok-clipping` CLI. All TiktokClipping interactions should use this CLI.
</objective>

<quick_start>
The `tiktok-clipping` CLI follows this pattern:
```bash
tiktok-clipping <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Persist control state; running requires verified exact account and approved sources | `tiktok-clipping control set <STATE>` |
| Validate leased model JSON from stdin, then execute once through trusted adapters | `tiktok-clipping jobs apply` |
| Account native receipt from stdin, then recheck its original lease before acting | `tiktok-clipping jobs apply-text` |
| Validate a native image-review receipt and its exact durable lease | `tiktok-clipping jobs apply-visual` |
| Get one durable job, excluding its ownership credential | `tiktok-clipping jobs get <JOB_ID>` |
| Queue an allowlisted trusted source record from bounded JSON stdin | `tiktok-clipping jobs ingest` |
| List durable jobs, including explicit failed, blocked and ambiguous states | `tiktok-clipping jobs list` |
| Recover expired leases, reconcile uploads and maintain campaign submissions | `tiktok-clipping jobs maintain` |
| Claim one durable job or return an explicit paused/unconfigured/idle state | `tiktok-clipping jobs prepare` |
| Read back an ambiguous upload without repeating publication | `tiktok-clipping jobs reconcile <JOB_ID>` |
| Revalidate blocked work or an explicitly proven pre-publication visual/render failure | `tiktok-clipping jobs retry <JOB_ID>` |
| Request a bounded new proposal for a proven quiescent failed render | `tiktok-clipping jobs retry <JOB_ID> --revise-render --reason "Measured cut timing rejection"` |
| Revalidate blocked preproposal text work after its original native process ended | `tiktok-clipping jobs retry-text <JOB_ID>` |
| Run a ready job; coordinator alone owns retries and side-effect budgets | `tiktok-clipping jobs run <JOB_ID>` |
| Append a trusted timestamped metric snapshot from stdin; unknown values stay null | `tiktok-clipping metrics record` |
| Read actual campaign acceptance/rejection and observed earnings | `tiktok-clipping rewards refresh <JOB_ID>` |
| Submit one post to its verified campaign before its verified campaign-specific deadline | `tiktok-clipping rewards submit <JOB_ID>` |
| Inspect setup, control, account, durable budgets and strategy version | `tiktok-clipping status get` |
| Restore recorded baseline; models cannot change hard policy | `tiktok-clipping strategy rollback` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `tiktok-clipping` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `tiktok-clipping --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **control** -- Persist pause, stop or running state (subcommands: set)
- **jobs** -- Prepare, validate and execute durable jobs (subcommands: apply, apply-text, apply-visual, get, ingest, list, maintain, prepare, reconcile, retry, retry-text, run)
- **metrics** -- Record provenance-preserving measurement snapshots (subcommands: record)
- **rewards** -- Track campaign submission separately from publication and earnings (subcommands: refresh, submit)
- **status** -- Inspect current setup and durable budgets (subcommands: get)
- **strategy** -- Bounded strategy versions and rollback (subcommands: rollback)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`tiktok-clipping --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<safety_contract>
- Every stateful operation needs an explicit trusted absolute JSON configuration path. Pass --config after the action. Missing config, account evidence, or capabilities never means permission to invent values.
- Exact TikTok actor is ata_clipper, numeric ID 7692213003349443597, named profile clipper. Never use atalearning. This local coordinator owns no remote auth command; live service authentication remains in its owning profile and secret manager.
- The updated native graphs use jobs prepare --native-text with explicit enclosing execution/workflow IDs. Send only ready:true original text.task to DeepSeekHarness. jobs apply-text accounts the original native receipt before rechecking permission to act; never use reasoning. Without native_text, manual legacy jobs apply remains supported. Read the README native text accounting contract before configuring these graphs.
- Metrics jobs execute without a model. jobs maintain runs bounded recovery, ambiguous publication readback, immediate/pending campaign submission and campaign status checks. Unknown uploads are never repeated.
- Upload, reward submission, campaign acceptance, and observed earnings are distinct states. Missing metrics/revenue remain null. Live readiness must prove both publishing and submission before upload.
- Optional learning.outcome_policy chooses one named field/age/currency descriptor at a time. Exact signed SDK cents remain separate from legacy decimal revenue. A configured engagement fallback is labeled proxy; no mature outcomes is cold-start. Original fresh revenue history, per-descriptor baselines and recorded candidate/style probabilities govern learning. Read the README comparable outcome selection contract before configuring this policy.
- Configuration example has null account, no sources/adapters, zero daily budgets and first boot paused. Its mere presence is not an authenticated end-to-end pipeline.
- status get includes durable health evidence. Optional monitoring is disabled for staged installation; operational activation explicitly enables it. Expected pause/stop/cooldown and source-specific exclusions remain distinct from actionable global failures and stale unknown requests. Every completed production graph path checks health once through the existing Global Error Handler; health never blocks read-only recovery. Failed terminal clips remain counted without permanently marking a recovered capability unhealthy.
- Read ../../../_personal/tiktok-clipping/README.md for the complete source, adapter, output, and configuration contract. Run jobs maintain --config PATH on a five-minute n8n cadence; only the coordinator owns retries.
</safety_contract>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>

<render_revision>
Typed measured ASR endpoint rejection consumes the configured revision allowance and passes exact rejected cuts and timing feedback to the next proposal. Other render failures never become quality rejections automatically. `jobs retry --revise-render --reason` requires original unchanged policy, current original rights, an expired lease, the completed original native proposal and terminal process proof, and quiescent owned render/ASR ledgers. Asset, visual or public-action history forbids revision. It records operator intent, preserves existing spend, limits and original deadlines, charges recovery runtime normally, and never renews authority. It queues a new proposal rather than directly retrying the retained proposal.
</render_revision>
