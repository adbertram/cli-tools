# Quick Plan: n8n test

## Summary
Create `n8n test` command that tests generated n8n nodes by creating a temporary workflow with user-specified resource/operation, executing it via SSH (`n8n execute`), polling for execution result, asserting success status, and printing JSON summary. Delete workflow on success, keep on failure for debugging.

## Why This Approach
Simplest end-to-end test without mocking - use n8n's native execution CLI via SSH, leverage existing n8n REST API for workflow CRUD and execution polling. No complex test harness needed - just workflow lifecycle + SSH execution + status assertion.

## Prerequisites
- n8n server running at `http://100.117.198.37:5678`
- n8n API key in `~/.claude/skills/n8n/.env` (N8N_API_KEY)
- SSH access to adam-server configured (already working)
- Generated n8n node already installed on n8n server (user's responsibility)

## Implementation Steps

### Step 1: Create n8n API client module
**File:** `<cli-tools-root>/n8n/n8n_cli/n8n_api.py`
**Action:** Create API client class with methods for:
- `create_workflow(name, nodes, connections)` - POST /workflows
- `delete_workflow(workflow_id)` - DELETE /workflows/{id}
- `get_executions(workflow_id)` - GET /executions?workflowId={id}&includeData=true
- Load API key from `~/.claude/skills/n8n/.env` (N8N_API_KEY)
- Base URL: `http://100.117.198.37:5678/api/v1`
**Pattern:** Follow `client.py` error handling (ClientError exceptions)
**Verify:** Import in Python REPL, instantiate client

### Step 2: Create test command module
**File:** `<cli-tools-root>/n8n/n8n_cli/commands/test.py`
**Action:** Create typer command `test_node()` with parameters:
- `node_name: str` (argument) - e.g. "brickowl"
- `--resource: str` (required) - e.g. "order"
- `--operation: str` (required) - e.g. "list"
- `--timeout: int` (default 60) - execution timeout in seconds
**Pattern:** Follow `convert.py` command structure
**Verify:** Run `n8n test --help`

### Step 3: Implement workflow creation logic
**File:** `<cli-tools-root>/n8n/n8n_cli/commands/test.py`
**Action:** In `test_node()` function:
- Build workflow JSON with single node: type=`n8n-nodes-{node_name}.{node_name}`, parameters={resource, operation}
- Call `n8n_api.create_workflow()` to create temporary workflow
- Store returned workflow ID
**Pattern:** n8n workflow structure from api-reference.md lines 71-106
**Verify:** Check workflow exists in n8n UI after creation

### Step 4: Implement SSH execution + polling
**File:** `<cli-tools-root>/n8n/n8n_cli/commands/test.py`
**Action:** Add execution logic:
- Execute: `subprocess.run(['ssh', 'adam-server', f'n8n execute --id {workflow_id}'])`
- Poll: Loop GET /executions?workflowId={workflow_id} every 2s until execution.finished=true or timeout
- Extract: execution ID, status, duration, output data
**Timeout:** Use --timeout flag with time.time() check in polling loop
**Verify:** Run command, observe polling output

### Step 5: Implement assertion + cleanup
**File:** `<cli-tools-root>/n8n/n8n_cli/commands/test.py`
**Action:** Add assertion and cleanup:
- Assert: `execution.status == 'success'`, raise error if not
- Print JSON: `{workflowId, executionId, status, duration, output}` using `print_json()`
- Cleanup: If success → delete workflow, if failure → keep workflow and print "Workflow preserved for debugging: {id}"
**Pattern:** Use `output.print_json()` from existing code
**Verify:** Run successful test (sees deletion), run failing test (sees preserved workflow)

### Step 6: Register command in main.py
**File:** `<cli-tools-root>/n8n/n8n_cli/main.py`
**Action:** Add imports and registration:
- Import: `from .commands import test`
- Register: `app.command("test")(test.test_node)`
**Pattern:** Follow existing `app.command("convert-cli-tool")` pattern
**Verify:** Run `n8n test --help` and see full command docs

## Testing Strategy
**Manual test:**
```bash
# Assumes brickowl node already installed on n8n server
n8n test brickowl --resource order --operation list --timeout 30
```

**Expected output:**
```json
{
  "workflowId": "123",
  "executionId": "456",
  "status": "success",
  "duration": 2.5,
  "output": {...}
}
```

**Verify:**
- Workflow created in n8n
- SSH execution triggered
- Execution polled until completion
- Status asserted
- Workflow deleted on success

## What's NOT Included
- Multiple node testing (single node only)
- Input data injection (no parameters beyond resource/operation)
- Credential management (assumes credentials already configured on n8n server)
- Parallel execution (one workflow at a time)
- Test result persistence (ephemeral JSON output only)

## Success Criteria
- [ ] Command `n8n test <node> --resource <r> --operation <o>` executes
- [ ] Workflow created via n8n API
- [ ] Execution triggered via SSH
- [ ] Execution polled until completion
- [ ] Status 'success' assertion passes
- [ ] JSON summary printed
- [ ] Workflow deleted on success, preserved on failure
