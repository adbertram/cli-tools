---
name: globiflow-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute globiflow operations using the `globiflow` CLI tool.
  CLI interface for Globiflow automation platform (browser automation) -- manage flows, steps, triggers, and search items.
  Triggers: globiflow, globiflow cli, globiflow flows, globiflow triggers, list globiflow flows, create globiflow flow, globiflow automation, globiflow steps, search globiflow
---

<objective>
Execute globiflow operations using the `globiflow` CLI. All globiflow interactions should use this CLI.
</objective>

<quick_start>
The `globiflow` CLI follows this pattern:
```bash
globiflow <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List all flows | `globiflow flows list --table` |
| Get flow details | `globiflow flows get FLOW_ID --table` |
| Create a flow | `globiflow flows create --app-id ID --trigger C --name "Name"` |
| View flow logs | `globiflow flows logs FLOW_ID --table` |
| List flow steps | `globiflow flows steps list --flow-id FLOW_ID --table` |
| Add a step to a flow | `globiflow flows steps add FLOW_ID --action "Add Comment" --comment "text"` |
| Add a field-less logic step | `globiflow flows steps add FLOW_ID --action "End If"` |
| Add a collector step (extra params) | `globiflow flows steps add FLOW_ID --action "Get Referenced Item(s)" --params '{"app": "Topics", "direction": "FORWARD"}'` |
| Add a trigger-condition filter step | `globiflow flows steps add FLOW_ID --action "Field Changed" --params '{"field": "Status"}'` (requires an Item Updated trigger) |
| Export a flow's XML | `globiflow flows export FLOW_ID --output flow-<id>.xml` |
| Import a flow XML | `globiflow flows import --app-id ID --file flow-<id>.xml` |
| List trigger types | `globiflow triggers list --table` |
| Search items | `globiflow search query "keyword" --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `globiflow` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Flow Import Requires A Field-Compatible Target App">
`flows import` carries the source app's Podio field references into the target app. Globiflow re-binds only the references it can match there, and its flow editor refuses to save while any reference is unmatched, so an import lands only in an app whose fields cover every field the flow uses -- a schema clone of the source app, in the same org or another one. Importing into an app with a different schema fails with the unmatched step and control named; recreate that flow with `flows create` / `flows steps add` instead.
</principle>

<principle name="Relationship Fields In --fields Are Runtime Search Criteria, Not IDs">
A Podio app/relationship field in `--fields` is set by the target item's title (`{"Format": "Blog Post"}`), never a raw Podio item ID. Globiflow has no title-to-item resolver at configure time -- it builds a search criterion (target app + field + "Equal to" + value) that it evaluates when the flow actually runs, so this CLI cannot pre-check whether that title matches zero, one, or many items; that is Globiflow's own runtime behavior.

Globiflow's target-app picker for that search is a per-Podio-app cache, NOT scoped to the field you picked -- an app with several relationship fields pointing at different targets (e.g. one app with Format/Content/Contacts fields) offers every one of those target apps for any of them, and this CLI refuses to guess. If the picker has more than one candidate, pass a dict instead: `{"app": "Content Formats", "value": "Blog Post"}` -- a plain string raises `ClientError` listing the real candidates by name. A picker with zero candidates means that app's Globiflow field cache is stale; refresh it via "Refresh from Podio" on that app's flows.php page and retry.

A list value (`{"Related Content": ["Blog Post", "Whitepaper"]}`) expands into one search row per item, for setting a multi-value relationship field to more than one item. A `null` value unsets any field (relationship or otherwise) via Globiflow's "Unset" function instead of setting one.
</principle>

<principle name="Multi-Step --steps Chains Only Reference-Resolve After The First Step">
`flows create --steps` with 2+ steps adds only the first step in-page, saves, then adds every remaining step via a fresh reload against the now-saved flow -- so a step referencing a variable an earlier step in the same call creates (`[(Variable) myvar1]`) resolves correctly. This is transparent to the caller; it just means a multi-step create makes multiple round-trips, one per step after the first.
</principle>

<principle name="Field-Less Step Types Take No Other Options">
"End If" (closes an "If (Sanity Check)" block) and "Continue" (ends a "For Each" loop early) render no configurable fields in Globiflow's UI at all -- `globiflow flows steps add FLOW_ID --action "End If"` with no other flags.
</principle>

<principle name="--params Is The Escape Hatch For Collector/Filter Parameters">
`steps add --params '{"key": "value", ...}'` merges arbitrary parameters into the step, the same JSON-object convention as `--fields`. Use it for:
- **"Get Referenced Item(s)" collector**: `app` (required, matched by trailing "Org > Space > App" segment like the Create Item app picker), `direction` (`FORWARD`/`REVERSE`/`BOTH`), `using_field` (optional, needs `direction` set first; its value is the picker's exact option text `"(ItemName) FieldLabel"` -- `ItemName` is the CURRENT app's singular item-name config, not its app name -- read an existing step's `using_field` via `flows steps list` to get the exact string for that app).
- **Filter steps' target field**: `{"field": "<Podio field label>"}` for "Field Changed". Only "Field Changed" and "Custom Filter" (which uses `--code`, not `--params`) have their fields fully wired; other filter types (Field Value Match, Date Match, etc.) add as a step type but fail loudly on save if this CLI hasn't filled a required control it doesn't yet support (an operator/match-value picker) -- that failure names the exact unfilled control, it is never a silent no-op.
</principle>

<principle name="Field Changed Requires An Item Updated Trigger">
"Field Changed" is Globiflow's own validation-gated to trigger `U` (Item Updated) -- adding it to a flow with any other trigger fails the save. Trigger-condition filter steps (Field Changed, Custom Filter, etc.) live in a separate section of Globiflow's editor from action/logic/collector steps and gate the whole flow before any action runs; `flows steps list`/`flows steps get` do not yet surface them (a known gap) -- use `flows export` and inspect the raw XML to confirm what a filter step actually saved.
</principle>

<principle name="Command Groups">
- **auth** -- Browser-based authentication (login, status, test, logout)
- **search** -- Search and browse Globiflow items (query, item, list)
- **flows** -- Manage automation flows (list, create, get, logs, delete, export, import, steps)
- **triggers** -- View available trigger types for flow creation (list, get)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
