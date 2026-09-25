# Plan: Social video publishing CLI support

## Goal

Add first-class short-form video publishing support to the existing Facebook, TikTok, and YouTube CLIs without introducing browser automation where official publishing APIs exist.

## Current state

- YouTube already has authenticated OAuth upload at `youtube channel videos upload`; the new Shorts surface should delegate to that implementation.
- Facebook is browser-session-only today. Add a separate OAuth authorization-code profile type for Graph API publishing while preserving legacy browser profiles.
- TikTok currently uses browser sessions for favorites and a credential-free yt-dlp path for transcripts. Add a separate API profile type and TikTok-specific OAuth/PKCE flow for Content Posting API direct posts.

## API contracts

### YouTube
- Existing YouTube Data API `videos.insert` implementation remains authoritative.
- Add `youtube shorts upload` as a thin short-form-facing adapter over the existing channel video upload path.

### Facebook
- Add Graph API OAuth profile alongside browser-session profiles.
- Add `facebook pages list|get` for managed Page selection without exposing Page access tokens.
- Add `facebook reels publish` using create -> local binary upload -> finish.
- Add `facebook reels status`.

### TikTok
- Add API auth profile with client key/secret, redirect URI, refreshable access token, and PKCE authorization.
- Change existing yt-dlp-only commands from the old empty `custom` credential gate to `no_auth`.
- Add `tiktok videos publish` using creator-info -> init -> chunk upload.
- Add `tiktok videos status`.
- Auto-refresh expired TikTok access tokens before API calls.

## Tests first

1. Facebook: profile migration/auth-type behavior, page-token stripping, Reels create/upload/finish/status request shapes.
2. TikTok: OAuth token exchange/refresh helpers, chunk plan boundaries, publish/status request shapes, creator privacy validation, no-auth legacy commands.
3. YouTube: Shorts command delegates to the existing upload implementation with the same metadata.

## Validation

- Run each tool's focused unit suite.
- Refresh each affected `_repo/skills/<tool>-cli/usage.json`.
- Run `test-cli-tool.sh --cli-name <tool>` with zero failures when local auth/environment permits; report any live-auth blocker separately.
- Verify regenerated usage maps are stable.
