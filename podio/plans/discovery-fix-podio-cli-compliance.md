# Discovery: Fix Podio CLI Compliance Issues

## Codebase Context

### Key Files

**Command Files:**
- `podio_cli/commands/item.py` - Has list command with required APP_ID positional arg (line 88-90)
- `podio_cli/commands/app.py` - Has field list command with required APP_ID positional arg, list command has optional space_id
- `podio_cli/commands/comment.py` - Has list command with required REF_TYPE, REF_ID positional args
- `podio_cli/commands/webhook.py` - Has list command with required HOOKABLE_TYPE, HOOKABLE_ID positional args; field list with required FIELD_ID
- `podio_cli/commands/webform.py` - Has list command with required APP_ID positional arg; field list with required FORM_ID_OR_URL
- `podio_cli/commands/task.py` - Has list command with no required args; label list command exists
- `podio_cli/commands/file.py` - Has get command (line 92-95) but NO list command
- `podio_cli/commands/conversation.py` - Has list and get commands

**Core Files:**
- `podio_cli/output.py` - Has max_columns = 7 at line 151 (user says ignore this)
- `podio_cli/main.py` - Main CLI entry point
- `pyproject.toml` - Specifies requires-python = ">=3.8" (line 10), should be ">=3.14" per standards

**Filtering Pattern:**
- Multiple command files have their own `_apply_client_filter()` functions with basic field:op:value parsing
- Other CLIs (kick, tasks) use a centralized `filters.py` module with comprehensive filter validation and application
- No `filters.py` or `filter_translator.py` exists in podio_cli

### Existing Patterns

**List Command Pattern (from item.py:88-112):**
- Takes optional `--filter`, `--limit`, `--properties` flags
- APP_ID is a required positional argument (but user decided to change test to warn, not fail)
- Has client-side filtering logic inline

**Filter Implementation (from task.py:29-71):**
- Custom `_apply_client_filter()` function in each command file
- Supports field:value and field:op:value syntax
- Operators: eq, ne, contains, gt, lt
- No validation or error handling for invalid filters

**Get/List Relationship:**
- Most groups have both get and list commands
- File group has get but no list command (needs to be added)

### Integration Points

- All command files in `podio_cli/commands/` directory
- Output module at `podio_cli/output.py`
- No existing filters or filter_translator modules
- Each command file currently has duplicate filtering logic

---

## Q&A Results

### Wave: Clarify Task

**Q:** I see `podio item list` requires APP_ID as a positional argument (item.py:90). Should I convert this to an optional --app-id flag, or can users provide it via environment variable PODIO_APP_ID?
**A:** podio item list should return all items from all apps by default

**Q:** The test mentions 'podio app field list' requires APP_ID. Should nested list commands (like field list under app) also support the parent ID via flag/env, or only top-level list commands?
**A:** all list commands should have an --app-id parameter to filter by app but if not provided, should return all resources in ALL apps

**Q:** I found `_apply_client_filter()` duplicated in task.py, app.py, webform.py, conversation.py, and comment.py with slightly different implementations. Should I create a centralized filters.py module like kick CLI has?
**A:** look at how the cli-tools/_repo/skills/cli-tool/templates/api does it and replicate its filtering

**Q:** The test expects filter_translator.py but other CLIs use filters.py. Should I create filter_translator.py (which translates CLI filters to API filters), filters.py (which does client-side filtering), or both?
**A:** find the cli-tools/_repo/skills/cli-tool/templates/api template and use that approach

### Wave: Technical Decisions

**Q:** Looking at kick/filters.py, it supports operators: eq, ne, gt, gte, lt, lte, in, nin, like, ilike, null, notnull. Should podio use this same operator set?
**A:** use all operators the cli standards require

**Q:** Task list command hits API error 'Query not restrictive enough' when called with just --limit 1. Should I add required filters, or handle this gracefully with a better error message?
**A:** Default filter - Add default --completed=false when no filters provided

**Q:** File group has 'podio file get' but no list command (test_groups_with_get_must_have_list fails). Should I add a list command, or is there a reason files shouldn't be listed?
**A:** Add file list - Create list command that lists files (need API endpoint)

**Q:** Some list commands (app field list, webhook field list) don't have --limit flag. Should all list commands have --limit, even if they return small result sets?
**A:** All list commands - Add --limit to every list command for consistency

### Wave: Scope & Standards

