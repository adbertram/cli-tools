# Changelog

All notable changes to copilot-cli will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `copilot agent-flow runs cancel <flow-id> <run-id>` to cancel an in-progress agent flow run via the Power Automate Flow Management API. Supports `-y/--yes` to skip the interactive confirmation prompt.
- Configurable read timeout for custom connector definition writes via the `--timeout` flag on `custom-connector create`/`update` and the `COPILOT_CONNECTOR_WRITE_TIMEOUT` environment variable.

### Fixed
- `custom-connector update` no longer times out (`The read operation timed out`) on connector writes that include an OpenAPI spec plus a `--script` policy, which the server can take over a minute to apply. The write timeout now defaults to 300s (was a hard-coded 60s on the update PATCH) and is configurable. This also covers the create-with-script path, which applies its script via the same update PATCH.

## [0.1.0] - 2026-05-02

### Added
- Initial public release.
- Agent management (list, create, update, delete, publish, prompt, transcript, analytics).
- Topic management (list, create, update, delete, enable/disable).
- Tools (REST APIs, MCP servers, prompts, models).
- Custom + managed connectors.
- Connections and connection references.
- Solution management (publishers, components).
- Power Automate + agent flows.
- Environment management.
- Multi-profile authentication via Azure CLI.

[0.1.0]: https://github.com/your-org/cli-tools
