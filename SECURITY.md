# Security Policy

## Reporting a Vulnerability

Please report suspected vulnerabilities privately through the repository's
GitHub security advisory flow when available. If security advisories are not
enabled on the published repository, open a minimal issue that says a private
security report is needed and avoid posting exploit details, credentials,
tokens, cookies, or session data.

## Credential Handling

Do not commit credentials or runtime auth state. This includes `.env` files,
browser profiles, cookies, `session.json`, `.auth-state.json`, Playwright
captures, OAuth token caches, API keys, passwords, and generated logs.

Service credentials should live in the user's local profile or keychain-backed
storage. Browser-backed tools should keep authenticated profile data outside
the source tree.

## Public Release Checks

Before publishing or cutting a release, scan both the working tree and Git
history for secrets, then verify no runtime auth artifacts are tracked.
