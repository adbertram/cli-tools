# iMessage CLI

CLI tool for interacting with iMessage on macOS. Uses SQLite for fast reads from the Messages database and AppleScript for sending messages.

## Requirements

- macOS (tested on macOS 10.15+)
- Full Disk Access granted to terminal (for reading chat.db)
- Contacts access permission (for contacts commands)

## Installation

The CLI is installed automatically via the cli-tools scaffolding. To install manually:

```bash
cd <cli-tools-root>/imessage
pip install -e .
```

## Permissions Setup

Before using the CLI, you need to grant permissions:

1. Open System Settings (or use `imessage auth login`)
2. Navigate to Privacy & Security > Full Disk Access
3. Add your terminal app (Terminal.app, iTerm.app, etc.)
4. Restart your terminal

Check permissions status:
```bash
imessage auth status
```

## Commands

### Auth

#### `imessage auth status`
Check system permissions and accessibility.

```bash
imessage auth status
imessage auth status --table
```

**Output fields:**
- `authenticated`: Whether Full Disk Access is granted
- `messages_db_accessible`: Whether Messages database is readable
- `messages_app_available`: Whether Messages app scripting is available
- `contacts_accessible`: Whether Contacts app is accessible
- `macos_version`: macOS version

**Exit codes:**
- `0`: Authenticated
- `2`: Not authenticated

#### `imessage auth login`
Open System Settings to grant permissions.

```bash
imessage auth login
imessage auth login --force
```

**Options:**
- `--force, -F`: Force re-opening System Settings

#### `imessage auth logout`
No-op for iMessage (no session to clear).

```bash
imessage auth logout
```

### Contacts

#### `imessage contacts list`
List contacts from macOS Contacts app.

```bash
# Basic list
imessage contacts list

# As table
imessage contacts list --table

# Limit results
imessage contacts list --limit 10

# Filter by name
imessage contacts list --filter "name:like:%john%"

# Filter by organization
imessage contacts list --filter "organization:eq:Acme Corp"

# Select specific fields
imessage contacts list --properties "name,phones"
imessage contacts list --properties "id,name,emails" --table
```

**Options:**
- `--table, -t`: Display as table
- `--limit, -l`: Maximum number of contacts (default: 100)
- `--filter, -f`: Filter results (field:op:value)
- `--properties, -p`: Comma-separated fields to include

**Output fields:**
- `id`: Contact ID
- `name`: Full name
- `first_name`: First name
- `last_name`: Last name
- `phones`: List of phone numbers
- `emails`: List of email addresses
- `organization`: Organization name

**Filter operators:**
- `eq`: Equals
- `ne`: Not equals
- `like`: SQL LIKE pattern (`%` for wildcard)
- `ilike`: Case-insensitive LIKE
- `gt`, `gte`, `lt`, `lte`: Comparisons
- `in`: In list (values separated by `|`)
- `nin`: Not in list
- `null`: Is null
- `notnull`: Is not null

#### `imessage contacts get`
Get a specific contact by ID.

```bash
# Get contact
imessage contacts get CONTACT_ID

# As table
imessage contacts get CONTACT_ID --table

# Select specific fields
imessage contacts get CONTACT_ID --properties "name,phones"
```

**Options:**
- `--table, -t`: Display as table
- `--properties, -p`: Comma-separated fields to include

### Conversations

#### `imessage conversations list`
List recent conversations.

```bash
# Basic list
imessage conversations list

# As table
imessage conversations list --table

# Limit results
imessage conversations list --limit 20

# Filter by service
imessage conversations list --filter "service:iMessage"

# Filter unread
imessage conversations list --filter "is_read:false"

# Select specific fields
imessage conversations list --properties "id,display_name,last_message_text"
```

**Options:**
- `--table, -t`: Display as table
- `--limit, -l`: Maximum number of conversations (default: 50)
- `--filter, -f`: Filter results (field:op:value)
- `--properties, -p`: Comma-separated fields to include

**Output fields:**
- `id`: Conversation ID (ROWID from chat table)
- `guid`: Conversation GUID
- `chat_identifier`: Chat identifier (phone/email)
- `display_name`: Display name
- `handle_id`: Handle ID (contact phone/email)
- `service`: Service type (iMessage or SMS)
- `last_message_text`: Last message preview
- `last_message_date`: ISO timestamp of last message
- `last_message_is_from_me`: Whether last message was sent by user
- `is_read`: Whether conversation has unread messages

#### `imessage conversations get`
Get a conversation with its recent messages.

```bash
# Get conversation
imessage conversations get CONVERSATION_ID

# As table
imessage conversations get CONVERSATION_ID --table

# Select specific fields
imessage conversations get CONVERSATION_ID --properties "id,display_name,message_count"
```

**Options:**
- `--table, -t`: Display as table
- `--properties, -p`: Comma-separated fields to include

**Output fields (in addition to list fields):**
- `messages`: Array of message objects
- `message_count`: Number of messages returned

### Messages

#### `imessage messages list`
List recent messages.

```bash
# Basic list
imessage messages list

# As table
imessage messages list --table

# Limit results
imessage messages list --limit 20

# Filter by contact (phone or email)
imessage messages list --contact "+15551234567"
imessage messages list --contact "user@example.com"

# Filter sent messages
imessage messages list --filter "is_from_me:true"

# Filter received messages
imessage messages list --filter "is_from_me:false"

# Select specific fields
imessage messages list --properties "id,text,date"
imessage messages list --properties "id,text,is_from_me,handle_id" --table
```

