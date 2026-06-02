## CLI Tool Skills

CLI-tool service skills live in this repository under `_repo/skills`.

When a task calls for a CLI-tool skill, load the matching skill from:

```text
_repo/skills/<skill-name>/SKILL.md
```

Do not load CLI-tool service skills from a user-level skill directory when this
repository contains the matching `_repo/skills/<skill-name>` bundle. Treat
`_repo/skills` as the source of truth for CLI-tool skill behavior in this
checkout.
