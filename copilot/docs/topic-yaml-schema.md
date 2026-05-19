# Copilot Studio Topic YAML Schema Reference

This document provides a comprehensive reference for the YAML schema used to define topics in Microsoft Copilot Studio. Topics are stored as `botcomponent` records (agent components) with `componenttype` 0 (legacy) or 9 (V2).

## Table of Contents

- [Root Structure](#root-structure)
- [Trigger Types](#trigger-types)
- [Action Nodes](#action-nodes)
- [Variables](#variables)
- [Entity Types](#entity-types)
- [Condition Expressions](#condition-expressions)
- [Complete Examples](#complete-examples)

---

## Root Structure

Every topic YAML file starts with an `AdaptiveDialog` kind:

```yaml
kind: AdaptiveDialog
beginDialog:
  kind: <TriggerType>
  id: main
  # ... trigger-specific properties
  actions:
    - # action nodes
```

### Root Properties

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `kind` | string | Yes | Always `AdaptiveDialog` |
| `beginDialog` | object | Yes | Contains the trigger and actions |
| `startBehavior` | string | No | `CancelOtherTopics` or `RunSideBySide` |

---

## Trigger Types

### OnRecognizedIntent

Standard trigger for topics activated by user phrases.

```yaml
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: "My Topic Name"
    triggerQueries:
      - "phrase one"
      - "phrase two"
      - "phrase three"
    includeInOnSelectIntent: true  # Optional
  priority: 50  # Optional, default varies
  actions:
    - # actions
```

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `intent.displayName` | string | Yes | Display name shown in topic list |
| `intent.triggerQueries` | array | Yes | List of trigger phrases |
| `intent.includeInOnSelectIntent` | boolean | No | Include in disambiguation |
| `priority` | integer | No | Topic priority (-1 to 100) |

### OnUnknownIntent

Fallback trigger when no other topic matches. Used for generative/conversational boosting.

```yaml
beginDialog:
  kind: OnUnknownIntent
  id: main
  priority: -1
  actions:
    - # actions (typically SearchAndSummarizeContent)
```

### OnEscalate

Trigger for escalation to live agent.

```yaml
beginDialog:
  kind: OnEscalate
  id: main
  intent:
    displayName: Escalate
    includeInOnSelectIntent: false
    triggerQueries:
      - "Talk to agent"
      - "Speak to a person"
      - "Live support"
  actions:
    - kind: TransferConversationV2
      id: transfer_abc123
      transferType:
        kind: TransferToAgent
        messageToAgent: "User requested live agent"
```

### OnConversationStart

Trigger when conversation begins (greeting).

```yaml
beginDialog:
  kind: OnConversationStart
  id: main
  actions:
    - kind: SendMessage
      id: greeting_msg
      message: "Hello! Welcome to our service."
```

### OnError

Trigger for handling errors.

```yaml
beginDialog:
  kind: OnError
  id: main
  actions:
    - kind: SendMessage
      id: error_msg
      message: "Sorry, something went wrong. Please try again."
```

---

## Action Nodes

### SendMessage

Display a message to the user.

```yaml
- kind: SendMessage
  id: sendMessage_abc123
  message: "Your message text here"
```

With message variations (random selection):

```yaml
- kind: SendMessage
  id: sendMessage_abc123
  message:
    - "Variation 1"
    - "Variation 2"
    - "Variation 3"
```

With speech (for voice channels):

```yaml
- kind: SendMessage
  id: sendMessage_abc123
  message: "Display text"
  speak: "Speech text for voice channels"
```

### Question

Ask the user a question and store the response.

```yaml
- kind: Question
  id: question_abc123
  alwaysPrompt: false
  variable: init:Topic.UserName
  prompt: "What is your name?"
  entity: PersonNamePrebuiltEntity
```

With validation:

```yaml
- kind: Question
  id: question_abc123
  alwaysPrompt: false
  variable: init:Topic.Email
  prompt: "What is your email address?"
  entity: EmailPrebuiltEntity
  invalidPrompt: "That doesn't look like a valid email. Please try again."
  maxTurnCount: 3
  defaultValue: "unknown@example.com"
```

Multiple choice question:

```yaml
- kind: Question
  id: question_abc123
  alwaysPrompt: false
  variable: init:Topic.Choice
  prompt: "Which option do you prefer?"
  entity:
    kind: EmbeddedEntity
    definition:
      kind: ClosedListEntity
      items:
        - displayName: "Option A"
          values:
            - "A"
            - "option a"
            - "first option"
        - displayName: "Option B"
          values:
            - "B"
            - "option b"
            - "second option"
```

#### Question Properties

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string | Yes | Unique identifier |
| `variable` | string | Yes | Variable to store response (`init:Topic.VarName`) |
| `prompt` | string | Yes | Question text |
| `entity` | string/object | Yes | Entity type for validation |
| `alwaysPrompt` | boolean | No | Always ask, even if variable has value |
| `invalidPrompt` | string | No | Message when validation fails |
| `maxTurnCount` | integer | No | Max retries before using default |
| `defaultValue` | any | No | Default if max retries exceeded |
| `repromptOnInvalidResponse` | boolean | No | Reprompt on invalid input |

### ConditionGroup

Branch logic based on conditions.

```yaml
- kind: ConditionGroup
  id: condition_abc123
  conditions:
    - id: cond_option_a
      condition: =Topic.Choice = "Option A"
      actions:
        - kind: SendMessage
          id: msg_a
          message: "You chose Option A!"
    - id: cond_option_b
      condition: =Topic.Choice = "Option B"
      actions:
        - kind: SendMessage
          id: msg_b
          message: "You chose Option B!"
  elseActions:
    - kind: SendMessage
      id: msg_else
      message: "No valid option selected."
```

### SetVariable

Set a variable value.

```yaml
- kind: SetVariable
  id: setVar_abc123
  variable: Topic.Counter
  value: =Topic.Counter + 1
```

### ClearVariable

Clear a variable value.

```yaml
- kind: ClearVariable
  id: clearVar_abc123
  variable: Topic.TempData
```

### RedirectToTopic

Jump to another topic.

```yaml
- kind: RedirectToTopic
  id: redirect_abc123
  topicSchemaName: pub_agentName.topic.OtherTopic
```

With input parameters:

```yaml
- kind: RedirectToTopic
  id: redirect_abc123
  topicSchemaName: pub_agentName.topic.OtherTopic
  inputs:
    - name: InputParam1
      value: =Topic.SomeValue
    - name: InputParam2
      value: "Static value"
  outputs:
    - name: OutputParam1
      variable: Topic.Result
```

### EndDialog

End the current topic/conversation.

```yaml
- kind: EndDialog
  id: end_abc123
  clearTopicQueue: true  # Optional, clears all pending topics
```

### EndConversation

End the entire conversation with survey option.

```yaml
- kind: EndConversation
  id: endConv_abc123
  showSurvey: true
```

### TransferConversationV2

Transfer to live agent.

```yaml
- kind: TransferConversationV2
  id: transfer_abc123
  transferType:
    kind: TransferToAgent
    messageToAgent: "Customer needs assistance with billing"
    context:
      kind: AutomaticTransferContext
```

### SearchAndSummarizeContent

Generative answers from knowledge sources.

```yaml
- kind: SearchAndSummarizeContent
  id: search_abc123
  userInput: =System.Activity.Text
  variable: Topic.Answer
  moderationLevel: Medium
  additionalInstructions: "Be concise and professional."
  publicDataSource:
    sites:
      - "https://docs.example.com/"
      - "https://support.example.com/"
  sharePointSearchDataSource: {}
```

| Property | Type | Description |
|----------|------|-------------|
| `userInput` | string | User query expression |
| `variable` | string | Variable to store answer |
| `moderationLevel` | string | `High`, `Medium`, or `Low` |
| `additionalInstructions` | string | Custom instructions for AI |
| `publicDataSource.sites` | array | Website URLs to search |

### InvokeFlowAction

Call a Power Automate flow.

```yaml
- kind: InvokeFlowAction
  id: flow_abc123
  flowId: /providers/Microsoft.Flow/flows/<flow-guid>
  inputs:
    - name: InputParameter
      value: =Topic.UserInput
  outputs:
    - name: OutputParameter
      variable: Topic.FlowResult
```

### InvokeHttpAction

Make an HTTP request.

```yaml
- kind: InvokeHttpAction
  id: http_abc123
  method: POST
  url: "https://api.example.com/endpoint"
  headers:
    Content-Type: application/json
    Authorization: =System.AuthToken
  body: |
    {
      "query": "${Topic.UserQuery}"
    }
  responseVariable: Topic.ApiResponse
```

### ParseJsonValue

Parse JSON response.

```yaml
- kind: ParseJsonValue
  id: parse_abc123
  jsonValue: =Topic.ApiResponse
  schema:
    type: object
    properties:
      result:
        type: string
      count:
        type: number
  resultVariable: Topic.ParsedData
```

### AdaptiveCardPrompt

Show an Adaptive Card and capture input.

```yaml
- kind: AdaptiveCardPrompt
  id: card_abc123
  card:
    type: AdaptiveCard
    version: "1.5"
    body:
      - type: TextBlock
        text: "Please fill out the form:"
        weight: Bolder
      - type: Input.Text
        id: userName
        label: "Your Name"
        isRequired: true
    actions:
      - type: Action.Submit
        title: Submit
  outputVariable: Topic.CardResponse
```

### ForEach

Loop through a collection.

```yaml
- kind: ForEach
  id: foreach_abc123
  itemsSource: =Topic.ItemsList
  itemVariable: Topic.CurrentItem
  indexVariable: Topic.CurrentIndex
  actions:
    - kind: SendMessage
      id: msg_item
      message: "Item ${Topic.CurrentIndex}: ${Topic.CurrentItem.name}"
```

---

## Variables

### Variable Scopes

| Prefix | Scope | Description |
|--------|-------|-------------|
| `Topic.` | Topic | Available within current topic only |
| `Global.` | Agent | Available across all topics |
| `System.` | System | Built-in system variables (read-only) |

### Variable Initialization

```yaml
variable: init:Topic.NewVar    # Initialize if not exists
variable: Topic.ExistingVar    # Reference existing variable
```

### System Variables

| Variable | Description |
|----------|-------------|
| `System.Activity.Text` | User's message text |
| `System.Activity.Type` | Activity type (message, event) |
| `System.User.Id` | User's unique ID |
| `System.User.DisplayName` | User's display name |
| `System.Conversation.Id` | Conversation ID |
| `System.Bot.Id` | Agent ID |
| `System.Bot.Name` | Agent name |
| `System.Channel.Id` | Channel (webchat, teams, etc.) |
| `System.LastMessage.Text` | Previous message text |
| `System.AuthToken` | Authentication token (if authenticated) |

---

## Entity Types

### Prebuilt Entities

| Entity | Description | Example Values |
|--------|-------------|----------------|
| `StringPrebuiltEntity` | Free text input | Any text |
| `BooleanPrebuiltEntity` | Yes/No responses | yes, no, true, false |
| `NumberPrebuiltEntity` | Numeric values | 42, 3.14, -100 |
| `DateTimePrebuiltEntity` | Date and time | tomorrow, next Monday, 12/25/2024 |
| `EmailPrebuiltEntity` | Email addresses | user@example.com |
| `PersonNamePrebuiltEntity` | Person names | John Smith |
| `PhoneNumberPrebuiltEntity` | Phone numbers | +1-555-123-4567 |
| `URLPrebuiltEntity` | Web URLs | https://example.com |
| `MoneyPrebuiltEntity` | Currency amounts | $50, 100 USD |
| `PercentagePrebuiltEntity` | Percentages | 50%, 0.75 |
| `AgePrebuiltEntity` | Age values | 25 years old |
| `GeographyPrebuiltEntity` | Geographic locations | New York, France |
| `CityPrebuiltEntity` | City names | Seattle, London |
| `StatePrebuiltEntity` | US states | California, TX |
| `CountryPrebuiltEntity` | Country names | United States, Japan |
| `ZipCodePrebuiltEntity` | US ZIP codes | 98052, 10001-1234 |
| `OrganizationPrebuiltEntity` | Organization names | Microsoft, Apple Inc |

### Custom Entities

#### Closed List Entity

```yaml
entity:
  kind: EmbeddedEntity
  definition:
    kind: ClosedListEntity
    items:
      - displayName: "Small"
        values:
          - "small"
          - "sm"
          - "s"
      - displayName: "Medium"
        values:
          - "medium"
          - "med"
          - "m"
      - displayName: "Large"
        values:
          - "large"
          - "lg"
          - "l"
```

#### Regex Entity

```yaml
entity:
  kind: EmbeddedEntity
  definition:
    kind: RegexEntity
    pattern: "^[A-Z]{2,3}-\\d{4,6}$"
```

---

## Condition Expressions

Conditions use Power Fx expressions prefixed with `=`.

### Comparison Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `=` | Equal | `=Topic.Value = "test"` |
| `<>` | Not equal | `=Topic.Value <> "test"` |
| `>` | Greater than | `=Topic.Count > 5` |
| `<` | Less than | `=Topic.Count < 10` |
| `>=` | Greater or equal | `=Topic.Count >= 1` |
| `<=` | Less or equal | `=Topic.Count <= 100` |

### Logical Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `&&` | And | `=Topic.A && Topic.B` |
| `\|\|` | Or | `=Topic.A \|\| Topic.B` |
| `!` | Not | `=!Topic.IsValid` |

### Functions

| Function | Description | Example |
|----------|-------------|---------|
| `IsBlank()` | Check if empty/null | `=IsBlank(Topic.Value)` |
| `!IsBlank()` | Check if has value | `=!IsBlank(Topic.Value)` |
| `Len()` | String length | `=Len(Topic.Text) > 0` |
| `Lower()` | Lowercase | `=Lower(Topic.Input)` |
| `Upper()` | Uppercase | `=Upper(Topic.Input)` |
| `Trim()` | Remove whitespace | `=Trim(Topic.Input)` |
| `Contains()` | String contains | `=Contains(Topic.Text, "search")` |
| `StartsWith()` | String starts with | `=StartsWith(Topic.Text, "Hello")` |
| `EndsWith()` | String ends with | `=EndsWith(Topic.Text, "!")` |
| `CountRows()` | Count items | `=CountRows(Topic.List)` |
| `First()` | First item | `=First(Topic.List)` |
| `Last()` | Last item | `=Last(Topic.List)` |
| `Text()` | Convert to text | `=Text(Topic.Number)` |
| `Value()` | Convert to number | `=Value(Topic.Text)` |

---

## Complete Examples

### Simple Greeting Topic

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
      - hey
      - good morning
      - good afternoon

  actions:
    - kind: SendMessage
      id: greeting_msg
      message:
        - "Hello! How can I help you today?"
        - "Hi there! What can I assist you with?"
        - "Hey! I'm here to help. What do you need?"
```

### Topic with Question and Conditions

```yaml
kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Order Status
    triggerQueries:
      - check order status
      - where is my order
      - track my order
      - order tracking

  actions:
    - kind: Question
      id: ask_order_number
      alwaysPrompt: false
      variable: init:Topic.OrderNumber
      prompt: "Please provide your order number:"
      entity:
        kind: EmbeddedEntity
        definition:
          kind: RegexEntity
          pattern: "^ORD-\\d{6}$"
      invalidPrompt: "Order numbers start with ORD- followed by 6 digits (e.g., ORD-123456)"
      maxTurnCount: 3

    - kind: ConditionGroup
      id: check_order_valid
      conditions:
        - id: has_order
          condition: =!IsBlank(Topic.OrderNumber)
          actions:
            - kind: SendMessage
              id: looking_up
              message: "Looking up order ${Topic.OrderNumber}..."
            - kind: InvokeHttpAction
              id: api_call
              method: GET
              url: "https://api.example.com/orders/${Topic.OrderNumber}"
              responseVariable: Topic.OrderData
            - kind: SendMessage
              id: order_status
              message: "Your order status is: ${Topic.OrderData.status}"
      elseActions:
        - kind: SendMessage
          id: no_order
          message: "I couldn't get your order number. Please try again later."
```

### Conversational Boosting Topic (Fallback)

```yaml
kind: AdaptiveDialog
beginDialog:
  kind: OnUnknownIntent
  id: main
  priority: -1
  actions:
    - kind: SearchAndSummarizeContent
      id: search_content
      userInput: =System.Activity.Text
      variable: Topic.Answer
      moderationLevel: Medium
      additionalInstructions: |
        Be helpful and professional.
        If you don't know the answer, say so clearly.
        Always cite your sources when possible.
      publicDataSource:
        sites:
          - "https://docs.company.com/"
          - "https://support.company.com/"
      sharePointSearchDataSource: {}

    - kind: ConditionGroup
      id: has_answer_check
      conditions:
        - id: has_answer
          condition: =!IsBlank(Topic.Answer)
          actions:
            - kind: EndDialog
              id: end_topic
              clearTopicQueue: true
      elseActions:
        - kind: SendMessage
          id: no_answer
          message: "I'm sorry, I couldn't find information about that. Would you like to speak with a support agent?"
```

### Escalation Topic

```yaml
kind: AdaptiveDialog
startBehavior: CancelOtherTopics
beginDialog:
  kind: OnEscalate
  id: main
  intent:
    displayName: Escalate
    includeInOnSelectIntent: false
    triggerQueries:
      - talk to agent
      - speak to a person
      - human agent
      - live support
      - connect me to someone
      - customer service

  actions:
    - kind: Question
      id: ask_reason
      alwaysPrompt: false
      variable: init:Topic.EscalationReason
      prompt: "Before I connect you with an agent, could you briefly describe what you need help with?"
      entity: StringPrebuiltEntity

    - kind: TransferConversationV2
      id: transfer_to_agent
      transferType:
        kind: TransferToAgent
        messageToAgent: "Customer escalation reason: ${Topic.EscalationReason}"
        context:
          kind: AutomaticTransferContext
```

### Topic with Adaptive Card

```yaml
kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Feedback Form
    triggerQueries:
      - give feedback
      - submit feedback
      - I have feedback

  actions:
    - kind: AdaptiveCardPrompt
      id: feedback_card
      card:
        type: AdaptiveCard
        version: "1.5"
        body:
          - type: TextBlock
            text: "We'd love to hear your feedback!"
            weight: Bolder
            size: Medium
          - type: Input.Text
            id: feedbackText
            label: "Your Feedback"
            isMultiline: true
            isRequired: true
            placeholder: "Tell us what you think..."
          - type: Input.ChoiceSet
            id: rating
            label: "How would you rate your experience?"
            isRequired: true
            choices:
              - title: "Excellent"
                value: "5"
              - title: "Good"
                value: "4"
              - title: "Average"
                value: "3"
              - title: "Poor"
                value: "2"
              - title: "Very Poor"
                value: "1"
        actions:
          - type: Action.Submit
            title: "Submit Feedback"
      outputVariable: Topic.FeedbackResponse

    - kind: SendMessage
      id: thank_you
      message: "Thank you for your feedback! You rated us ${Topic.FeedbackResponse.rating}/5."
```

---

## Topic Parameters (Input/Output)

Topics can have input and output parameters for passing data between topics.

### Defining Parameters

```yaml
kind: AdaptiveDialog
inputParameters:
  - name: CustomerName
    type: String
    description: "Customer's name"
  - name: AccountId
    type: String
    description: "Account identifier"
outputParameters:
  - name: Result
    type: String
    description: "Operation result"
beginDialog:
  kind: OnRecognizedIntent
  id: main
  # ...
```

### Using Parameters

Input parameters are accessed via `Topic.InputParameterName`.
Output parameters are set via `SetVariable` before ending.

```yaml
actions:
  - kind: SendMessage
    id: greeting
    message: "Hello ${Topic.CustomerName}!"
  - kind: SetVariable
    id: set_result
    variable: Topic.Result
    value: "Success"
  - kind: EndDialog
    id: end
```

---

## Best Practices

1. **Unique IDs**: Every node must have a unique `id`. Use descriptive prefixes (e.g., `sendMessage_greeting`, `question_email`).

2. **Variable Naming**: Use descriptive PascalCase names (e.g., `Topic.CustomerEmail`, `Topic.OrderStatus`).

3. **Trigger Phrases**: Include 5-10 varied trigger phrases per topic for better recognition.

4. **Error Handling**: Always include `elseActions` in conditions for graceful fallbacks.

5. **Validation**: Use appropriate entity types and validation patterns for user input.

6. **Message Variations**: Use message arrays for more natural conversations.

7. **Testing**: Test topics with various inputs before publishing.

---

## CLI Commands

```bash
# List topics
copilot agent topic list --agentId <agent-id>
copilot agent topic list --agentId <agent-id> --custom
copilot agent topic list --agentId <agent-id> --system

# Get topic details
copilot agent topic get <topic-id>
copilot agent topic get <topic-id> --yaml
copilot agent topic get <topic-id> --output topic.yaml

# Create topic
copilot agent topic create --agentId <agent-id> --name "My Topic" --file topic.yaml
copilot agent topic create --agentId <agent-id> --name "Greeting" \
    --triggers "hello,hi,hey" --message "Hello! How can I help?"

# Update topic
copilot agent topic update <topic-id> --file updated-topic.yaml
copilot agent topic update <topic-id> --name "New Name"

# Enable/Disable
copilot agent topic enable <topic-id>
copilot agent topic disable <topic-id>

# Delete
copilot agent topic delete <topic-id>
copilot agent topic delete <topic-id> --force
```