**Options:**
- `--table, -t`: Display as table
- `--limit, -l`: Maximum number of messages (default: 50)
- `--contact`: Filter by contact phone/email
- `--filter, -f`: Filter results (field:op:value)
- `--properties, -p`: Comma-separated fields to include

**Output fields:**
- `id`: Message ID (ROWID from message table)
- `guid`: Message GUID
- `text`: Message text content
- `date`: ISO timestamp
- `is_from_me`: Whether message was sent by user
- `is_read`: Whether message has been read
- `service`: Service type (iMessage or SMS)
- `has_attachment`: Whether message has attachments
- `handle_id`: Sender/recipient handle (phone/email)

#### `imessage messages get`
Get a specific message by ID.

```bash
# Get message
imessage messages get MESSAGE_ID

# As table
imessage messages get MESSAGE_ID --table

# Select specific fields
imessage messages get MESSAGE_ID --properties "id,text,date"
```

**Options:**
- `--table, -t`: Display as table
- `--properties, -p`: Comma-separated fields to include

**Output fields (in addition to list fields):**
- `date_read`: ISO timestamp when message was read
- `date_delivered`: ISO timestamp when message was delivered
- `associated_message_type`: Associated message type code

#### `imessage messages send`
Send a message to a recipient.

```bash
# Send to phone number
imessage messages send "+15551234567" "Hello!"

# Send to email
imessage messages send "user@example.com" "Hi there"

# Phone numbers are auto-normalized
imessage messages send "5551234567" "Hey"  # Becomes +15551234567
```

**Arguments:**
- `recipient`: Phone number or email address
- `text`: Message text to send

**Output fields:**
- `success`: Whether message was sent successfully
- `recipient`: Normalized recipient (with +1 prefix for US numbers)
- `message`: Message text that was sent
- `service`: Service used (iMessage)

**Phone number normalization:**
- 10-digit numbers: `+1` prefix added (US)
- Already prefixed: Used as-is
- Email addresses: Used as-is

## Output Formats

All commands support two output formats:

1. **JSON** (default): Machine-readable, suitable for piping to `jq`
2. **Table** (`--table`): Human-readable table format

### JSON Output
```bash
imessage contacts list | jq '.[] | select(.organization == "Acme Corp")'
```

### Table Output
```bash
imessage contacts list --table
```

## Filter Syntax

Filters use the format: `field:operator:value`

### Examples

```bash
# Equality
--filter "name:eq:John Smith"

# Pattern matching (% is wildcard)
--filter "name:like:%john%"

# Case-insensitive pattern
--filter "name:ilike:%JOHN%"

# Comparisons
--filter "message_count:gt:10"

# Multiple conditions (AND logic)
--filter "service:eq:iMessage,is_read:false"

# In list
--filter "service:in:iMessage|SMS"

# Null checks
--filter "organization:null"
--filter "organization:notnull"
```

### Supported Operators

- `eq`: Equals
- `ne`: Not equals
- `like`: SQL LIKE with `%` wildcards
- `ilike`: Case-insensitive LIKE
- `gt`, `gte`, `lt`, `lte`: Comparisons
- `in`: Value in list (pipe-separated)
- `nin`: Value not in list
- `null`: Field is null
- `notnull`: Field is not null

## Properties Selection

Use `--properties` to select specific fields:

```bash
# Single field
imessage contacts list --properties "name"

# Multiple fields
imessage contacts list --properties "id,name,phones"

# Works with table output
imessage contacts list --properties "name,emails" --table
```

## Database Schema

The CLI reads from `~/Library/Messages/chat.db` (SQLite database).

### Key Tables

- **message**: Message content, timestamps, metadata
- **handle**: Contact identifiers (phone/email)
- **chat**: Conversation metadata
- **chat_handle_join**: Links chats to contacts
- **chat_message_join**: Links chats to messages

### Date Format

iMessage stores dates as nanoseconds since 2001-01-01 (Apple epoch). The CLI automatically converts to ISO 8601 format.

## Troubleshooting

### "Cannot open iMessage database" error

Grant Full Disk Access:
1. `imessage auth login` (opens System Settings)
2. Privacy & Security > Full Disk Access
3. Add your terminal app
4. Restart terminal

### "Failed to list contacts" error

Grant Contacts access:
1. System Settings > Privacy & Security > Contacts
2. Enable access for Terminal/iTerm

### Empty message text

On newer macOS versions, message text is stored in `attributedBody` blob. The CLI automatically extracts text from this field.

### Sending messages fails

Ensure:
1. Messages app is running
2. iMessage is signed in
3. Recipient format is correct (phone with country code or email)

## Examples

### Find unread conversations
```bash
imessage conversations list --filter "is_read:false" --table
```

### Get messages from specific contact
```bash
imessage messages list --contact "+15551234567" --limit 10
```

### Export all contacts to JSON
```bash
imessage contacts list --limit 1000 > contacts.json
```

### Send bulk messages
```bash
for number in "+15551234567" "+15559876543"; do
  imessage messages send "$number" "Hello from CLI!"
done
```

### Find conversations with unread messages
```bash
imessage conversations list | jq '.[] | select(.is_read == false) | .display_name'
```

## Architecture

- **SQLite** for reads: Direct database access for fast querying
- **AppleScript** for writes: Reliable message sending via Messages app
- **Pydantic models**: Type-safe data validation and serialization
- **Rich tables**: Beautiful terminal output with box-drawing characters

## Limitations

- Read-only access to messages (no deletion or editing)
- Attachments are detected but not downloaded
- Group message handling is limited to basic metadata
- Requires macOS with Messages app

## License

MIT License - See cli-tools repository for details.
