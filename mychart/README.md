# MyChart CLI

## DESCRIPTION

The `mychart` CLI provides command-line access to Epic MyChart SMART on FHIR patient record.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
cd <cli-tools-root>/mychart
uv tool install -e . --force --refresh
```

## Quick Start

```bash
mychart metadata list --properties id,resourceType,fhirVersion
mychart oauth list
mychart types list --filter "type:eq:Observation" --table
mychart auth login
mychart patient get --table
mychart resources list Observation --limit 10 --filter "status:eq:final"
mychart summary get --resource Observation --resource MedicationRequest
```

## Commands

### Authentication

```bash
mychart auth login
mychart auth login --force
mychart auth status
mychart auth test
mychart auth refresh
mychart auth logout
```

`auth login` uses Epic SMART on FHIR authorization-code OAuth with PKCE. It prompts for the Epic on FHIR Client ID and a registered loopback redirect URI, opens the authorization URL, captures the localhost callback, then saves the returned access token, refresh token, and patient context.

### Profiles

```bash
mychart auth profiles list
mychart auth profiles get default
mychart auth profiles create PROFILE_NAME
mychart auth profiles select PROFILE_NAME
mychart auth profiles delete PROFILE_NAME
```

### Metadata

```bash
mychart metadata get
mychart metadata get capability-statement
mychart metadata get --properties resourceType,fhirVersion
mychart metadata get --table
mychart metadata list
mychart metadata list --properties id,resourceType,fhirVersion
```

Returns the FHIR CapabilityStatement advertised by the configured Epic FHIR base URL. This command does not require authentication.

### OAuth Discovery

```bash
mychart oauth get
mychart oauth get authorize
mychart oauth get --table
mychart oauth list
mychart oauth list --table
```

Returns SMART OAuth endpoints advertised by the FHIR CapabilityStatement. This command does not require authentication.

### Resource Types

```bash
mychart types list --limit 25
mychart types list --filter "type:eq:Observation" --properties "type,search_params"
mychart types list --table
mychart types get Observation
mychart types get Patient --table
```

Lists or inspects FHIR resource types supported by the configured server.

### Resources

```bash
mychart resources list Observation --limit 10
mychart resources list Observation --patient-id PATIENT_ID --filter "status:eq:final"
mychart resources list MedicationRequest --filter "status:eq:active" --properties "resourceType,id,status"
mychart resources get Observation OBSERVATION_ID
mychart resources get Patient PATIENT_ID --table
mychart resources search Observation "hemoglobin" --limit 5
```

`resources list` maps `--limit` to FHIR `_count` and maps `--filter` to server-side FHIR search parameters.

Supported filter operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`.

### Patient

```bash
mychart patient get
mychart patient get PATIENT_ID
mychart patient get --properties "resourceType,id,name"
mychart patient get --table
mychart patient list
mychart patient list --filter "name:eq:Camila Lopez"
mychart patient list --limit 5 --table
```

Gets the saved token patient by default, or a specific Patient resource ID. Without authentication, `patient list` and `patient get <id>` return the public Epic sandbox test-patient catalog, excluding published passwords.

### Summary

```bash
mychart summary get
mychart summary get --patient-id PATIENT_ID
mychart summary get --resource Observation --resource MedicationRequest
mychart summary get --limit-per-resource 5
```

Returns a grouped read-only summary for common patient resources. If a resource type is unavailable for the configured server/account, its error is returned under `errors`.

### Cache

```bash
mychart cache clear
mychart --no-cache metadata get
mychart --no-cache resources list Observation --limit 10
```

## Output Formats

JSON is the default output format. Add `--table` / `-t` for table output.

List commands return arrays. Get commands return one object. FHIR JSON fields are preserved in JSON output.

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results for list/search commands |
| `--filter` | `-f` | Server-side FHIR search filter using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--patient-id` |  | Override the saved token patient context |
| `--resource` | `-r` | Include a resource type in `summary get`; repeatable |
| `--version` | `-v` | Show version and exit |
| `--no-cache` |  | Bypass cached read responses for this execution |

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/mychart/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/mychart/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. Do not put reusable credentials in any `.env` file. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
BASE_URL=https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4
FHIR_SCOPES=launch/patient openid fhirUser offline_access patient/Patient.read patient/Observation.read
CACHE_ENABLED=true
CACHE_TTL=3600
```

Authentication profile variables:

```bash
ACTIVE=true
CLIENT_ID=<epic_public_client_id>
REDIRECT_URI=http://localhost:8765/callback
ACCESS_TOKEN=<access_token_written_by_cli>
REFRESH_TOKEN=<refresh_token_written_by_cli>
TOKEN_EXPIRES_AT=<epoch_seconds_written_by_cli>
PATIENT_ID=<patient_id_written_by_cli>
GRANTED_SCOPES=<scope_string_written_by_cli>
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/config/authentication error |
| 130 | User interrupted |

## Requirements

- Python 3.11+
- `typer`
- `python-dotenv`
- `requests`
- `cli-tools-shared`

## License

MIT
