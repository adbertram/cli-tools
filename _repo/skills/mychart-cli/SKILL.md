---
name: mychart-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute Epic MyChart SMART on FHIR patient-record operations using the `mychart` CLI tool.
  Triggers: mychart, mychart cli, Epic MyChart, SMART on FHIR, FHIR patient records, list FHIR resources, get MyChart patient, clinical summary
---

<objective>
Execute Epic MyChart SMART on FHIR patient-record operations using the `mychart` CLI.
</objective>

<quick_start>
The `mychart` CLI follows this pattern:
```bash
mychart <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth | `mychart auth status` |
| Login | `mychart auth login` |
| Inspect FHIR metadata | `mychart metadata get --properties resourceType,fhirVersion` |
| List supported FHIR types | `mychart types list --table` |
| Get patient context | `mychart patient get --table` |
| List observations | `mychart resources list Observation --limit 10` |
| Get clinical summary | `mychart summary get --resource Observation --resource MedicationRequest` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `mychart` command.**
This file contains complete command syntax, arguments, options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Authentication">
`mychart` uses Epic SMART on FHIR OAuth with PKCE. A patient-facing Epic on FHIR Client ID and registered loopback redirect URI are required for patient data. Metadata, OAuth discovery, and supported type discovery can run without authentication.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication and profile management.
- **metadata** -- FHIR CapabilityStatement metadata.
- **oauth** -- SMART OAuth endpoint discovery.
- **types** -- Supported FHIR resource types.
- **resources** -- Generic FHIR resource list/get/search.
- **patient** -- Patient resource access.
- **summary** -- Grouped read-only clinical summaries.
- **cache** -- Response cache management.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error.
- Output is displayed in requested format.
- Correct command and flags used, verified against `usage.json`.
</success_criteria>
