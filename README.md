# CLI Tools

Service-specific command-line tools designed for AI agents and still practical
for humans at a terminal.

This repo contains small Python CLIs for APIs, browser-backed services, local
apps, and automation targets. The tools are built around predictable command
shapes, JSON-first output, clean stderr/stdout separation, shared auth helpers,
and repo-local agent skill files so an agent can inspect command usage before it
runs anything.

## Why This Exists

AI agents are much more reliable when service operations are exposed as narrow,
documented commands instead of ad-hoc browser clicks or one-off scripts. These
CLIs give agents a stable interface for common service tasks while keeping the
same commands available for direct interactive use.

This is not a collection of unrelated scripts. The repo defines a repeatable
way to build Python CLI tools for agent use. Each tool adapts one service,
application, API, browser workflow, or existing command-line program into a
single predictable command surface that agents can inspect, call, cache, and
verify consistently.

## What's Included

- 83 active CLI packages.
- Repo-local service skills in `_repo/skills/<tool>-cli/`.
- Repo-local framework skills and expert agents for building and maintaining
  the tools.
- Generated `usage.json` command maps for agent command planning.
- Shared auth, cache, profile, browser-session, and output helpers.
- A Keychain-backed secret manager for CLI credentials.
- One install command per tool.

## Quick Start

Install a tool from its folder name:

```bash
_repo/_scripts/install-cli-tool.sh <tool-folder>
```

Examples:

```bash
_repo/_scripts/install-cli-tool.sh airtable
_repo/_scripts/install-cli-tool.sh amazon
_repo/_scripts/install-cli-tool.sh wordpress
```

Then run the installed command:

```bash
airtable --help
amazon orders list --table
wordpress posts list --limit 5
```

## Design Principles

- Commands should be predictable and discoverable through `--help`.
- JSON is the default data output for automation and piping.
- Human status messages belong on stderr; stdout stays clean for data.
- Browser-backed tools use shared profile/auth helpers from `cli-tools-shared`.
- API-backed tools use the same profile, cache, auth, and output patterns.
- Credentials belong in the CLI-tools secret manager or tool-owned profile
  state, never in source files.
- Agent-facing usage guidance lives next to the repo in `_repo/skills`.

## Architecture

The repo is organized around a shared CLI framework, not around one-off command
scripts. Each service folder is an installable Python package with a consistent
entry point, command structure, output contract, and runtime state layout.

At a high level, a tool is usually one of these adapters:

- **API adapter:** wraps a public or private HTTP API in stable CLI commands.
- **Browser adapter:** wraps a browser-authenticated workflow behind a CLI.
- **Local app/data adapter:** wraps local app data, SQLite stores, AppleScript,
  or operating-system automation.
- **CLI adapter:** wraps an existing command-line program with a more predictable
  command shape and output contract for agents.

The common parts live in [`cli-tools-shared`](_repo/cli-tools-shared/). Tools
reuse that package for the behaviors agents need to be consistent across
services:

- command app construction and standard command conventions
- JSON-first output and table output for interactive use
- authentication profile layout under `~/.local/share/cli-tools/<tool>`
- shared cache commands and cache behavior
- browser session/profile handling for browser-backed tools
- reusable auth verification and status checks

This means an agent does not need to relearn each integration from scratch. Once
it knows the framework, it can expect familiar command groups such as `auth`,
`cache`, `list`, and `get`, inspect the tool-specific `usage.json`, and then run
the service operation through one predictable interface.

### Caching

Tools that read from APIs or browser-backed service surfaces use a common cache
pattern. Cacheable commands keep network and browser reads repeatable, reduce
unnecessary service calls, and make agent workflows easier to debug. The exact
cache keys and freshness rules are tool-specific, but the operational shape is
consistent: tools expose cache management commands, support fresh reads where
needed, and keep cached data out of stdout unless the command is returning data.

### Browser Automation

Browser-backed tools use the shared browser/profile architecture instead of
custom browser code per service. The shared package owns the common lifecycle:
persistent browser profiles, auth markers, session checks, storage-state
handling, and status verification. Individual tools provide the service-specific
URLs and selectors needed to confirm authentication or collect data.

That separation keeps browser automation predictable for agents: the tool owns
the service workflow, while the shared package owns the browser session and auth
plumbing.

## Public Use Notice

Some tools use official APIs. Others use browser automation, local app data, or
undocumented service surfaces where no public API exists. These integrations are
unofficial, may break when a service changes, and should be used only with
accounts and data you are authorized to access.

