# Changelog

All notable changes to copilot-cli will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `copilot agent-flow runs cancel <flow-id> <run-id>` to cancel an in-progress agent flow run via the Power Automate Flow Management API. Supports `-y/--yes` to skip the interactive confirmation prompt.

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
