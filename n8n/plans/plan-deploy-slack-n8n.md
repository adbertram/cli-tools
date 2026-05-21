# Implementation Plan: Deploy Slack CLI to n8n & Create Slack Reminders AI Tool

## Summary

The Slack CLI has a broken token (xoxp stored, but the saved.list API requires xoxc) and the reminders command group was removed from main.py. This plan re-adds reminders, fixes auth via browser re-login to capture xoxc, regenerates the n8n node package, deploys it to the server, then adds a scoped "Get Slack Reminders" AI tool node to the Susan workflow.

## Why This Approach

- Re-auth via `slack auth login --force` is the correct fix: browser.py already extracts xoxc from localStorage, so running it again after removing the stale xoxp will give the right token type.
- Regenerating with `--force` is simpler than patching the existing TypeScript — the generator is the source of truth.
- Adding a scoped node (resource=reminders, operation=list) rather than the full node keeps Susan's tool list clean and focused, per user direction.
- The display name is renamed in the node TS to avoid confusion with the built-in slackTool already present in Susan.

## Prerequisites

- Slack CLI venv active: `source <cli-tools-root>/slack/.venv/bin/activate`
- n8n CLI venv active: `source <cli-tools-root>/n8n/.venv/bin/activate`
- Browser available for Slack re-auth (playwright session)
- adam-server reachable via `ssh adam-server`

---

## Implementation Steps

### Step 1: Re-add reminders to slack CLI main.py

**File:** `<cli-tools-root>/slack/slack_cli/main.py`

**Action:** Add `reminders` to the import line and register its typer app. Insert after the `from .commands import auth, channels, dm, messages, users, files` line and after `canvas, notifications`:

Change line 17 from:
```python
from .commands import auth, channels, dm, messages, users, files
from .commands import canvas, notifications
```
To:
```python
from .commands import auth, channels, dm, messages, users, files
from .commands import canvas, notifications, reminders
```

Then add after line 28 (`app.add_typer(users.app, ...)`):
```python
app.add_typer(reminders.app, name="reminders", help="Manage Slack saved items (reminders/Later)")
```

**Verify:**
```bash
cd <cli-tools-root>/slack && source .venv/bin/activate && slack reminders --help
```
Expected: shows `list`, `get`, `complete`, `new`, `delete` subcommands.

---

### Step 2: Fix Slack auth — re-login to capture xoxc token

**Action:** Run browser login with `--force` to clear the stale xoxp token and capture a fresh xoxc token from localStorage via the playwright browser automation.

```bash
cd <cli-tools-root>/slack && source .venv/bin/activate && slack auth login --force
```

This opens a browser via playwright. Log in to Slack. The `_on_authenticated` callback in `browser.py` extracts the xoxc token from `localStorage.localConfig_v2` and saves it as `ACCESS_TOKEN` in the profile `.env`.

**Verify:**
```bash
cd <cli-tools-root>/slack && source .venv/bin/activate && slack auth status
```
Expected: `"access_token"` value starts with `xoxc` (not `xoxp`).

Then confirm the API call works:
```bash
slack reminders list
```
Expected: JSON response with `"ok": true` and `"saved_items"` array (may be empty).

---

### Step 3: Update the node display name in the generator source

**File:** `<cli-tools-root>/n8n/n8n_cli/generator.py` (or wherever `displayName` is set)

**Action:** Before regenerating with `--force`, find where the generator sets `displayName` for the node and ensure the display name will be `"Slack (Custom)"` instead of `"Slack"` so it doesn't clash with the built-in slackTool in Susan's workflow.

First locate the display name template:
```bash
grep -r "displayName" <cli-tools-root>/n8n/n8n_cli/ --include="*.py" -l
```
Then find the relevant line and note the pattern. The generator uses `metadata.display_name` from the CLI's metadata. Check what the slack CLI returns:
```bash
cd <cli-tools-root>/n8n && source .venv/bin/activate && n8n nodes list 2>&1 | python3 -c "import sys,json; data=json.load(sys.stdin); [print(t) for t in data if 'slack' in t.lower()]"
```

If the generator reads display name from a `display_name` attribute on the CLI metadata object, check the CLI's metadata file:
```bash
grep -r "display_name\|Slack" <cli-tools-root>/slack/slack_cli/ --include="*.py" | grep -i "display"
```

**Update:** Change the display name source so the generated node will have `displayName: 'Slack (Custom)'`. The correct place to make this change is in the CLI metadata (e.g. a `DISPLAY_NAME` constant or the `name` field in `pyproject.toml`/`setup.cfg` that the generator reads), NOT in the generated TypeScript (which will be overwritten by `--force`).

**Verify:** After finding and updating the source, confirm the value before proceeding to Step 4.

---

### CHECKPOINT: Verify steps 1-3 complete

