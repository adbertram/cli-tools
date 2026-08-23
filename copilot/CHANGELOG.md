# Changelog

All notable changes to copilot-cli will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `copilot agent-flow runs cancel <flow-id> <run-id>` to cancel an in-progress agent flow run via the Power Automate Flow Management API. Supports `-y/--yes` to skip the interactive confirmation prompt.
- Configurable read timeout for custom connector definition writes via the `--timeout` flag on `custom-connector create`/`update` and the `COPILOT_CONNECTOR_WRITE_TIMEOUT` environment variable.
- `copilot agent-flow publish <flow-id>` promotes a flow's unpublished (draft) definition to the published definition through the Dataverse `PublishXml` action. This is the publish layer, not the `enable`/`disable` activation state.
- `agent-flow import` gained `--discard-draft` and `--publish`. `--discard-draft` publishes an existing unpublished draft to clear the Dataverse `ActiveUnpublished` state and immediately overwrites it with the imported definition. `--publish` publishes the flow after a successful import.

### Fixed
- `agent-flow import` no longer leaks the raw Dataverse solution-layer HTTP 400 (`You are attempting to do a published update of publishable component in an unmodified active context when there exists an unpublished active row ... Component Type: 29 ... CurrentState=ActiveUnpublished`) when the flow has a draft saved from the Power Automate or Copilot Studio web designer. The command now reads the flow's publish state before it writes and refuses with a message that names the cause, the evidence, and the two remedies. `--dry-run` reports the publish state too.
- `agent-flow export --draft` no longer returns the PUBLISHED definition labeled `version: draft`. The draft is read through the Dataverse `RetrieveUnpublished` function, which returns different data from a plain read only when the record was updated but not published. When no unpublished draft exists, `--draft` fails instead of mislabeling published content, and a published export prints a stderr note when a draft is pending. Previously `--draft` derived the label from the workflow `type` column, so every agent flow (`type=1`) was labeled `draft` regardless of content.
- `connections <id> operations invoke` no longer exits with a bare `Error: 'name'` when a connector swagger expresses a parameter as a local `$ref`. Swagger 2.0 shared parameters such as `{"$ref": "#/parameters/DynamicApprovalType"}` are now resolved against the swagger's `parameters` section by `list`, `get`, and `invoke` alike. The `shared_approvals` connector uses 16 of them, including the required `approvalType` path parameter, which had been dropped from the request URL. An unresolvable reference or a genuinely nameless parameter now fails with the operation id, parameter index, pointer, and available keys.
- New `connections-parameter` validation rule. A flow definition that uses connector operations (or declares connection references) must declare `definition.parameters.$connections` with `type: Object` and `defaultValue: {}`. `agent-flow validate`, `agent-flow create`, and `agent-flow import` now reject the definition with an error naming the missing parameter and its required shape. Previously validation reported `Errors: 0`, `create` wrote the flow row to Dataverse, and the failure only surfaced at `agent-flow enable` as `HTTP 400 InvalidPowerFlow: The provided flow definition with a recurrent trigger is missing the required parameter '$connections'.`
- `agent-flow validate`, `agent-flow create`, and `agent-flow import` now apply the connection-reference and undefined-parameter rules to every connector-backed operation. Both rules previously inspected only top-level `definition.actions` entries whose type was exactly `OpenApiConnection`. They now walk nested `Scope`, `If`/`else`, `Foreach`, `Switch` (cases and default), and `Until` containers, cover all six connector operation types (`OpenApiConnection`, `OpenApiConnectionWebhook`, `OpenApiConnectionNotification`, `ApiConnection`, `ApiConnectionWebhook`, `ApiConnectionNotification`), and cover connector-backed triggers. Across 31 live PSDXAutomation exports this raised coverage from 64 to 261 connector operations.
- The undefined-parameter rule no longer warns about connector request-body parameters (`body` and `body/<field>`). Those hold per-app field values and cannot be enumerated, so `body/fields` and `body/file_ids` produced false warnings on working flows.
- `custom-connector update` no longer times out (`The read operation timed out`) on connector writes that include an OpenAPI spec plus a `--script` policy, which the server can take over a minute to apply. The write timeout now defaults to 300s (was a hard-coded 60s on the update PATCH) and is configurable. This also covers the create-with-script path, which applies its script via the same update PATCH.
- `get_access_token()` and `Config.get_auth_method()` now correctly prefer service-principal (MSAL client-credentials) auth over Azure CLI delegated auth when a profile has fully opted in (`AZURE_TENANT_ID` + `AZURE_CLIENT_ID` + `AZURE_CLIENT_SECRET` all set). Previously `get_auth_method()` checked `has_cli_auth()` (satisfied by `DATAVERSE_URL` alone) before `has_service_principal_auth()`, so the service-principal branch was unreachable and every Dataverse Web API command silently used `az login` even on profiles with full service-principal credentials configured. This closes the gap that caused recurring `AADSTS70043` (conditional-access sign-in-frequency) failures on unattended profiles, since service principals are not subject to interactive user sign-in-frequency policies. See `docs/auth.md` § Service Principal (Non-Interactive) Authentication for setup (requires a Dataverse Application User bound to the app registration).

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
