# Hermes with a Locally Authenticated Coding CLI

Use this reference when Hermes should run a local coding CLI as its primary model process or as a delegated worker without copying the CLI's OAuth credential into Hermes.

## Keep the two paths distinct

- **CLI-backed provider:** Hermes launches the local executable. Authentication and subscription usage belong to that CLI.
- **Direct vendor provider:** Hermes calls the vendor API itself. Vendor API-key, OAuth, billing, and plan rules apply.

A provider name is not proof of the execution path. Verify the actual boundary before changing global configuration.

## Safe configuration sequence

1. Verify the local CLI reports authenticated status.
2. Run the smallest harmless live CLI request. Cached authentication metadata alone is insufficient.
3. Run an explicit fresh-process Hermes smoke with the intended provider and model. For Claude Code, the provider must resolve to the dedicated external-process client rather than normalize to direct `anthropic` routing.
4. Only after the explicit smoke passes, set the global provider/model with supported `hermes config set` commands.
5. Run a second fresh-process smoke without a provider override to prove configured-default resolution.
6. Restart long-lived gateway processes only after active work drains, then verify the supervisor reports the gateway running.

## Routing failure diagnostic

If an explicit local-CLI provider request returns vendor API billing, extra-usage, or API-credential guidance, the request crossed the direct API boundary. Do not add an API key as a workaround. Trace provider normalization, aliases, provider profiles, and client construction; make the local-CLI provider identity distinct and add regression coverage that preserves that identity end to end.

For Claude Code, preserve `claude` as the direct Anthropic alias when supported, while `claude-code` selects the local external-process client.

## Deferred gateway restart

A gateway should not depend on its own process tree to complete its restart. Use an independent supervisor job that:

1. Verifies the gateway launchd plist path and PATH dependencies.
2. Polls the canonical cron job store for `state == "running"`.
3. Requires a short stable idle window and rechecks before restarting.
4. Unloads and reloads the verified gateway plist.
5. Verifies the launchd service is running and writes a durable status artifact.

On macOS, `launchctl submit` can register a submitted job with keepalive behavior. The watcher must remove its own submitted label after success or failure so it cannot repeat the restart.

For a script-only Hermes cron notifier, place the script under `~/.hermes/scripts/` and pass a relative path such as `notify.py`. Absolute and `~`-prefixed script paths are rejected at the cron tool boundary.