**Run:**
```bash
cd <cli-tools-root>/slack && source .venv/bin/activate && slack reminders list
```
**Expected:** JSON output with `"ok": true`, no `not_allowed_token_type` error.

**Also confirm display name source is updated** before proceeding to regeneration.

---

### Step 4: Regenerate the slack-custom node package with --force

**Action:** Run the node generator. This overwrites all TypeScript and package files at `~/Dropbox/GitRepos/n8n-nodes/slack-custom/`.

```bash
cd <cli-tools-root>/n8n && source .venv/bin/activate && n8n nodes create slack --name slack-custom --force
```

**Expected output:** JSON summary showing:
- `"package": "slack-custom"`
- `"path": "...n8n-nodes/slack-custom"`
- `"resources"` count includes `reminders`
- `pending_tasks` lists the SVG icon task

**Verify reminders is included:**
```bash
grep -i "reminders\|Reminders" /Users/adam/Dropbox/GitRepos/n8n-nodes/slack-custom/nodes/SlackCustom/SlackCustom.node.ts
```
Expected: options entry for `reminders` resource.

**Verify display name:**
```bash
grep "displayName" /Users/adam/Dropbox/GitRepos/n8n-nodes/slack-custom/nodes/SlackCustom/SlackCustom.node.ts
```
Expected: `displayName: 'Slack (Custom)'`

---

### Step 5: Create the Slack SVG icon

**File:** `/Users/adam/Dropbox/GitRepos/n8n-nodes/slack-custom/nodes/SlackCustom/slack-custom.svg`

**Action:** Create the Slack brand icon as a 60x60 SVG. Slack's brand uses a multi-color hash/pound symbol with four colors: red (#E01E5A), green (#2EB67D), yellow (#ECB22E), blue (#36C5F0). The icon uses four "L"-shaped pieces forming a hashtag grid.

Write this file:
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 60" width="60" height="60">
  <!-- Top-left: green -->
  <rect x="11" y="11" width="10" height="10" rx="3" fill="#2EB67D"/>
  <rect x="11" y="23" width="10" height="10" rx="3" fill="#2EB67D"/>
  <!-- Top-right: yellow -->
  <rect x="23" y="11" width="10" height="10" rx="3" fill="#ECB22E"/>
  <rect x="35" y="11" width="10" height="10" rx="3" fill="#ECB22E"/>
  <!-- Bottom-left: blue -->
  <rect x="11" y="35" width="10" height="10" rx="3" fill="#36C5F0"/>
  <rect x="23" y="35" width="10" height="10" rx="3" fill="#36C5F0"/>
  <!-- Bottom-right: red -->
  <rect x="35" y="23" width="10" height="10" rx="3" fill="#E01E5A"/>
  <rect x="35" y="35" width="10" height="10" rx="3" fill="#E01E5A"/>
  <!-- Center intersection pieces -->
  <rect x="23" y="23" width="10" height="10" rx="3" fill="#ECB22E"/>
