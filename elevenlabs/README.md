# ElevenLabs CLI

A command-line interface for the [ElevenLabs API](https://elevenlabs.io/docs/api-reference). It supports API-key authentication, voice discovery, model inspection, subscription quota checks, pronunciation dictionaries, and text-to-speech audio generation.

## Installation

```bash
cd <cli-tools-root>/elevenlabs
uv tool install -e . --force --refresh
```

After installation, the `elevenlabs` command is available globally.

## Quick Start

```bash
elevenlabs auth login
elevenlabs auth status
elevenlabs voices list --table
elevenlabs models list --table
elevenlabs pronunciation-dictionaries list --table
elevenlabs speech create VOICE_ID "The first move is what sets everything in motion." --output speech.mp3
```

## Commands

### Authentication

```bash
# Save API key
elevenlabs auth login
elevenlabs auth login --api-key YOUR_API_KEY

# Re-authenticate
elevenlabs auth login --force
elevenlabs auth login -F

# Check authentication status
elevenlabs auth status

# Clear stored credentials
elevenlabs auth logout

# Test configured credentials
elevenlabs auth test
```

### Profiles

```bash
elevenlabs auth profiles list
elevenlabs auth profiles get default
elevenlabs auth profiles create production
elevenlabs auth profiles select production
elevenlabs auth profiles delete production
```

### Voices

```bash
# List voices
elevenlabs voices list
elevenlabs voices list --table
elevenlabs voices list --limit 25
elevenlabs voices list --properties "voice_id,name,category"

# Server-side voice query parameters
elevenlabs voices list --search Rachel
elevenlabs voices list --voice-type personal
elevenlabs voices list --category generated
elevenlabs voices list --sort name --sort-direction asc

# CLI filter syntax
elevenlabs voices list --filter "name:ilike:%rachel%"
elevenlabs voices list --filter "category:eq:generated"

# Get one voice
elevenlabs voices get VOICE_ID
elevenlabs voices get VOICE_ID --table
elevenlabs voices get VOICE_ID --properties "voice_id,name,labels.accent"

# Get stored voice settings
elevenlabs voices settings VOICE_ID
elevenlabs voices settings VOICE_ID --table
```

### Models

```bash
# List models
elevenlabs models list
elevenlabs models list --table
elevenlabs models list --limit 10
elevenlabs models list --filter "can_do_text_to_speech:eq:true"
elevenlabs models list --properties "model_id,name,maximum_text_length_per_request"

# Get one model by ID
elevenlabs models get eleven_multilingual_v2
elevenlabs models get eleven_multilingual_v2 --table
```

### Speech

```bash
# Create speech audio
elevenlabs speech create VOICE_ID "Hello from ElevenLabs." --output hello.mp3

# Choose model and output format
elevenlabs speech create VOICE_ID "Hello." --output hello.mp3 --model-id eleven_multilingual_v2 --output-format mp3_44100_128

# Override voice settings for one request
elevenlabs speech create VOICE_ID "Hello." --output hello.mp3 --stability 0.5 --similarity-boost 0.75 --style 0 --speaker-boost

# Use generation options
elevenlabs speech create VOICE_ID "Hello." --output hello.mp3 --language-code en --seed 123 --text-normalization auto

# Apply pronunciation dictionaries by version locator
elevenlabs speech create VOICE_ID "Hello sysadmins." --output hello.mp3 --pronunciation-dictionary DICT_ID:VERSION_ID

# Output result metadata as a table
elevenlabs speech create VOICE_ID "Hello." --output hello.mp3 --table
```

### Pronunciation Dictionaries

```bash
# List and inspect dictionaries
elevenlabs pronunciation-dictionaries list --table
elevenlabs pronunciation-dictionaries get DICT_ID --table

# Create dictionaries from inline rules
elevenlabs pronunciation-dictionaries create-from-rules --name "Course Terms" --alias-rule "Sysadmins=sys admins"
elevenlabs pronunciation-dictionaries create-from-rules --name "English Terms" --phoneme-rule "route|cmu|R AW1 T"

# Create dictionaries from PLS files
elevenlabs pronunciation-dictionaries create-from-file --name "Course Terms" --file dictionary.pls

# Update metadata without changing the dictionary version
elevenlabs pronunciation-dictionaries update DICT_ID --name "Renamed Terms"
elevenlabs pronunciation-dictionaries update DICT_ID --archived

# Replace, add, or remove rules
elevenlabs pronunciation-dictionaries set-rules DICT_ID --alias-rule "Sysadmins=sys admins"
elevenlabs pronunciation-dictionaries add-rules DICT_ID --alias-rule "PowerShell=Power Shell"
elevenlabs pronunciation-dictionaries remove-rules DICT_ID --rule-string "Sysadmins"

# Download a dictionary version as PLS
elevenlabs pronunciation-dictionaries download DICT_ID VERSION_ID --output dictionary.pls
```

### User

```bash
# Get subscription and quota state
elevenlabs user subscription
elevenlabs user subscription --table
elevenlabs user subscription --properties "tier,status,character_count,character_limit"
```

### Cache

```bash
elevenlabs cache status
elevenlabs cache clear
```

## Output

JSON is the default output for all commands. Use `--table` or `-t` for table output where supported.

```bash
elevenlabs voices list --limit 5 | jq '.[].voice_id'
elevenlabs models list --table
```

List commands support:

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display table output |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results with `field:op:value` syntax |
| `--properties` | `-p` | Comma-separated fields to include |

## Configuration

Credentials are stored in the active profile `.env` file.

```bash
API_KEY=your_elevenlabs_api_key
BASE_URL=https://api.elevenlabs.io
```

The API key is sent as the `xi-api-key` header.

## Models

This CLI uses Pydantic models and preserves additional API fields in JSON output.

| Model | Description |
|-------|-------------|
| `Voice` | ElevenLabs voice metadata |
| `VoiceSettings` | Voice generation settings |
| `Model` | ElevenLabs model metadata |
| `Subscription` | User subscription and quota state |
| `SpeechResult` | Metadata for generated audio written to disk |
| `PronunciationDictionary` | Pronunciation dictionary metadata and rules |
| `PronunciationDictionaryList` | Pronunciation dictionary list response with pagination metadata |
| `PronunciationDictionaryRulesResult` | Dictionary version metadata after rule changes |
| `PronunciationDictionaryDownloadResult` | Metadata for downloaded PLS files |