**Q:** The test expects filter help text to describe 'field:op:value syntax'. Should this go in the global --filter help text, or in a separate --help-filters flag?
**A:** In --filter help - Expand --filter help to show syntax and operators

**Q:** output.py has max_columns = 7 (line 151) but test expects 6. Should I just change this value, or is there a reason for 7 columns?
**A:** ignore (skip this fix)

**Q:** pyproject.toml requires Python >=3.8 but test expects >=3.14. Should I update to 3.14, and will this break compatibility for existing users?
**A:** Update to 3.14 - Match standard, accept breaking change

**Q:** When converting positional args to optional flags, some commands may need the parent ID. Should I use the pattern from space.py where it falls back to env var (PODIO_WORKSPACE_ID)?
**A:** no fall backs. I need to see an example

### Wave: Implementation Approach

**Q:** I see task.py imports filter functions but doesn't use filter_translator (test #7-8 fail). Should task.py be updated to use the new filter system, or is task filtering different?
**A:** Use filter_translator - Task.py should import and use standard filter translator

**Q:** The test checks that command files import filter_translator. Should every command file that has a list command import this, even if they don't currently use client-side filtering?
**A:** All list commands - Import filter_translator in every file with list command

**Q:** Looking at the existing _apply_properties_filter() pattern, should this also move to the filters.py module, or keep it separate since it's not filter logic?
**A:** Move to filters - Include in filters.py as apply_properties()

**Q:** Webhook list and comment list require ref_type and ref_id (e.g., 'item 12345'). If I make these optional, how should the commands work without them?
**A:** List all webhooks - No args = list all webhooks across all resources

### Wave: Edge Cases

**Q:** The Podio API has different filter capabilities per endpoint. Should filter_translator.py translate to API filters when available, or always do client-side filtering?
**A:** API when available - Detect API filter support, translate if possible

**Q:** What should happen when a filter uses an invalid operator or field name? Current implementation silently skips invalid filters.
**A:** Raise error - Validate filters upfront, error on invalid syntax

**Q:** After making list commands accept optional flags, should I add default values or require at least one identifying parameter?
**A:** list everything - No required params, list all available resources

**Q:** The test checks that nested groups (like 'app field') have both list and get. Currently app field has both. Should I verify all nested groups or are there exceptions?
**A:** All nested groups - Every nested group must have get and list

### Wave: Risk Assessment

**Q:** Making APP_ID optional in 'podio item list' could break existing scripts. Should I maintain backward compatibility or accept the breaking change?
**A:** **CRITICAL CHANGE OF DIRECTION:** Instead of changing Podio, change the test. Make the test a warning; not a failure. If you can't do a warning natively with pytest, let me know

**Q:** If I add filter_translator.py and filters.py, should existing _apply_client_filter() functions be removed or kept as fallback?
**A:** Remove old code - Delete all _apply_client_filter() functions

**Q:** Changing Python requirement from 3.8 to 3.14 could affect users on older systems. Should I check for Python 3.14-specific features needed, or just update the requirement?
**A:** Update requirement only - Change version, code likely works on 3.14

### Wave: Implementation Preferences

**Q:** Looking at filter examples in kick CLI, should Podio's filter help text include examples like '--filter status:active' or be more general?
**A:** Specific examples - Show real field names like 'status:active'

---

## Key Decisions

1. **Positional Arguments Issue**: Instead of changing Podio CLI, modify the pytest test to emit a warning instead of failure for required positional arguments
2. **Filter System**: Use the cli-tools/_repo/skills/cli-tool/templates/api template approach for filters.py and filter_translator.py
3. **Filter Operators**: Use all operators that CLI standards require
4. **Task List API Error**: Add default --completed=false filter when no filters provided
5. **File List Command**: Add new file list command to satisfy get/list pairing requirement
6. **All List Commands**: Must have --limit, --filter, --properties flags
7. **Filter Import**: All command files with list commands must import filter_translator
8. **Properties Filter**: Move _apply_properties_filter() to filters.py module
9. **Remove Duplicates**: Delete all existing _apply_client_filter() functions after centralizing
10. **Invalid Filters**: Raise error on invalid filter syntax (strict validation)
11. **Python Version**: Update pyproject.toml to require >=3.14
12. **max_columns**: Skip this fix (user said ignore)
13. **Nested Groups**: All nested groups must have both get and list commands