</svg>
```

**Verify:** File exists and is valid XML:
```bash
ls -la /Users/adam/Dropbox/GitRepos/n8n-nodes/slack-custom/nodes/SlackCustom/slack-custom.svg
```

---

### Step 6: Copy the updated xoxc token .env to the CLI bundle inside the package

**Action:** The generated package bundles a copy of the CLI source at `n8n-nodes/slack-custom/cli/`. The `.env` file with the new xoxc token needs to be present there so deploy.py can copy it to the server.

```bash
cp <cli-tools-root>/slack/.env /Users/adam/Dropbox/GitRepos/n8n-nodes/slack-custom/cli/.env
```

**Verify:**
```bash
grep "ACCESS_TOKEN" /Users/adam/Dropbox/GitRepos/n8n-nodes/slack-custom/cli/.env | cut -c1-30
```
Expected: `ACCESS_TOKEN=xoxc...` (starts with xoxc).

---

### CHECKPOINT: Verify steps 4-6 complete

**Run:**
```bash
grep -i "reminders" /Users/adam/Dropbox/GitRepos/n8n-nodes/slack-custom/nodes/SlackCustom/SlackCustom.node.ts && echo "reminders OK"
grep "xoxc" /Users/adam/Dropbox/GitRepos/n8n-nodes/slack-custom/cli/.env && echo "token OK"
ls /Users/adam/Dropbox/GitRepos/n8n-nodes/slack-custom/nodes/SlackCustom/slack-custom.svg && echo "icon OK"
```
**Expected:** All three echo "OK" messages printed.

---

### Step 7: Deploy the slack-custom package to adam-server

**Action:** Run the full deploy pipeline. This builds the TypeScript, rsyncs to the server, installs the npm package, installs the CLI venv, copies the .env, restarts n8n, and verifies the node loads.

```bash
cd <cli-tools-root>/n8n && source .venv/bin/activate && n8n nodes deploy /Users/adam/Dropbox/GitRepos/n8n-nodes/slack-custom
```

**Expected:** Pipeline runs through all stages ending with `"node_loaded": true` in the verification output.

**If auth check fails** (deploy checks browser session health): pass `--skip-auth-check` since we just re-authenticated in Step 2.

**Verify node loaded on server:**
```bash
cd <cli-tools-root>/n8n && source .venv/bin/activate && n8n nodes list --type community 2>&1 | python3 -c "import sys,json; data=json.load(sys.stdin); [print(n) for n in data if 'slack' in n.lower()]"
```
Expected: `n8n-nodes-slack-custom.slackCustom` appears in output.

---

### Step 8: Test reminders operation via n8n nodes test

**Action:** Verify the node executes correctly on the server with the reminders resource before wiring it into Susan.

```bash
cd <cli-tools-root>/n8n && source .venv/bin/activate && n8n nodes test slack-custom --resource reminders --operation list
```

**Expected:** Execution succeeds with JSON output containing `saved_items` array. Exit code 0.

---

### CHECKPOINT: Verify steps 7-8 complete

**Expected:** Node deployed and reminders list test passes. If test fails, diagnose before proceeding to Susan integration.

---

### Step 9: Add slack-custom reminders node to Susan workflow

**Action:** Add the node scoped to reminders/list with a descriptive display name:

```bash
cd <cli-tools-root>/n8n && source .venv/bin/activate && n8n workflows node add U7cK5XlQqmgG9CWlrB6wM n8n-nodes-slack-custom.slackCustom --resource reminders --operation list --name "Get Slack Reminders"
```

**Verify node was added:**
```bash
n8n workflows get U7cK5XlQqmgG9CWlrB6wM | python3 -c "import sys,json; wf=json.load(sys.stdin); [print(n['name']) for n in wf.get('nodes',[])]"
```
Expected: `"Get Slack Reminders"` appears in the list.

---

### Step 10: Connect the node to Susan as an AI tool

**Action:**

```bash
cd <cli-tools-root>/n8n && source .venv/bin/activate && n8n workflows node connect U7cK5XlQqmgG9CWlrB6wM --from "Get Slack Reminders" --to "Susan" --type ai_tool
```

**Verify connection:**
```bash
n8n workflows get U7cK5XlQqmgG9CWlrB6wM | python3 -c "
import sys, json
wf = json.load(sys.stdin)
conns = wf.get('connections', {})
if 'Get Slack Reminders' in conns:
    print('Connection found:', conns['Get Slack Reminders'])
else:
    print('ERROR: no connection from Get Slack Reminders')
"
```
Expected: connection entry present pointing to Susan with type `ai_tool`.

---

### Step 11: Execute Susan workflow to test reminders tool end-to-end

**Action:** The Susan workflow uses a Chat Message trigger. The simplest validation is to confirm the workflow is active and the node appears in the tool list. Use `n8n workflows execute` for a manual trigger test:

```bash
cd <cli-tools-root>/n8n && source .venv/bin/activate && n8n workflows execute U7cK5XlQqmgG9CWlrB6wM
```

**Note:** Since Susan requires a chat input prompt, the better test is to send a message via the n8n UI or webhook. Check Susan's execution history afterward:

```bash
ssh adam-server "curl -s -H 'X-N8N-API-KEY: \$(grep N8N_API_KEY ~/.n8n/.env | cut -d= -f2)' http://localhost:5678/api/v1/executions?workflowId=U7cK5XlQqmgG9CWlrB6wM\\&limit=1 | python3 -m json.tool | head -40"
```

Alternatively test via the n8n UI by opening a chat with Susan and asking: "What are my current Slack reminders?"

**Expected:** Susan calls the `Get Slack Reminders` tool, which returns `saved_items` JSON, and Susan summarizes the results.

---

## What's NOT Included

- Other slack-custom resources (channels, messages, DM, etc.) are NOT connected as AI tools — only reminders per user direction
- No credential UI configuration — deploy.py auto-creates credentials from .env
- No changes to Susan's system prompt — the tool description from the node is sufficient

## Success Criteria

- [ ] `slack reminders list` returns `"ok": true` with xoxc token
- [ ] Regenerated node includes `reminders` resource in SlackCustom.node.ts
- [ ] Node display name is `"Slack (Custom)"` in generated TypeScript
- [ ] `slack-custom.svg` icon present in package
- [ ] `n8n nodes deploy` completes with `"node_loaded": true`
- [ ] `n8n nodes test slack-custom --resource reminders --operation list` passes
- [ ] `"Get Slack Reminders"` node present in Susan workflow with ai_tool connection to "Susan"
- [ ] Susan correctly calls the tool when asked about Slack reminders
