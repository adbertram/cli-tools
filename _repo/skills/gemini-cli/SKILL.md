---
name: "gemini-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute gemini operations using the `gemini` CLI tool. CLI interface for Gemini API -- chat, image generation, video analysis, deep research, file management, and usage tracking. Triggers: gemini, gemini cli, gemini chat, gemini image, gemini research, ask gemini, generate image with gemini, analyze video with gemini, gemini api usage, gemini deep research"
---

<objective>
Execute gemini operations using the `gemini` CLI. All gemini interactions should use this CLI.
</objective>

<quick_start>
The `gemini` CLI follows this pattern:
```bash
gemini <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Chat with Gemini | `gemini chat new "Your prompt here"` |
| Chat with file attachment | `gemini chat new "Describe this" --file image.jpg` |
| Generate an image | `gemini image generate "A sunset over mountains" -o sunset.png` |
| Analyze a video | `gemini video analyze video.mp4 --prompt "Summarize this"` |
| Start deep research | `gemini research start "Research topic"` |
| List models | `gemini models list --table` |
| Show API usage | `gemini usage show --table` |
| Check auth status | `gemini auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `gemini` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage API authentication (login, logout, status)
- **chat** -- Chat and content generation with optional file attachments
- **files** -- Upload, list, get, and delete files via the Gemini Files API
- **image** -- Generate images from text prompts with model/size/aspect ratio control
- **models** -- List available Gemini models
- **research** -- Run autonomous deep research tasks with citations
- **usage** -- View API usage statistics (local or cloud)
- **video** -- Analyze video files with multimodal prompts
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>

## Image Editing / Reference Images

`gemini image generate` accepts reference images via `-i / --input-image` (repeatable) for image editing and multi-image composition. Only the Nano Banana models support this (`gemini-3-pro-image-preview`, `gemini-2.5-flash-image`); Imagen models (`imagen-4.0-*`) will error if `-i` is passed. Images are sent as inline bytes to the Gemini API.

```bash
gemini image generate "make a slight variation" -i ./ref.png -o out.png
gemini image generate "compose these two scenes" -i a.png -i b.png -m gemini-2.5-flash-image
```
