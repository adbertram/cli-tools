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
| Read actual cumulative views, likes, comments, shares, and favorites for an own post. Missing measurements stay null. | `tiktok videos metrics <video_id> --profile clipper --username ata_clipper --expected-account-id 7692213003349443597` |
| Permanently delete one of your videos by id; requires `--yes` (`browser_session`). | `tiktok videos delete` |
| Configure authentication, optionally using a manual browser login. | `tiktok auth login` |
| Open visible Chrome for manual login in an isolated named browser profile; no stored credentials are submitted. | `tiktok auth login --profile clipping --credential-type browser_session --manual` |
| Read verified current numeric account ID and username in a named browser profile. | `tiktok account get --profile clipping` |
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
- **account** -- Read current identity from TikTok's passport account-info endpoint. `get` uses `browser_session`, returns the numeric `account_id` as a string, and excludes contact/session fields. Optional `--expected-username` and `--expected-account-id` fail on mismatch; authentication alone does not establish the intended account.
- **transcripts** -- Download TikTok video transcripts
- **favorites** -- List and look up saved (favorited) TikTok videos. `list` needs a `browser_session` login (`tiktok auth login --credential-type browser_session`); `get` does not.
- **videos** -- `publish`/`status` use the custom Content Posting API profile (`--profile posting`). `list`/`get`/`delete`/`metrics` use `browser_session`. Explicit `list/get --studio` and `metrics` verify the session owner against `--username` and optional exact `--expected-account-id`; they read Studio content using the observed Views sorting control. Studio counts are per-post measurements, never account-counter substitutes or earned revenue. Missing metrics are null. Limited/malformed reads and bounded incomplete lookups are inconclusive, never proof of absence. The public profile route remains the default for `list/get`; HTTP failures are not empty feeds. A `SELF_ONLY` API publish returns no post ID; listing alone does not prove which post an ambiguous upload created.
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
