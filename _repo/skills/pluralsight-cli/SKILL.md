---
name: pluralsight-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Pluralsight operations using the `pluralsight` CLI tool.
  CLI interface for Pluralsight.
  Triggers: pluralsight, pluralsight cli
---

<objective>
Execute Pluralsight operations using the `pluralsight` CLI. All Pluralsight interactions should use this CLI.
</objective>

<quick_start>
The `pluralsight` CLI follows this pattern:
```bash
pluralsight <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Remove all cached responses | `pluralsight cache clear` |
| Get a single catalog entry by product id | `pluralsight get <ITEM_ID>` |
| List newest catalog entries across the public Pluralsight library | `pluralsight list` |
| Keyword search over the public Pluralsight catalog | `pluralsight search <QUERY>` |
| Return query suggestions from the catalog search engine | `pluralsight suggestions <QUERY>` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `pluralsight` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `pluralsight --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **cache** -- Manage response cache (subcommands: clear)
- **get** -- Get a single catalog entry by product id
- **list** -- List newest catalog entries across the public Pluralsight library
- **search** -- Keyword search over the public Pluralsight catalog
- **suggestions** -- Return query suggestions from the catalog search engine
</principle>

<principle name="Catalog API Quirks (verified live 2026-08-23)">
- The CLI needs NO credentials. The endpoint is the public Cludo site-search
  behind pluralsight.com/browse, authorized by a static SiteKey header baked
  into Pluralsight's own pages. Do not look for or create credentials.
- Category mapping: `path` and `skill` both map to index token `skill`.
  Default content types mirror pluralsight.com/browse: courses, labs,
  certificates, skills. `-c all` widens to every indexed type including blogs.
- Tags: the index has no dedicated tag taxonomy. Record `tags` = subjects
  (`course-category`) + role tags (`roles`). On paths/skills, the raw
  "Skill Levels" field mirrors the title; the CLI nulls non-level values.
- `publish-date` parses to YYYY-MM-DD; some entries (many paths) have no
  publish date and return `null`. Ratings can be absent on brand-new items.
- `get <prodId>` uses a server-side `prodId:<id>` query; the prodId is the
  course URL slug (e.g. `docker-developers-docker-foundations`).
- If a command errors right after install with a legacy-profile message under
  `~/.local/share/cli-tools/pluralsight/`, remove any leftover `.profiles/`
  directory there; canonical auth profiles live in `authentication_profiles/`.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`pluralsight --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