## Shared Building Blocks

| Component | Purpose |
| --- | --- |
| [`cli-tools-shared`](_repo/cli-tools-shared/) | Shared command, browser-auth, cache, profile, and output helpers used by tool packages. |
| [`secret-manager`](_repo/_secret-manager/) | CLI-tools Keychain helper for credentials that belong to CLI tooling. |
| [`skills`](_repo/skills/) | Agent-facing CLI skill bundles. Each installable tool has a matching `<tool>-cli` skill with command guidance and a `usage.json` command tree. Framework support skills such as `cli-tool` and `cli-tool-secrets` also live here. |
| [`agents`](_repo/agents/) | Repo-owned expert agent definitions for maintaining CLI tools across agent harnesses. |

## Secret Manager

CLI credentials belong in the repo-owned secret manager, not in source files,
checked-in `.env` files, shell history, or general agent instructions. The
helper is backed by a dedicated macOS Keychain file:

```text
~/.local/share/cli-tools/cli-tools.keychain-db
```

The helper script is:

```text
_repo/_secret-manager/secrets.sh
```

Secrets are stored in the `cli-tools` Keychain service namespace. Canonical
names use this format:

```text
<cli-tool>-<type>
```

Use the explicit `--tool` and `--type` form when storing new values so the helper
builds the canonical name:

```bash
printf '%s' "$SECRET_VALUE" | _repo/_secret-manager/secrets.sh set --tool <cli-tool> --type <type>
```

Common operations:

```bash
_repo/_secret-manager/secrets.sh set --tool <cli-tool> --type <type>
_repo/_secret-manager/secrets.sh get <cli-tool>-<type>
_repo/_secret-manager/secrets.sh has <cli-tool>-<type>
_repo/_secret-manager/secrets.sh list
_repo/_secret-manager/secrets.sh delete <cli-tool>-<type>
```

The secret manager is for CLI tool code and CLI-tool skills only. It should not
be used as a general project secret store or by unrelated automation. Tool
profile files may reference secrets with `secret://...` placeholders; the
runtime resolves those through this helper instead of storing sensitive values
in the profile file.

See [`_repo/_secret-manager/README.md`](_repo/_secret-manager/README.md) for
remote-host mode, Keychain access policy, and import/export behavior.

## Agent Skills

This repo includes agent skill bundles for CLI operations under `_repo/skills`.
For a tool folder named `<tool>`, the matching service-operation skill is usually:

```text
_repo/skills/<tool>-cli/SKILL.md
```

Each skill tells an agent when to use the CLI, how to call it, and where to find
the tool's generated `usage.json` command reference. Agents should load the
repo-local skill before running service operations for that CLI. Skill bundles
are documentation and orchestration guidance only; they do not replace the
installable CLI package under `<tool>/`.

Two framework support skills also live in `_repo/skills`:

- `_repo/skills/cli-tool/` is the framework skill for creating, testing,
  updating, removing, and validating CLI tools in this repo.
- `_repo/skills/cli-tool-secrets/` documents the CLI-tools secret-manager
  workflow for reusable CLI credentials.

These support skills intentionally do not map to installable service commands.
They describe how to build and maintain the CLI framework itself.

## Expert Agent

The CLI tool expert agent is repo-owned so it can evolve with the framework
instead of drifting in user-level agent folders:

```text
_repo/agents/cli-tool-expert.toml  # TOML agent format
_repo/agents/cli-tool-expert.md    # Markdown agent format
```

User-level harness folders should symlink to those repo files. That keeps normal
agent invocation working while making the repo the source of truth:

```text
~/.codex/agents/cli-tool-expert.toml -> <cli-tools-root>/_repo/agents/cli-tool-expert.toml
~/.claude/agents/cli-tool-expert.md  -> <cli-tools-root>/_repo/agents/cli-tool-expert.md
```

### `usage.json`

`usage.json` is the structured command map for a CLI. It lets an agent inspect
the tool's command tree without guessing syntax from memory. Before running a
command, the agent should use the matching skill and `usage.json` to confirm:

- available command groups and subcommands
- positional arguments and whether they are required
- options, short aliases, defaults, and value types
- examples from the live CLI help when available
- `usage_instructions` that explain when to use each command and how to combine
  important flags

The file is organized as a root object for the CLI, with nested command groups
and leaf commands. `usage_instructions` should exist at the root, group, and
leaf-command levels when the command needs decision guidance beyond the raw help
text.

### Creating or Refreshing `usage.json`

