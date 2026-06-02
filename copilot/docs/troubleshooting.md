# Troubleshooting

Common issues, debug workflow, and exit codes.

## Common Issues

**Authentication Errors:**
```bash
# Ensure you're logged in to Azure CLI
az login

# Verify Dataverse URL is set
echo $DATAVERSE_URL
```

**Agent Not Responding:**
1. Check if agent is published: `copilot agent get <agent-id>`
2. Check analytics for errors: `copilot agent analytics query <agent-id> -t 1h`
3. Review recent transcripts: `copilot agent transcript list --agent <agent-id>`

**Topic Not Triggering:**
1. Ensure topic is enabled: `copilot agent topic list --agentId <agent-id>`
2. Check trigger phrases match user input
3. Verify topic YAML syntax: `copilot agent topic get <topic-id> --yaml`

**Connected Agent Not Working:**
1. Verify target agent is published
2. Check "Let other agents connect" is enabled in target agent settings
3. Review tool configuration: `copilot agent tool list --agentId <agent-id>`

**Agent Flow Fails with "Forbidden" Error on AI Builder Prompt:**
1. The service principal running the flow needs ReadAccess to the prompt
2. Grant access: `copilot tool prompt permissions grant <prompt-id> --principal <sp-user-id> --level read`

**Permissions Commands:**
- `copilot tool prompt permissions` - Full implementation (grant, revoke, list)
- `copilot agent permissions` - Coming soon (placeholder)
- `copilot agent-flow permissions` - Coming soon (placeholder)

## Debug Workflow

1. **Check agent status:**
   ```bash
   copilot agent get <agent-id>
   ```

2. **Query recent telemetry:**
   ```bash
   copilot agent analytics query <agent-id> -t 1h --events
   ```

3. **Review conversation transcripts:**
   ```bash
   copilot agent transcript list --agent <agent-id> --limit 5
   copilot agent transcript get <transcript-id>
   ```

4. **Verify topic configuration:**
   ```bash
   copilot agent topic list --agentId <agent-id>
   copilot agent topic get <topic-id> --yaml
   ```

5. **Check tool dependencies:**
   ```bash
   copilot tool list --installed
   ```

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | General error |
| `2` | Authentication/credentials error |
| `130` | Interrupted (Ctrl+C) |
