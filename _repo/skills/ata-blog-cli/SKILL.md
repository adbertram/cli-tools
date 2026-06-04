---
name: "ata-blog-cli"
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute ATA Blog operations using the `ata-blog` CLI wrapper.
  Triggers: ata-blog, ata blog cli, ATA Blog Notion, ATA Blog WordPress, list ATA posts, publish ATA post, schedule ATA post
---

<objective>
Execute ATA Blog operations through the `ata-blog` CLI wrapper.
</objective>

<quick_start>
The `ata-blog` CLI follows this pattern:

```bash
ata-blog <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check wrapper auth | `ata-blog auth test --verbose` |
| List auth profiles | `ata-blog auth profiles list` |
| List Notion pages | `ata-blog notion-page list --table` |
| Get a Notion page | `ata-blog notion-page get PAGE_ID` |
| Update Notion status | `ata-blog notion-page update PAGE_ID --status "Draft"` |
| List WordPress posts | `ata-blog wordpress-post list --table` |
| Get a WordPress post | `ata-blog wordpress-post get POST_ID` |
| Schedule a WordPress post | `ata-blog wordpress-post schedule POST_ID --auto-schedule` |
| List WordPress pages | `ata-blog wordpress-page list --table` |
| Upload media | `ata-blog media upload image.png` |
| List categories | `ata-blog categories list --table` |
| List tags | `ata-blog tags list --table` |
| List plugins | `ata-blog wordpress-admin plugins list --table` |
</quick_start>

<essential_principles>
- ATA Blog content metadata is managed through Notion commands.
- WordPress operations are delegated through the wrapper's WordPress command groups.
- Authentication is delegated to `wordpress` and `notion`; run their auth commands if `ata-blog auth test --verbose` reports a delegated failure.
- Do not bypass this wrapper for ATA Blog project workflows unless the project instructions explicitly require a lower-level CLI.
</essential_principles>

<success_criteria>
- Command executes without error.
- Output is displayed in the requested format.
- Mutating commands are run only when explicitly requested.
</success_criteria>