Create or refresh `usage.json` whenever a CLI is added, command names change,
flags are added or removed, defaults change, or examples in `--help` change.

1. Install the CLI from the repo:

   ```bash
   _repo/_scripts/install-cli-tool.sh <tool-folder>
   ```

2. Read the live command help recursively:

   ```bash
   <tool> --help
   <tool> <group> --help
   <tool> <group> <command> --help
   ```

3. Write the command tree to:

   ```text
   _repo/skills/<tool>-cli/usage.json
   ```

4. Include the command structure, arguments, options, examples, and
   `usage_instructions`. Keep command paths exactly as the CLI exposes them;
   for example, document `auth profiles list`, not a flattened `profiles list`.

5. Update `_repo/skills/<tool>-cli/SKILL.md` if the tool's purpose, major
   command groups, trigger phrases, or required operating rules changed.

6. Verify by checking that every documented command path still appears in live
   help and that the skill references the current `usage.json`.

Most service skills in `_repo/skills` must have a corresponding installable CLI
package. The explicit exceptions are framework support skills that maintain the
repo itself, currently `cli-tool` and `cli-tool-secrets`.

## Tool Catalog

### Affiliate & SEO

| Tool | Command | What it does |
| --- | --- | --- |
| [`ahrefs`](ahrefs/) | `ahrefs` | A command-line interface for [Ahrefs](https://app.ahrefs.com) Site Audit using browser automation and internal APIs. |
| [`amazon-associates`](amazon-associates/) | `amazon-associates` | A command-line interface for the official [Amazon Associates](https://affiliate-program.amazon.com/). |
| [`awin`](awin/) | `awin` | CLI for the [Awin Publisher API](https://help.awin.com/apidocs). Lists publisher accounts and advertiser programmes you have access to. |
| [`cj`](cj/) | `cj` | `cj` is a publisher-side command-line interface for [CJ Affiliate](https://www.cj.com/) (Commission Junction). It enables bulk discovery of CJ advertiser programs through the public REST/GraphQL API and bulk application to those programs through the publisher Marketplace UI. |
| [`clickbank`](clickbank/) | `clickbank` | CLI for the documented ClickBank REST APIs at `https://api.clickbank.com/rest/1.3`. |
| [`g2`](g2/) | `g2` | CLI for finding G2 products and mining negative reviews through the official G2 APIs at `https://data.g2.com`. |
| [`impact`](impact/) | `impact` | Impact.com Publisher API CLI for MediaPartner accounts. |
| [`keywords`](keywords/) | `keywords` | Query autocomplete suggestions from Google, YouTube, Bing, Amazon, and DuckDuckGo for keyword research and SEO analysis. |
| [`moz`](moz/) | `moz` | A command-line interface for the [Moz API](https://api.moz.com/api/json/). Interact with Moz. |
| [`partnerstack`](partnerstack/) | `partnerstack` | Command-line access to the [PartnerStack Partner API](https://docs.partnerstack.com/docs/partner-api). |
| [`raptive`](raptive/) | `raptive` | A command-line interface for [Raptive](https://dashboard.raptive.com) using browser automation. Interact with Raptive. |

### Commerce & Shipping

| Tool | Command | What it does |
| --- | --- | --- |
| [`amazon`](amazon/) | `amazon` | Read-only Amazon order evidence lookup using a persistent browser session from `cli-tools-shared`. |
| [`brickfreedom`](brickfreedom/) | `brickfreedom` | A command-line interface for [Brickfreedom](https://brickfreedom.com) using browser automation. Manage LEGO marketplace orders and tasks from the command line. |
| [`bricklink`](bricklink/) | `bricklink` | A command-line interface for the [Bricklink API](https://www.bricklink.com/v3/api.page). Bricklink marketplace API. |
| [`brickowl`](brickowl/) | `brickowl` | A command-line interface for the [Brick Owl API](https://api.brickowl.com/v1). Manage orders, inventory, catalog data, messages, refunds, coupons, and quotes for your Brick Owl LEGO marketplace store. |
| [`cvs`](cvs/) | `cvs` | A command-line interface for the [Cvs API](https://www.cvs.com). CLI interface for CVS Health -- prescriptions, orders, and refills. |
| [`doordash`](doordash/) | `doordash` | A command-line interface for [DoorDash](https://www.doordash.com) food ordering and delivery management. |
| [`ebay`](ebay/) | `ebay` | A command-line interface for eBay APIs. Manage your eBay seller tools, marketplace categories, and account from the terminal. |
| [`fedex`](fedex/) | `fedex` | A command-line interface for the [FedEx Pickup API](https://developer.fedex.com/api/en-us/catalog/pickup/v1/docs.html). Schedule, check availability, and cancel FedEx pickups. |
| [`instacart`](instacart/) | `instacart` | A command-line interface for Instacart using browser session authentication. Manage orders, view carts, and access your Instacart account from the terminal. |
| [`paypal`](paypal/) | `paypal` | Command-line interface for PayPal using the REST API. |
| [`shippo`](shippo/) | `shippo` | A command-line interface for the [Shippo API](https://docs.goshippo.com/) - Create USPS shipping labels, get rates, and track packages. |
| [`shopgoodwill`](shopgoodwill/) | `shopgoodwill` | A command-line interface for [ShopGoodwill.com](https://shopgoodwill.com), the online auction marketplace operated by Goodwill Industries. Search listings, view item details, and manage authentication directly from your terminal. |
| [`shopsalvationarmy`](shopsalvationarmy/) | `shopsalvationarmy` | Complete reference for the `shopsalvationarmy` command-line interface for searching Shop The Salvation Army auctions. |
| [`usps`](usps/) | `usps` | A command-line interface for the [USPS Tracking API](https://developer.usps.com/api/97). Query package tracking status for USPS shipments. |
| [`venmo`](venmo/) | `venmo` | A command-line interface for retrieving Venmo transaction history. |

### Content, Publishing & Media

| Tool | Command | What it does |
| --- | --- | --- |
| [`buttondown`](buttondown/) | `buttondown` | Command-line access to the Buttondown REST API for subscribers, emails, and tags. |
| [`descript`](descript/) | `descript` | CLI for managing Descript video projects via reverse-engineered internal API. Authenticates by extracting JWT tokens from the running Descript Electron app via Chrome DevTools Protocol. |
| [`dev_to`](dev_to/) | `dev_to` | CLI for publishing and reading DEV Community posts through the official Forem API. |
| [`elevenlabs`](elevenlabs/) | `elevenlabs` | A command-line interface for the [ElevenLabs API](https://elevenlabs.io/docs/api-reference). It supports API-key authentication, voice discovery, model inspection, subscription quota checks, pronunciation dictionaries, and text-to-speech audio generation. |
| [`facebook`](facebook/) | `facebook` | A command-line tool for Facebook Marketplace, Messenger, and Groups via browser automation (playwright). |
| [`google-lighthouse`](google-lighthouse/) | `google-lighthouse` | A standardized wrapper around Google's `lighthouse` CLI for running page audits and storing normalized audit summaries. |
| [`hyvor`](hyvor/) | `hyvor` | A command-line interface for the [Hyvor Talk API](https://talk.hyvor.com/docs/api-console). Manage Hyvor Talk comments and discussions on your website. |
| [`leanpub`](leanpub/) | `leanpub` | Command-line interface for the [Leanpub API](https://leanpub.com/help/api), focused on author revenue, royalties, and copies-sold stats. |
| [`linkedin`](linkedin/) | `linkedin` | Create and manage LinkedIn member and page posts through LinkedIn's official OAuth APIs only. |
| [`mailchimp`](mailchimp/) | `mailchimp` | A Python CLI tool for managing Mailchimp via the Marketing API v3.0. |
| [`medium`](medium/) | `medium` | Browser-based draft creation for Medium through Medium's real web composer. |
| [`photos-app`](photos-app/) | `photos-app` | Query and export photos from the macOS Photos library. Uses SQLite for fast metadata queries and AppleScript for exports (which handles iCloud downloads automatically). |
| [`pinterest`](pinterest/) | `pinterest` | Command-line access to Pinterest API v5 for authenticated account, board, and pin reads. |
| [`podio`](podio/) | `podio` | A command-line interface for the Podio API built with Python and Typer. Automate and manage your Podio workspace from the terminal. |
| [`powerpoint-slide-recorder`](powerpoint-slide-recorder/) | `powerpoint-slide-recorder` | Record narrated PowerPoint slides. |
| [`snagit`](snagit/) | `snagit` | A command-line interface for managing Snagit capture files (.snagx format). |
| [`techsmith`](techsmith/) | `techsmith` | A command-line interface for [Techsmith](https://www.techsmith.com/resources/affiliate-partners/) using browser automation. Browser CLI for TechSmith affiliate workflows. |
| [`tiktok`](tiktok/) | `tiktok` | A command-line interface for downloading TikTok video transcripts using yt-dlp. |
| [`twelvelabs`](twelvelabs/) | `twelvelabs` | A command-line interface for the [TwelveLabs API](https://docs.twelvelabs.io) - video AI for video understanding, indexing, and text generation. |
| [`udemy`](udemy/) | `udemy` | Command-line access to Udemy instructor courses. Course list/get commands use the Udemy Instructor API. Course management read/update commands use an authenticated browser session because Udemy does not provide an API for those manage pages. |
| [`whisper`](whisper/) | `whisper` | A standardized command-line wrapper for [OpenAI Whisper](https://github.com/openai/whisper) speech-to-text transcription. |
| [`wordpress`](wordpress/) | `wordpress` | A command-line interface for managing WordPress posts and media via the [WordPress REST API](https://developer.wordpress.org/rest-api/). Supports creating posts from manual content, DOCX files, or Markdown files with automatic image upload and link processing. |
| [`x`](x/) | `x` | A command-line interface for the [X API](https://api.twitter.com). Post tweets to X.com. |
| [`youtube`](youtube/) | `youtube` | Downloads public YouTube videos/transcripts with yt-dlp and manages authenticated channel videos through the YouTube Data API v3. |

### Productivity & Workspace

| Tool | Command | What it does |
| --- | --- | --- |
| [`airtable`](airtable/) | `airtable` | A command-line interface for the [Airtable API](https://airtable.com/developers/web/api/introduction). Manage Airtable records and fields from the command line. |
| [`asana`](asana/) | `asana` | Command-line interface for the Asana API - manage projects, tasks, custom fields, and more. |
| [`atlassian`](atlassian/) | `atlassian` | A command-line interface for [Atlassian](https://www.flexoffers.com/affiliate-programs/atlassian-affiliate-program/) using browser automation. CLI interface for Atlassian affiliate-program browser automation. |
| [`claude-code-sessions`](claude-code-sessions/) | `claude-code-sessions` | A standardized command-line wrapper for [claude](). Query and analyze Claude Code session data from ~/.claude. |
| [`cliclick`](cliclick/) | `cliclick` | A Python wrapper for [cliclick](https://github.com/BlueM/cliclick), the macOS command-line tool for emulating mouse and keyboard events. |
| [`codex-sessions`](codex-sessions/) | `codex-sessions` | Query and analyze OpenAI Codex session transcripts stored under `~/.codex`. |
| [`copilot`](copilot/) | `copilot` | Command-line interface for managing Microsoft Copilot Studio agents via the Dataverse API. |
| [`dropbox`](dropbox/) | `dropbox` | A command-line interface for [Dropbox](https://www.dropbox.com). Manage files, folders, and account information directly from your terminal. |
| [`gemini`](gemini/) | `gemini` | A command-line interface for the [Google Gemini API](https://ai.google.dev/gemini-api/docs). Supports video analysis, content generation, and file management. |
| [`globiflow`](globiflow/) | `globiflow` | A command-line interface for [Globiflow](https://workflow-automation.podio.com) using browser automation. Globiflow workflow automation for Podio. |
| [`google`](google/) | `google` | Command-line interface for Google Workspace APIs (Docs, Drive, Sheets, Gmail, Calendar, Chat), Google Analytics, Google Search Console, and Google Cloud. |
| [`grammarly`](grammarly/) | `grammarly` | Command-line interface for the Grammarly Plagiarism Detection API. |
| [`imessage`](imessage/) | `imessage` | CLI tool for interacting with iMessage on macOS. Uses SQLite for fast reads from the Messages database and AppleScript for sending messages. |
| [`lastpass`](lastpass/) | `lastpass` | A standardized command-line wrapper for [lpass](https://github.com/lastpass/lastpass-cli) (LastPass CLI). |
| [`manus`](manus/) | `manus` | Complete reference for the `manus` command-line interface for interacting with Manus AI services. |
| [`mindmeister`](mindmeister/) | `mindmeister` | A command-line interface for the [MindMeister API](https://developers.mindmeister.com/docs) - manage mind maps from the terminal. |
| [`msword`](msword/) | `msword` | Read Word documents, convert to Markdown, and extract comments with context. |
| [`notifier`](notifier/) | `notifier` | A command-line wrapper for [terminal-notifier](https://github.com/julienXX/terminal-notifier) to send macOS desktop notifications. |
| [`notion`](notion/) | `notion` | Complete reference for the `notion` command-line interface for querying and managing Notion databases and pages. |
| [`onedrive`](onedrive/) | `onedrive` | A command-line interface for [OneDrive for Business](https://learn.microsoft.com/en-us/graph/onedrive-concept-overview) via Microsoft Graph API. |
| [`reminders`](reminders/) | `reminders` | Command-line interface for managing macOS Reminders using the EventKit framework. |
| [`slack`](slack/) | `slack` | A command-line interface for the [Slack API](https://docs.slack.dev). Manage channels, messages, users, files, notifications, and more from the terminal. |
| [`things`](things/) | `things` | A command-line interface for Things 3 on macOS. Uses SQLite for fast reads and AppleScript for reliable writes. |

### Infrastructure & Automation

| Tool | Command | What it does |
| --- | --- | --- |
| [`cloudflare`](cloudflare/) | `cloudflare` | A command-line interface for the [Cloudflare API](https://developers.cloudflare.com/api/). Manage Cloudflare zones and cache. |
| [`cryptocom`](cryptocom/) | `cryptocom` | Command-line access to the Crypto.com Exchange REST API for public market data and authenticated account data. |
| [`freshbooks`](freshbooks/) | `freshbooks` | Complete reference for the `freshbooks` command-line interface for managing FreshBooks accounting data. |
| [`n8n`](n8n/) | `n8n` | Manage n8n server - nodes, executions, credentials, data tables, and logs. |

### Consumer Services & Devices

| Tool | Command | What it does |
| --- | --- | --- |
| [`apple`](apple/) | `apple` | Read-only Apple purchase and subscription history lookup using the private `reportaproblem.apple.com/api/purchase/search` endpoint with a persisted Apple browser session. |
| [`fitnesspal`](fitnesspal/) | `fitnesspal` | A read-only command-line interface for [MyFitnessPal](https://www.myfitnesspal.com/). View your diary, exercises, measurements, reports, food database, recipes, and saved meals. |
| [`kick`](kick/) | `kick` | A command-line interface for [Kick.co](https://www.kick.co) - the self-driving bookkeeping platform. |
| [`monarch`](monarch/) | `monarch` | A command-line interface for [Monarch Money](https://monarchmoney.com) personal finance. |
| [`ring`](ring/) | `ring` | A command-line interface for [Ring](https://ring.com/) doorbells, cameras, chimes, and intercoms. Wraps the [`ring-doorbell`](https://python-ring-doorbell.readthedocs.io/) Python library -- same library that powers the Home Assistant integration. |
| [`roomba`](roomba/) | `roomba` | A command-line interface to control iRobot Roomba vacuums using the [roombapy](https://github.com/pschmitt/roombapy) library. |

## Operating Standards

These rules are intentionally short here; individual tools keep service-specific details in their own README files.

- Data commands output JSON by default. Do not add redundant `--json` flags.
- `get` commands return the resource object. `list` commands return the resource array.
- stdout is for data only. stderr is for progress, warnings, and confirmations.
- API-backed tools expose `auth login`, `auth status`, and `auth logout` when authentication is required.
- Browser-backed tools should reuse shared browser/profile helpers instead of custom browser lifecycle code.
- Credentials belong in the CLI-tools secret manager or the tool-owned profile/config path, never in source files.

## User Profile Storage

Each tool's user profile folder is `~/.local/share/cli-tools/<tool>`. Non-authentication configuration for the tool lives in `~/.local/share/cli-tools/<tool>/.env`.

Authentication-related data lives under `~/.local/share/cli-tools/<tool>/authentication_profiles/<profile>/`, including the profile `.env`, OAuth tokens, API keys, browser session data, auth markers, and auth-tied cache/state.

## Repository Layout

```text
cli-tools/
  <tool>/                  # one installable CLI package
    pyproject.toml
    <tool>_cli/
    README.md
  _repo/cli-tools-shared/        # shared runtime library
  _repo/_secret-manager/          # credential helper for CLI tooling
  _repo/agents/                   # repo-owned expert agent definitions
    cli-tool-expert.toml
    cli-tool-expert.md
  _repo/skills/                   # agent-facing skill bundles for CLI usage
    cli-tool/
    cli-tool-secrets/
    <tool>-cli/
      SKILL.md
      usage.json
```

## Add or Refresh a Tool

```bash
_repo/_scripts/install-cli-tool.sh <tool-folder>
```

Each tool keeps its own package metadata, README, tests, and matching `_repo/skills/<tool>-cli/` agent skill. Use the shared runtime library for common auth, output, cache, and browser-session behavior.
