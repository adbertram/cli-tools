# Gemini CLI

## DESCRIPTION

The `gemini` CLI provides a command-line interface for Gemini API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
cd gemini
pip install -e .
```

After installation, the `gemini` command will be available in your terminal.

## Quick Start

```bash
# Get your API key from https://aistudio.google.com/apikey
gemini auth login

# Analyze a video
gemini video analyze video.mp4 --prompt "Summarize this video"

# Start a new conversation
gemini chat new "Explain quantum computing"

# Chat with a file
gemini chat new "Describe this image" --file photo.jpg
```

## Commands

### Authentication

```bash
# Login with API key
gemini auth login
gemini auth login --api-key YOUR_API_KEY

# Check authentication status
gemini auth status
gemini auth status

# Clear stored credentials
gemini auth logout
```

### Video Analysis

The primary use case for this CLI - analyze video content with AI.

```bash
# Analyze a video with inline prompt
gemini video analyze video.mp4 --prompt "Summarize this video"

# Analyze using a prompt file
gemini video analyze video.mp4 --prompt-file prompts/review.txt

# Analyze with custom model
gemini video analyze lecture.mp4 -p "What are the key topics?" --model gemini-3-pro-preview

# Using short flags: -p for prompt, -f for prompt-file
gemini video analyze demo.mp4 -f analysis_prompt.txt

# For large files, skip auto-wait for processing
gemini video analyze large.mp4 -p "Analyze audio quality" --no-wait
```

**Note**: Videos < 20MB are analyzed immediately. Videos >= 20MB are uploaded to Files API first.

### Chat & Content Generation

```bash
# Start a new chat conversation
gemini chat new "Write a haiku about AI"
gemini chat new "Explain photosynthesis" --model gemini-3-pro-preview

# Chat with a file attachment
gemini chat new "What is in this image?" --file photo.jpg
gemini chat new "Summarize this document" -f report.pdf
```

### File Operations

Manage files uploaded to Gemini Files API.

```bash
# Upload a file
gemini files upload document.pdf
gemini files upload video.mp4 --wait

# List uploaded files
gemini files list
gemini files list

# Get file metadata
gemini files get files/abc123

# Delete a file
gemini files delete files/abc123
gemini files delete files/abc123 --yes  # Skip confirmation
```

### Models

```bash
# List available models
gemini models list
gemini models list
```

### Usage Statistics

Track API usage locally with token counts and estimated costs.

```bash
# Show usage summary (last 30 days)
gemini usage show
gemini usage show

# Show last 7 days
gemini usage show --days 7

# Show breakdown by model
gemini usage show --by-model

# Show daily breakdown
gemini usage show --daily

# Clear usage data
gemini usage clear
```

**Note**: Usage is tracked locally from API responses. Estimated costs are approximate based on published pricing.

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/gemini/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/gemini/.env`:

```bash
# API Key (required)
GEMINI_API_KEY=your_api_key_here
```

Get your API key from: https://aistudio.google.com/apikey

## Common Use Cases

### Course Video Review

Analyze course videos for quality and content:

```bash
# Check audio quality
gemini video analyze m1-01.mp4 -p "Analyze the audio quality. Check for background noise, volume consistency, and clarity."

# Review presentation quality
gemini video analyze m1-02.mp4 -p "Evaluate the presentation quality. Check slide readability, visual assets, and pacing."

# Identify technical errors
gemini video analyze demo.mp4 -p "Identify any technical errors, mistakes, or issues in the demo."
```

### Batch Processing Videos

```bash
# Process all videos in a directory
for video in *.mp4; do
  gemini video analyze "$video" -p "Summarize this module" > "${video%.mp4}_summary.txt"
done
```

### Analyze with Context Files

Analyze videos alongside reference materials:

```bash
# Analyze a video with a reference document
gemini video analyze demo.mp4 -p "Compare this demo to the spec" --file spec.pdf
```

## Output Formats

- **Video/Chat commands**: Direct text output (analysis results)

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Supported File Types

The Gemini API supports the following file types:

| Category | Extensions |
|----------|------------|
| **Images** | `.png`, `.jpg`, `.jpeg`, `.webp` |
| **Video** | `.mp4`, `.mov`, `.mpeg`, `.mpg`, `.webm`, `.wmv`, `.flv`, `.3gp` |
| **Audio** | `.mp3`, `.wav`, `.flac`, `.aac`, `.m4a`, `.opus`, `.webm` |
| **Documents** | `.pdf`, `.txt`, `.md`, `.csv`, `.json`, `.xml`, `.html` |

**Note**: Word documents (`.docx`) and Excel files (`.xlsx`) are not supported. Convert to PDF or plain text first.

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - google-genai
  - typer
  - python-dotenv

## Features

- **Video Analysis**: Upload and analyze videos with AI (primary feature)
- **Chat with Files**: Generate content with file attachments (images, PDFs, etc.)
- **Content Generation**: Generate text from prompts
- **File Management**: Upload, list, and delete files via Files API
- **Model Listing**: View available Gemini models
- **Automatic File Processing**: Handles both inline (<20MB) and Files API (>=20MB) uploads
- **Table/JSON Output**: Flexible output formatting for scripting or human reading

## License

MIT

## Additional Commands

### Research

```bash
gemini research --help
```

### Cache

```bash
gemini cache --help
```
