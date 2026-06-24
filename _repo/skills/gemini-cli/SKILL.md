---
name: gemini-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute gemini operations using the `gemini` CLI tool.
  CLI interface for Gemini API -- chat, image generation, video analysis, deep research, file management, and usage tracking.
  Triggers: gemini, gemini cli, gemini chat, gemini image, gemini research, ask gemini, generate image with gemini, analyze video with gemini, gemini api usage, gemini deep research
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
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `gemini` command.**
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

## Deep Research (Interactions API)

`gemini research start|status|resume` drives the Gemini Deep Research Agent
through the Google GenAI **Interactions API**. As of the May 2026 breaking
change (legacy schema removed by the API on 2026-06-08), this requires:

- **`google-genai >= 2.0.0`** (the gemini CLI pins `>=2.0.0` in
  `gemini/pyproject.toml`). SDK 1.x sends the legacy Interactions schema and the
  API rejects it with HTTP 400: *"The legacy Interactions API schema is no
  longer supported … adopt the new 'steps' schema."* If `research` fails with
  that 400, the SDK is too old — reinstall with the cli-tool install script so
  `uv` resolves `google-genai >= 2.0.0`.
- The new **"steps" schema**: a completed `Interaction` exposes `steps`
  (not the legacy `outputs`) and the convenience property `output_text`. The CLI
  reads `interaction.output_text` for the final report. Streamed events use
  `event_type` values `interaction.created`, `step.start`, `step.delta`,
  `step.stop`, `interaction.status_update`, `interaction.completed`, `error`
  (replacing legacy `interaction.start` / `content.delta` / `interaction.complete`).
  `step.delta` deltas are typed by `delta.type` (`text` → `delta.text`,
  `thought_summary` → `delta.content.text`).
- Deep Research is **background-only** and **paid-tier-only**; a single task can
  run 5-20+ minutes. `gemini research start` defaults to `--stream`; callers that
  capture stdout (e.g. the ClientContentWriter `research_article.js`) use
  `--no-stream`, which prints the synthesized report to stdout and exits 0.
- Valid `--agent` values (SDK Literal): `deep-research-pro-preview-12-2025`
  (default), `deep-research-preview-04-2026`, `deep-research-max-preview-04-2026`.

Migration reference: https://ai.google.dev/gemini-api/docs/interactions-breaking-changes-may-2026

## Image Editing / Reference Images

`gemini image generate` accepts reference images via `-i / --input-image` (repeatable) for image editing and multi-image composition. Only the Nano Banana models support this (`gemini-3-pro-image-preview`, `gemini-2.5-flash-image`); Imagen models (`imagen-4.0-*`) will error if `-i` is passed. Images are sent as inline bytes to the Gemini API.

```bash
gemini image generate "make a slight variation" -i ./ref.png -o out.png
gemini image generate "compose these two scenes" -i a.png -i b.png -m gemini-2.5-flash-image
```
