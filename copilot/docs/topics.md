# Topics

Topics define conversation flows for Copilot Studio agents using AdaptiveDialog YAML format.

For the complete YAML schema reference (trigger types, action nodes, variables, conditions, Power Fx expressions), see [topic-yaml-schema.md](topic-yaml-schema.md).

## Topic Commands

### List Topics

```bash
copilot agent topic list --agentId <agent-id>           # List all topics
copilot agent topic list --agentId <agent-id>   # Formatted table
copilot agent topic list --agentId <agent-id> --system  # System topics only
copilot agent topic list --agentId <agent-id> --custom  # Custom topics only
```

| Option | Description |
|--------|-------------|
| `-a, --agentId` | Agent's unique identifier (required) |
| `-s, --system` | List only system (managed) topics |
| `-c, --custom` | List only custom (user-created) topics |

### Get Topic

```bash
copilot agent topic get <topic-id>              # Get topic details (JSON)
copilot agent topic get <topic-id> --yaml       # Output YAML content only
copilot agent topic get <topic-id> -o file.yaml # Save YAML to file
```

| Option | Description |
|--------|-------------|
| `-y, --yaml` | Output topic content as YAML |
| `-o, --output` | Write YAML content to file |

### Create Topic

```bash
# Create from YAML file
copilot agent topic create --agentId <agent-id> --name "My Topic" --file topic.yaml

# Create simple topic with triggers and message
copilot agent topic create --agentId <agent-id> --name "Greeting" \
    --triggers "hello,hi,hey there" --message "Hello! How can I help?"
```

| Option | Description |
|--------|-------------|
| `-a, --agentId` | Agent's unique identifier (required) |
| `-n, --name` | Display name for the topic (required) |
| `-f, --file` | Path to YAML file containing topic content |
| `-t, --triggers` | Comma-separated trigger phrases |
| `-m, --message` | Response message (for simple topics) |
| `-d, --description` | Optional description |

### Update Topic

```bash
copilot agent topic update <topic-id> --file updated.yaml
copilot agent topic update <topic-id> --name "New Name"
copilot agent topic update <topic-id> --triggers "new,phrases" --message "New response"
copilot agent topic update <topic-id> --description "Updated description"
```

### Enable/Disable Topic

```bash
copilot agent topic enable <topic-id>
copilot agent topic disable <topic-id>
```

### Delete Topic

```bash
copilot agent topic delete <topic-id>           # Delete (with confirmation)
copilot agent topic delete <topic-id> --force   # Delete without confirmation
```

## Topic YAML Examples

Topics use AdaptiveDialog YAML format. See [topic-yaml-schema.md](topic-yaml-schema.md) for the complete schema reference including:
- Trigger types (OnRecognizedIntent, OnActivity, OnConversationStart, etc.)
- Action nodes (SendMessage, Question, ConditionGroup, BeginDialog, etc.)
- Variables and entities
- Conditions and Power Fx expressions

### Simple Topic Example

```yaml
kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Greeting
    triggerQueries:
      - hello
      - hi
      - hey there

  actions:
    - kind: SendMessage
      id: sendMessage_greeting
      message: Hello! How can I help you today?
```

### Topic with Condition Branches

```yaml
kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Product Help
    triggerQueries:
      - help with product
      - product question

  actions:
    - kind: ConditionGroup
      id: conditionGroup_product
      conditions:
        - id: condition_alpha
          condition: =Topic.product = "ProductAlpha"
          displayName: ProductAlpha
          actions:
            - kind: BeginDialog
              id: beginDialog_alpha
              dialog: pub_myAgent.InvokeConnectedAgentTaskAction.ProductAlphaExpert

        - id: condition_beta
          condition: =Topic.product = "ProductBeta"
          displayName: ProductBeta
          actions:
            - kind: BeginDialog
              id: beginDialog_beta
              dialog: pub_myAgent.InvokeConnectedAgentTaskAction.ProductBetaExpert

      elseActions:
        - kind: SendMessage
          id: sendMessage_unknown
          message: I couldn't determine which product you need help with.
```
