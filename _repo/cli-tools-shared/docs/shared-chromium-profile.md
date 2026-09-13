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

There is no silent migration from old per-tool Chromium directories. Silent selection or merging of cookie databases is unsafe. Existing directories remain untouched and can be restored. To seed the shared profile, choose one known-good `default` browser profile while Chrome is fully closed, copy it to the shared path, then retain the source as a backup until every CLI is verified. Do not merge multiple Chrome profile trees.

Adam's Mac already has a seeded shared directory and per-tool symlinks from the earlier experiment. Once this feature is active, the symlinks are not required for path resolution; they may remain temporarily as compatibility pointers while validation runs.

## Validation

Run:

```bash
cd _repo/cli-tools-shared
env -u PYTHONPATH UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/cli-tools-shared-tests uv run pytest
```

The shared-profile tests cover default sharing, named-profile isolation, environment overrides, non-browser configs, saved-session detection, per-tool clear safety, and explicit shared reset.
