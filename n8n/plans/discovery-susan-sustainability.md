# Discovery: Susan Long-Term Sustainability Fixes

## Codebase Context

### Key Files
- `n8n_cli/commands/server.py` — Server management: restart, upgrade, version. `_restart_n8n()` handles unload/load + readiness polling.
- `n8n_cli/commands/logs.py` — `logs_set_level()` at line 300 is the established pattern for plist env var modification via SSH + plistlib.
- `n8n_cli/n8n_api.py` — Full API client. `delete_data_table_rows()` at line 501 accepts list of row IDs. `list_data_table_rows()` at line 436 has a `limit` parameter.
- `n8n_cli/commands/data_tables.py` — `tables_delete_rows` at line 309 takes repeatable `--row-id` flags. `tables_rows` at line 185 supports `--limit` and `--filter`.
- `n8n_cli/commands/workflows.py` — `workflows_update` at line 171 handles full workflow JSON replacement.
- `n8n_cli/main.py` — Top-level Typer app. `server`, `data-tables`, `workflows`, `executions` command groups.

### Existing Patterns
- **Plist modification**: `logs set-level` (logs.py:341-358) uses SSH + `sudo python3 -c <plistlib_script>` — template for new plist commands
- **Data table row operations**: CLI has `data-tables rows`, `data-tables insert`, `data-tables delete-rows`
- **Workflow node patching**: `workflows node update` supports deep-merge patch of node parameters
- **Server restart**: `_restart_n8n()` in server.py:32 handles unload/load + readiness polling

### Live State
- **Memory table** (`m4cUmSY4VapzXha8`): 22 rows, categories: session(6), agent_gap(12), routing(1), preference(2), test(1). Columns: timestamp, category, content. Inconsistent timestamp formats.
- **Simple Memory node**: `sessionKey: "susan-session"` (static), `contextWindowLength: 10`
- **LLM**: Google Gemini Chat Model (gemini-pro-latest)
- **Read Memory node**: `limit` param driven by `$fromAI()`, defaults to 100
- **SQLite DB**: 54 MB main + 19 MB WAL = 73 MB total. `execution_data` table is 27.5 MB, `workflow_history` is 2.3 MB.
- **Execution pruning**: n8n 2.10.0 defaults to pruneData=true, 14-day age, 10k count. No plist vars set.
- **Valid plist env vars**: `EXECUTIONS_DATA_PRUNE`, `EXECUTIONS_DATA_MAX_AGE`, `EXECUTIONS_DATA_PRUNE_MAX_COUNT`, `N8N_WORKFLOW_HISTORY_PRUNE_TIME`
- **Workflow history**: 40 versions for Susan, 129 total. No history pruning configured.

## Q&A Results

### Wave: Scope
**Q:** Which fixes should we prioritize?
**A:** All 8 fixes (R1-R8)

**Q:** Implementation approach preference?
**A:** You decide — whatever makes the most sense technically

### Wave: Core Decisions
**Q:** Buffer fix approach — per-execution isolation loses cross-run Slack context. Acceptable?
**A:** "I want to ensure Susan knows about all activity up to a week old regardless of what communication channel she uses." — This means per-execution buffer isolation is fine, but the memory table must serve as the 7-day activity log that Susan reads at the start of each run.

**Q:** Memory TTL strategy?
**A:** Category-based TTLs: session: 7d, agent_gap: 30d, preference/pattern: 90d, routing: 14d

**Q:** Weekly memory summarization (R7) — include now or defer?
**A:** Include now — build the weekly summarization workflow

**Q:** LLM swap (Gemini → Claude Code Model)?
**A:** No, keep Gemini

### Wave: Technical Decisions
**Q:** Where should pruning/dedup logic live?
**A:** n8n sub-workflow — "Susan Memory Maintenance" on its own schedule

**Q:** Server restart timing for plist changes?
**A:** Restart immediately during implementation

**Q:** CLI structure for plist management?
**A:** New `server config` group — `n8n server config set <key> <value>` and `n8n server config show`

**Q:** DB monitoring approach?
**A:** Skip monitoring — pruning controls growth, react if it becomes a problem

## Key Decisions
1. All 8 fixes in scope (R1-R8), R8 (monitoring) explicitly skipped per user preference
2. Buffer window: per-execution isolation, memory table is the 7-day activity source
3. Memory pruning: category-based TTLs in an n8n sub-workflow (nightly)
4. Weekly summarization: included now as a separate n8n workflow
5. LLM stays on Gemini
6. New `server config` CLI command group for plist env var management
7. Server restarts happen immediately during implementation
8. No DB monitoring — trust pruning to control growth
