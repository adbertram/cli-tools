# Shared Chromium profile

Browser-session CLIs on the `default` authentication profile share one Chromium user-data-dir:

```text
~/.local/share/cli-tools/_shared/chromium-profile
```

This lets Google/SSO and domain cookies persist once across normal browser CLIs. `BaseConfig.get_persistent_profile_dir()` owns the decision; CLI implementations and the browser template require no per-tool path code.

## Isolation rules

A browser CLI uses a per-tool profile instead when any of these is true:

- the active authentication profile is named anything other than `default` (multi-account identities must not merge);
- `CLI_TOOLS_ISOLATE_CHROME_PROFILE=1` is set;
- the config does not declare `CredentialType.BROWSER_SESSION`.

Override the shared location with `CLI_TOOLS_SHARED_CHROME_PROFILE=/path/to/profile`.

## Concurrency

Chrome permits one live process per user-data-dir. Browser CLIs using the shared profile must run sequentially. Existing profile-process and lifecycle-lock checks fail fast rather than corrupting the directory. Use an isolated named profile or `CLI_TOOLS_ISOLATE_CHROME_PROFILE=1` when concurrent Chrome processes are required.

## Logout and reset

A per-tool `auth login --force` / `clear_session()` must not delete the shared profile, because that would sign every CLI out of Google/SSO. It closes that CLI's browser and clears tool-local `browser-data/` only.

An intentional global reset uses `BaseConfig.clear_shared_chromium_profile()`. This deletes the shared user-data-dir for all browser CLIs.

## Existing installations

There is no silent migration from old per-tool Chromium directories. Silent selection or merging of cookie databases is unsafe. Existing directories remain untouched and can be restored.

If the shared profile is empty but an isolated/default profile is known-good, seed exactly one source with that CLI's deterministic command:

```bash
<known-good-cli> auth seed-shared-chromium-profile
```

For example, after confirming BrickLink's isolated profile still works:

```bash
CLI_TOOLS_ISOLATE_CHROME_PROFILE=1 bricklink auth status
bricklink auth seed-shared-chromium-profile
```

The command requires the `default` profile, verifies the source has a Chromium Cookies database, refuses a populated destination, refuses running Chrome processes, and excludes stale Chromium singleton artifacts. It never merges or overwrites profile trees. Re-login every other browser CLI into the newly seeded shared profile as needed.

Adam's Mac already has a seeded shared directory and per-tool symlinks from the earlier experiment. Once this feature is active, the symlinks are not required for path resolution; they may remain temporarily as compatibility pointers while validation runs.

## Per-host rollout check

Run this check on every host that executes browser-backed CLI workflows before removing a temporary `CLI_TOOLS_ISOLATE_CHROME_PROFILE=1` workaround:

```bash
<browser-cli> auth status
```

When `credential_types.browser_session.browser_error` says the shared Chromium profile is not seeded, identify one CLI whose isolated/default profile is still valid, run its `auth seed-shared-chromium-profile` command while Chrome is closed, then rerun `auth status`. Do not seed from an expired profile. A browser session can be re-authenticated after seeding, but the command must never be used to merge multiple profiles.

## Portable named sessions

Services that declare `browser_session_origins()`,
`browser_session_cookie_domains()`, and `browser_session_identity(browser)`
support explicit named-session transfer. The identity hook returns only string
`account_id` and `username` fields using the provided browser. Default/shared
profiles and non-browser authentication profiles are refused.

```bash
tiktok auth session-export --profile clipper --expected-account-id 7692213003349443597 --expected-username ata_clipper --output "$HOME/.local/share/cli-tools/tiktok/session-transfers/clipper.json"
tiktok auth session-import --profile clipper --expected-account-id 7692213003349443597 --expected-username ata_clipper --stdin < "$HOME/.local/share/cli-tools/tiktok/session-transfers/clipper.json"
tiktok auth session-import-recover --profile clipper
```

Export files must be new files in a private CLI runtime directory. The format
contains only service-scoped cookies and exact-origin localStorage, is capped
at 16 MiB, and never includes `.env` credentials, IdP sessions, Chrome databases,
or keychain material. Cookies+localStorage may still require device verification
on another host; only live exact-account verification proves portability.

Import requires an absent destination and macOS exclusive rename support.
Required root configuration must already exist. It creates an inactive private
staging profile before Config construction, restores and checks persistence,
closes Chrome, publishes without overwriting any concurrent destination, then
verifies the final profile. No imported profile is automatically activated.
Failure retains private stage, bundle, and journal. A subsequent import refuses
an unfinished journal until `session-import-recover` checks ownership and that
Chrome is closed. Recovery quarantines a failed owned publication and archives
its journal while retaining its backup. A durable complete journal instead
finishes cleanup and preserves the already verified published profile.

## Validation

Run:

```bash
cd _repo/cli-tools-shared
env -u PYTHONPATH UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/cli-tools-shared-tests uv run pytest
```

The shared-profile tests cover default sharing, named-profile isolation, environment overrides, non-browser configs, saved-session detection, per-tool clear safety, and explicit shared reset.
