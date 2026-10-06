---
name: tiktok-cli
description: >-
  Execute tiktok operations using the `tiktok` CLI tool.
  TikTok transcript downloader using yt-dlp, saved (favorited) video listing,
  and publishing, status, listing, and deleting your own TikTok videos.
  Triggers: tiktok, tiktok cli, tiktok transcripts, tiktok favorites, tiktok videos,
  tiktok publish, delete tiktok video, tiktok auth
---

<objective>
Execute tiktok operations using the `tiktok` CLI. All tiktok interactions should use this CLI.
</objective>

<project_overrides>
Before acting on this skill, run:

```bash
~/.agents/skills/skill-expert/scripts/load-skill-overrides.sh tiktok-cli
```

Apply any printed instructions alongside this skill's own workflow: they extend it and
never repeal its limits. No output means no project override is in effect. A non-zero
exit means the project's override file is broken -- report it and stop rather than
silently running unmodified.
</project_overrides>

<quick_start>
The `tiktok` CLI follows this pattern:
```bash
tiktok <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Download transcripts for one or more TikTok videos. | `tiktok transcripts download` |
| List all of the logged-in account's saved (favorited) TikTok videos. Needs a `browser_session` login first (`tiktok auth login --credential-type browser_session`). | `tiktok favorites list` |
| Get one saved video's details (id, url, caption, author) by id or URL. No login required. | `tiktok favorites get` |
| Publish a video through the Content Posting API (custom API profile). | `tiktok videos publish` |
| Check a Direct Post's status by `publish_id` (custom API profile). | `tiktok videos status` |
| List a profile's posted videos; your own private posts need your `browser_session`. | `tiktok videos list` |
| Get one posted video by id (`browser_session`). | `tiktok videos get` |
| Read verified own-account Studio content with endpoint provenance. | `tiktok videos list --profile clipper --username ata_clipper --studio --expected-account-id 7692213003349443597` |
| Read exact owned post IDs in one bounded Studio scan; resume beyond 1000 feed items using caller-owned continuation. | `tiktok studio inventory owned-post-ids.json --profile clipper --username ata_clipper --account-id 7692213003349443597` |
| Read actual cumulative views, likes, comments, shares, and favorites for an own post. Missing measurements stay null. | `tiktok videos metrics <video_id> --profile clipper --username ata_clipper --expected-account-id 7692213003349443597` |
| Permanently delete one of your videos by id; requires `--yes` (`browser_session`). | `tiktok videos delete` |
| Configure authentication, optionally using a manual browser login. | `tiktok auth login` |
| Open visible Chrome for manual login in an isolated named browser profile; no stored credentials are submitted. | `tiktok auth login --profile clipping --credential-type browser_session --manual` |
| Read verified current numeric account ID and username in a named browser profile. | `tiktok account get --profile clipping` |
| Report each recent own post's restriction state (For You eligibility), TikTok's stated reason, and appeal state; read-only. | `tiktok account check --profile clipper --username ata_clipper --expected-account-id 7692213003349443597` |
| Read TikTok Studio's own pre-post verdict (Content check lite, music copyright) for a local MP4; uploads a private draft, removes it, never posts. | `tiktok studio check clip.mp4 --profile clipper --username ata_clipper --account-id 7692213003349443597` |
| Clear stored credentials. | `tiktok auth logout` |
| Check authentication status across profiles. Performs a live round-trip for every configured credential type so the report reflects ground truth — not on-disk belief. Saved credentials whose live verification fails are reported as ``authenticated: false`` with the failure reason in ``api_test``. | `tiktok auth status` |
| Manage authentication profiles | `tiktok auth profiles` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `tiktok` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `tiktok` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Manual Browser Login">
Use `auth login --profile <named-profile> --credential-type browser_session --manual`
for an explicitly requested visible login or MFA/CAPTCHA recovery. It opens plain
Chrome with that profile's existing persistent data. Finish login there, then
press Enter in the terminal; without an interactive terminal, close that window
within five minutes instead. The shared engine verifies live authentication and
saves the profile's session. Manual login requires an explicit non-default
profile, submits no stored credentials, and leaves ordinary login unchanged.
Use Computer Use only for this CLI-owned window; never bypass CAPTCHA. Verify
with `tiktok auth status --profile <named-profile>` before service operations.
</principle>

<principle name="Command Groups">
- **account** -- Read current identity from TikTok's passport account-info endpoint. `get` uses `browser_session`, returns the numeric `account_id` as a string, and excludes contact/session fields. Optional `--expected-username` and `--expected-account-id` fail on mismatch; authentication alone does not establish the intended account. `check` reads Studio's per-post penalty endpoint (`/mod/v1/getPenaltyDetails/`) for the `--limit` most recent posts plus any `--video-id`: `eligibility` is `restricted`, `no_penalty`, or null; `reasons` carry TikTok's code and title; `appeal_status` is decoded. `account.standing` is always null because TikTok web has no Account check page. A failed penalty read stays null with `penalty_error`; `in_studio_feed: false` means the complete feed lacks that ID. It never appeals or changes anything.
- **transcripts** -- Download TikTok video transcripts
- **favorites** -- List and look up saved (favorited) TikTok videos. `list` needs a `browser_session` login (`tiktok auth login --credential-type browser_session`); `get` does not.
- **videos** -- `publish`/`status` use the custom Content Posting API profile (`--profile posting`). `list`/`get`/`delete`/`metrics` use `browser_session`. Explicit `list/get --studio` and `metrics` verify the session owner against `--username` and optional exact `--expected-account-id`; they read Studio content using the observed Views sorting control. Studio counts are per-post measurements, never account-counter substitutes or earned revenue. Missing metrics are null. Limited/malformed reads and bounded incomplete lookups are inconclusive, never proof of absence. The public profile route remains the default for `list/get`; HTTP failures are not empty feeds. A `SELF_ONLY` API publish returns no post ID; listing alone does not prove which post an ambiguous upload created.
- **studio inventory** -- Takes a regular JSON file of 1–1000 unique positive string IDs (64 KiB), exact `--username` and `--account-id`, optional regular `--continuation` JSON file, and `--max-pages` 1–20. One capture serves all IDs. Resume refreshes the head, requires at least two pages, and binds exact actor/profile/request-set/stable native semantics without signing material. Keep prior results and their actual measurement timestamps. `records` are newly measured matches, `requested_complete` includes previously observed matches, and `unresolved_ids` remain unknown even at `provider_end`; never infer deletion. Restart without a continuation for a new pass. No public-feed fallback.
- **studio check** -- Takes a local MP4, exact `--username` and `--account-id`, and `--timeout` 30–900 seconds. `verdict` is `pass` or `restricted` only when `status` is `completed`; `not_finished`, `check_failed`, `limit_reached`, `unavailable`, `switch_off`, and `not_offered` carry a null verdict, which is never a pass. `issues` hold TikTok's code and text. Each run spends one of the account's daily checks. A pass does not guarantee the post stays unrestricted. Never kill a running check: its leftover draft makes Studio drop other unlocked drafts on the next upload-page load.
- **auth** -- Manage tiktok authentication
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
