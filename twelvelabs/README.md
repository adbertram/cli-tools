# TwelveLabs CLI

A command-line interface for the [TwelveLabs API](https://docs.twelvelabs.io) - video AI for video understanding, indexing, and text generation.

## Installation

```bash
cd twelvelabs
pip install -e .
```

After installation, the `twelvelabs` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with TwelveLabs
twelvelabs auth login

# Create an index for your videos
twelvelabs indexes create my-course-videos

# Upload a video (waits for indexing by default)
twelvelabs videos upload INDEX_ID /path/to/video.mp4

# Generate text analysis from the video
twelvelabs generate text VIDEO_ID --prompt "Describe this video"
```

## Commands

### Authentication

```bash
# Login with API key (will prompt for key)
twelvelabs auth login

# Login with API key directly
twelvelabs auth login --api-key YOUR_API_KEY

# Re-authenticate (clear and login again)
twelvelabs auth login --force

# Check authentication status
twelvelabs auth status

# Clear stored credentials
twelvelabs auth logout
```

### Indexes

Indexes are containers that hold videos for analysis.

```bash
# List all indexes
twelvelabs indexes list
twelvelabs indexes list --table
twelvelabs indexes list --limit 10

# Get index details
twelvelabs indexes get INDEX_ID
twelvelabs indexes get INDEX_ID --table

# Create a new index
twelvelabs indexes create my-course-index
twelvelabs indexes create ai-102-nlp --engine pegasus1.5
twelvelabs indexes create ai-102-nlp-pegasus15 --engine pegasus1.5

# Delete an index (with confirmation)
twelvelabs indexes delete INDEX_ID
twelvelabs indexes delete INDEX_ID --force
```

### Videos

Manage videos within indexes.

```bash
# List videos in an index
twelvelabs videos list INDEX_ID
twelvelabs videos list INDEX_ID --table
twelvelabs videos list INDEX_ID --limit 10

# Get video details
twelvelabs videos get INDEX_ID VIDEO_ID
twelvelabs videos get INDEX_ID VIDEO_ID --table

# Upload a video (waits for indexing by default)
twelvelabs videos upload INDEX_ID /path/to/video.mp4

# Upload without waiting for indexing
twelvelabs videos upload INDEX_ID /path/to/video.mp4 --no-wait

# Force re-upload even if duplicate exists
twelvelabs videos upload INDEX_ID /path/to/video.mp4 --force-upload

# Upload with custom timeout
twelvelabs videos upload INDEX_ID /path/to/video.mp4 --timeout 300

# Delete a video
twelvelabs videos delete INDEX_ID VIDEO_ID
twelvelabs videos delete INDEX_ID VIDEO_ID --force
```

### Generate

Generate text from indexed videos using custom prompts.

```bash
# Generate text with inline prompt
twelvelabs generate text VIDEO_ID --prompt "Describe what happens in this video"

# Generate text with prompt from file
twelvelabs generate text VIDEO_ID --prompt-file review_prompt.md

# Generate text with Pegasus 1.5
twelvelabs generate text VIDEO_ID --prompt-file review_prompt.md --engine pegasus1.5 --index-id INDEX_ID

# Pipe output to file
twelvelabs generate text VIDEO_ID --prompt "List all issues" > output.txt

# Generate JSON output (validates JSON structure)
twelvelabs generate json VIDEO_ID --prompt "Return a JSON array of issues"

# Generate JSON with Pegasus 1.5
twelvelabs generate json VIDEO_ID --prompt-file review_prompt.md --engine pegasus1.5 --index-id INDEX_ID

# Generate JSON without validation
twelvelabs generate json VIDEO_ID --prompt "Return JSON" --no-validate
```

## Output Formats

All list and get commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping
- **Table** (`--table`): Human-readable tabular format

### JSON Output Example

```bash
twelvelabs indexes list --limit 2
```

### Table Output Example

```bash
twelvelabs indexes list --table --limit 5
```

## Options Reference

### Global Options

| Option | Short | Description |
|--------|-------|-------------|
| `--version` | `-v` | Show version and exit |
| `--help` | | Show help and exit |

### List Command Options

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display as table |
| `--limit` | `-l` | Maximum number of results (default: 100) |
| `--filter` | `-f` | Filter results (field:op:value) |
| `--properties` | `-p` | Comma-separated fields to include |

### Get Command Options

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display as table |
| `--properties` | `-p` | Comma-separated fields to include |

### Upload Command Options

| Option | Description |
|--------|-------------|
| `--wait/--no-wait` | Wait for indexing (default: wait) |
| `--timeout` | Timeout in seconds (default: 600) |
| `--skip-duplicate/--force-upload` | Skip if duplicate exists (default: skip) |

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/twelvelabs/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/twelvelabs/.env`:

```bash
# API Key (required)
TWELVELABS_API_KEY=your_api_key

# Optional: API base URL
TWELVELABS_BASE_URL=https://api.twelvelabs.io/v1.3
```

Get your API key from the [TwelveLabs Dashboard](https://dashboard.twelvelabs.io/).

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Complete Workflow

```bash
# 1. Authenticate
twelvelabs auth login

# 2. Create an index for a course
twelvelabs indexes create ai-102-nlp

# 3. Get the index ID
INDEX_ID=$(twelvelabs indexes list | jq -r '.[0].id')

# 4. Upload a video
twelvelabs videos upload $INDEX_ID course-clip-01.mp4

# 5. Get the video ID
VIDEO_ID=$(twelvelabs videos list $INDEX_ID | jq -r '.[0].id')

# 6. Generate analysis
twelvelabs generate text $VIDEO_ID --prompt "Describe this video" > analysis.txt

# 7. Generate JSON review
twelvelabs generate json $VIDEO_ID --prompt-file review_prompt.md > review.json
```

### Batch Video Upload

```bash
INDEX_ID="your-index-id"
for video in *.mp4; do
    echo "Uploading: $video"
    twelvelabs videos upload $INDEX_ID "$video"
done
```

### Export Index List to JSON

```bash
twelvelabs indexes list > indexes.json
```

## Models

This CLI uses Pydantic models for type-safe data handling.

### Available Models

| Model | Description | Key Fields |
|-------|-------------|------------|
| `Index` | Video index container | `id`, `index_name`, `video_count` |
| `Video` | Video in an index | `id`, `index_id`, `metadata` |
| `Task` | Upload/indexing task | `id`, `status`, `video_id` |
| `GenerateResponse` | Text generation result | `data` |

### Model Architecture

```
models/
├── __init__.py      # Exports all models
├── base.py          # CLIModel base class
└── item.py          # Index, Video, Task, GenerateResponse models
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - twelvelabs (official SDK)
  - pydantic

## License

MIT

## Additional Commands

### Cache

```bash
twelvelabs cache --help
```
