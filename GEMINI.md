# CLI Tools Agent Instructions

## Project Purpose

cli-tools is the central source tree for service-specific Python CLIs built for AI agents and humans. It exists to expose external services through documented, JSON-first, testable command surfaces instead of ad hoc browser clicks or one-off scripts.

## General Guidance

Use this directory as the project workspace for tasks that match the purpose above. Keep durable, project-specific instructions here and move reusable procedures into skills.

## CLI Tool Skills

Always load and follow the repo-owned `cli-tool` skill before creating,
updating, testing, listing, troubleshooting, or running any CLI tool in this
checkout:

```text
_repo/skills/cli-tool/SKILL.md
```

CLI-tool service skills live in this repository under `_repo/skills`.

When a task calls for a CLI-tool skill, load the matching skill from:

```text
_repo/skills/<skill-name>/SKILL.md
```

Do not load CLI-tool service skills from a user-level skill directory when this
repository contains the matching `_repo/skills/<skill-name>` bundle. Treat
`_repo/skills` as the source of truth for CLI-tool skill behavior in this
checkout.
