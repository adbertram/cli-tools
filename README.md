# CLI Tools

One repo for service-specific command-line tools. Each tool is a small Python CLI with a consistent command shape, predictable JSON-first output, shared browser/auth helpers where needed, and repo-local installation through `uv`.

## At a Glance

- 83 active CLI packages.
- One install command for any tool: `_repo/_scripts/install-cli-tool.sh <tool-folder>`.
- JSON is the default data output for automation and piping.
- Human status messages belong on stderr; stdout stays clean for data.
- Browser-backed tools use shared profile/auth helpers from `cli-tools-shared`.

## Public Use Notice

Some tools use official APIs. Others use browser automation, local app data, or
undocumented service surfaces where no public API exists. These integrations are
unofficial, may break when a service changes, and should be used only with
accounts and data you are authorized to access.

## Install a Tool

```bash
_repo/_scripts/install-cli-tool.sh <tool-folder>
```

Examples:

```bash
_repo/_scripts/install-cli-tool.sh airtable
_repo/_scripts/install-cli-tool.sh amazon
_repo/_scripts/install-cli-tool.sh wordpress
```

## Shared Building Blocks

| Component | Purpose |
| --- | --- |
| [`cli-tools-shared`](_repo/cli-tools-shared/) | Shared command, browser-auth, cache, profile, and output helpers used by tool packages. |
| [`secret-manager`](_repo/_secret-manager/) | CLI-tools Keychain helper for credentials that belong to CLI tooling. |

## Tool Catalog

### Affiliate & SEO

| Tool | Command | What it does | Main command areas |
| --- | --- | --- | --- |
| [`ahrefs`](ahrefs/) | `ahrefs` | A command-line interface for [Ahrefs](https://app.ahrefs.com) Site Audit using browser automation and internal APIs. | `auth`, `cache`, `site-audit` |
| [`amazon-associates`](amazon-associates/) | `amazon-associates` | A command-line interface for the official [Amazon Associates](https://affiliate-program.amazon.com/). | `amazon-associates`, `cache`, `program` |
| [`awin`](awin/) | `awin` | CLI for the [Awin Publisher API](https://help.awin.com/apidocs). Lists publisher accounts and advertiser programmes you have access to. | `awin`, `cache`, `programmes`, `publishers` |
| [`cj`](cj/) | `cj` | `cj` is a publisher-side command-line interface for [CJ Affiliate](https://www.cj.com/) (Commission Junction). It enables bulk discovery of CJ advertiser programs through the public REST/GraphQL API and bulk application to those programs through the publisher Marketplace UI. | `advertisers`, `cache`, `cj`, `links`, `relationships` |
| [`clickbank`](clickbank/) | `clickbank` | CLI for the documented ClickBank REST APIs at `https://api.clickbank.com/rest/1.3`. | `cache`, `clickbank`, `marketplace`, `orders`, `products`, `quickstats` |
| [`g2`](g2/) | `g2` | CLI for finding G2 products and mining negative reviews through the official G2 APIs at `https://data.g2.com`. | `cache`, `g2`, `get`, `list`, `products`, `reviews`, `search` |
| [`impact`](impact/) | `impact` | Impact.com Publisher API CLI for MediaPartner accounts. | `account`, `actions`, `ads`, `cache`, `campaigns`, `catalogs`, `clicks`, `impact`, `jobs`, `marketplace`, `reports`, `websites` |
| [`keywords`](keywords/) | `keywords` | Query autocomplete suggestions from Google, YouTube, Bing, Amazon, and DuckDuckGo for keyword research and SEO analysis. | `cache`, `keywords`, `suggest` |
| [`moz`](moz/) | `moz` | A command-line interface for the [Moz API](https://api.moz.com/api/json/). Interact with Moz. | `auth`, `cache`, `keywords` |
| [`partnerstack`](partnerstack/) | `partnerstack` | Command-line access to the [PartnerStack Partner API](https://docs.partnerstack.com/docs/partner-api). | `applications`, `auth`, `basic-status`, `cache`, `form-templates`, `login-basic`, `marketplace`, `partnerships`, `rewards` |
| [`raptive`](raptive/) | `raptive` | A command-line interface for [Raptive](https://dashboard.raptive.com) using browser automation. Interact with Raptive. | `auth`, `cache`, `dashboard`, `earnings`, `traffic` |

### Commerce & Shipping

| Tool | Command | What it does | Main command areas |
| --- | --- | --- | --- |
| [`amazon`](amazon/) | `amazon` | Read-only Amazon order evidence lookup using a persistent browser session from `cli-tools-shared`. | `amazon`, `cache`, `orders` |
| [`brickfreedom`](brickfreedom/) | `brickfreedom` | A command-line interface for [Brickfreedom](https://brickfreedom.com) using browser automation. Manage LEGO marketplace orders and tasks from the command line. | `brickfreedom`, `cache`, `order`, `task` |
| [`bricklink`](bricklink/) | `bricklink` | A command-line interface for the [Bricklink API](https://www.bricklink.com/v3/api.page). Bricklink marketplace API. | `auth`, `cache`, `catalog`, `coupon`, `inventory`, `member`, `messages`, `notification`, `order`, `refund`, `send-wanted-list-notification` |
| [`brickowl`](brickowl/) | `brickowl` | A command-line interface for the [Brick Owl API](https://api.brickowl.com/v1). Manage orders, inventory, catalog data, messages, refunds, coupons, and quotes for your Brick Owl LEGO marketplace store. | `brickowl`, `cache`, `catalog`, `coupon`, `inventory`, `issue`, `messages`, `order`, `quotes`, `refund`, `user` |
| [`cvs`](cvs/) | `cvs` | A command-line interface for the [Cvs API](https://www.cvs.com). CLI interface for CVS Health -- prescriptions, orders, and refills. | `cache`, `cvs`, `orders`, `prescriptions`, `refills` |
| [`doordash`](doordash/) | `doordash` | A command-line interface for [DoorDash](https://www.doordash.com) food ordering and delivery management. | `cache`, `doordash`, `orders`, `stores` |
| [`ebay`](ebay/) | `ebay` | A command-line interface for eBay APIs. Manage your eBay seller tools, marketplace categories, and account from the terminal. | `auth`, `cache`, `categories`, `get`, `images`, `inventory`, `list`, `listings`, `locations`, `messages`, `orders`, `payment-policies` |
| [`fedex`](fedex/) | `fedex` | A command-line interface for the [FedEx Pickup API](https://developer.fedex.com/api/en-us/catalog/pickup/v1/docs.html). Schedule, check availability, and cancel FedEx pickups. | `auth`, `cache`, `pickup` |
| [`instacart`](instacart/) | `instacart` | A command-line interface for Instacart using browser session authentication. Manage orders, view carts, and access your Instacart account from the terminal. | `auth`, `cache`, `cart`, `orders`, `user` |
| [`paypal`](paypal/) | `paypal` | Command-line interface for PayPal using the REST API. | `cache`, `payouts`, `paypal` |
| [`shippo`](shippo/) | `shippo` | A command-line interface for the [Shippo API](https://docs.goshippo.com/) - Create USPS shipping labels, get rates, and track packages. | `addresses`, `cache`, `carriers`, `labels`, `rates`, `shipments`, `shippo`, `tracking` |
| [`shopgoodwill`](shopgoodwill/) | `shopgoodwill` | A command-line interface for [ShopGoodwill.com](https://shopgoodwill.com), the online auction marketplace operated by Goodwill Industries. Search listings, view item details, and manage authentication directly from your terminal. | `auth`, `cache`, `search` |
| [`shopsalvationarmy`](shopsalvationarmy/) | `shopsalvationarmy` | Complete reference for the `shopsalvationarmy` command-line interface for searching Shop The Salvation Army auctions. | `auth`, `cache`, `search` |
| [`usps`](usps/) | `usps` | A command-line interface for the [USPS Tracking API](https://developer.usps.com/api/97). Query package tracking status for USPS shipments. | `auth`, `cache`, `tracking` |
| [`venmo`](venmo/) | `venmo` | A command-line interface for retrieving Venmo transaction history. | `cache`, `get`, `list`, `transactions`, `venmo` |

### Content, Publishing & Media

| Tool | Command | What it does | Main command areas |
| --- | --- | --- | --- |
| [`buttondown`](buttondown/) | `buttondown` | Command-line access to the Buttondown REST API for subscribers, emails, and tags. | `automations`, `buttondown`, `cache`, `emails`, `feeds`, `subscribers`, `tags` |
| [`descript`](descript/) | `descript` | CLI for managing Descript video projects via reverse-engineered internal API. Authenticates by extracting JWT tokens from the running Descript Electron app via Chrome DevTools Protocol. | `auth`, `cache`, `compositions`, `monitor`, `projects` |
| [`dev_to`](dev_to/) | `dev_to` | CLI for publishing and reading DEV Community posts through the official Forem API. | `cache`, `create`, `dev-to`, `get`, `list`, `posts`, `unpublish` |
| [`elevenlabs`](elevenlabs/) | `elevenlabs` | A command-line interface for the [ElevenLabs API](https://elevenlabs.io/docs/api-reference). It supports API-key authentication, voice discovery, model inspection, subscription quota checks, pronunciation dictionaries, and text-to-speech audio generation. | `cache`, `elevenlabs`, `models`, `pronunciation-dictionaries`, `speech`, `user`, `voices` |
| [`facebook`](facebook/) | `facebook` | A command-line tool for Facebook Marketplace, Messenger, and Groups via browser automation (playwright). | `cache`, `facebook`, `groups`, `marketplace`, `messenger` |
| [`google-lighthouse`](google-lighthouse/) | `google-lighthouse` | A standardized wrapper around Google's `lighthouse` CLI for running page audits and storing normalized audit summaries. | `audits`, `google-lighthouse` |
| [`hyvor`](hyvor/) | `hyvor` | A command-line interface for the [Hyvor Talk API](https://talk.hyvor.com/docs/api-console). Manage Hyvor Talk comments and discussions on your website. | `auth`, `cache`, `comments` |
| [`leanpub`](leanpub/) | `leanpub` | Command-line interface for the [Leanpub API](https://leanpub.com/help/api), focused on author revenue, royalties, and copies-sold stats. | `author`, `cache`, `leanpub` |
| [`linkedin`](linkedin/) | `linkedin` | Create and manage LinkedIn member and page posts through LinkedIn's official OAuth APIs only. | `auth`, `cache`, `create`, `delete`, `get`, `list`, `page`, `posts`, `readiness`, `search`, `update`, `user` |
| [`mailchimp`](mailchimp/) | `mailchimp` | A Python CLI tool for managing Mailchimp via the Marketing API v3.0. | `audiences`, `auth`, `cache`, `campaigns`, `forms`, `members`, `templates` |
| [`medium`](medium/) | `medium` | Browser-based draft creation for Medium through Medium's real web composer. | `cache`, `medium`, `posts` |
| [`photos-app`](photos-app/) | `photos-app` | Query and export photos from the macOS Photos library. Uses SQLite for fast metadata queries and AppleScript for exports (which handles iCloud downloads automatically). | `albums`, `auth`, `cache`, `photos` |
| [`pinterest`](pinterest/) | `pinterest` | Command-line access to Pinterest API v5 for authenticated account, board, and pin reads. | `account`, `boards`, `cache`, `pins`, `pinterest` |
| [`podio`](podio/) | `podio` | A command-line interface for the Podio API built with Python and Typer. Automate and manage your Podio workspace from the terminal. | `auth`, `cache`, `comment`, `conversation`, `file`, `item`, `org`, `space`, `task`, `webform`, `webhook` |
| [`powerpoint-slide-recorder`](powerpoint-slide-recorder/) | `powerpoint-slide-recorder` | Record narrated PowerPoint slides. | `record` |
| [`snagit`](snagit/) | `snagit` | A command-line interface for managing Snagit capture files (.snagx format). | `capture` |
| [`techsmith`](techsmith/) | `techsmith` | A command-line interface for [Techsmith](https://www.techsmith.com/resources/affiliate-partners/) using browser automation. Browser CLI for TechSmith affiliate workflows. | `cache`, `search`, `techsmith` |
| [`tiktok`](tiktok/) | `tiktok` | A command-line interface for downloading TikTok video transcripts using yt-dlp. | `tiktok`, `transcripts` |
| [`twelvelabs`](twelvelabs/) | `twelvelabs` | A command-line interface for the [TwelveLabs API](https://docs.twelvelabs.io) - video AI for video understanding, indexing, and text generation. | `auth`, `cache`, `generate`, `indexes`, `videos` |
| [`udemy`](udemy/) | `udemy` | Command-line access to Udemy instructor courses. Course list/get commands use the Udemy Instructor API. Course management read/update commands use an authenticated browser session because Udemy does not provide an API for those manage pages. | `cache`, `courses`, `udemy` |
| [`whisper`](whisper/) | `whisper` | A standardized command-line wrapper for [OpenAI Whisper](https://github.com/openai/whisper) speech-to-text transcription. | `transcripts` |
| [`wordpress`](wordpress/) | `wordpress` | A command-line interface for managing WordPress posts and media via the [WordPress REST API](https://developer.wordpress.org/rest-api/). Supports creating posts from manual content, DOCX files, or Markdown files with automatic image upload and link processing. | `admin`, `auth`, `cache`, `categories`, `media`, `org`, `pages`, `posts`, `tags` |
| [`x`](x/) | `x` | A command-line interface for the [X API](https://api.twitter.com). Post tweets to X.com. | `auth`, `cache`, `tweet` |
| [`youtube`](youtube/) | `youtube` | Downloads public YouTube videos/transcripts with yt-dlp and manages authenticated channel videos through the YouTube Data API v3. | `auth`, `channel`, `transcripts`, `videos` |

### Productivity & Workspace

| Tool | Command | What it does | Main command areas |
| --- | --- | --- | --- |
| [`airtable`](airtable/) | `airtable` | A command-line interface for the [Airtable API](https://airtable.com/developers/web/api/introduction). Manage Airtable records and fields from the command line. | `airtable`, `cache`, `fields`, `records`, `tables` |
| [`asana`](asana/) | `asana` | Command-line interface for the Asana API - manage projects, tasks, custom fields, and more. | `auth`, `cache`, `custom-fields`, `projects`, `sections`, `tasks`, `users`, `workspaces` |
| [`atlassian`](atlassian/) | `atlassian` | A command-line interface for [Atlassian](https://www.flexoffers.com/affiliate-programs/atlassian-affiliate-program/) using browser automation. CLI interface for Atlassian affiliate-program browser automation. | `atlassian`, `cache`, `search` |
| [`claude-code-sessions`](claude-code-sessions/) | `claude-code-sessions` | A standardized command-line wrapper for [claude](). Query and analyze Claude Code session data from ~/.claude. | `conversations`, `projects`, `search`, `sessions`, `skills`, `subagent-activity`, `timeline`, `todos`, `tool-calls` |
| [`cliclick`](cliclick/) | `cliclick` | A Python wrapper for [cliclick](https://github.com/BlueM/cliclick), the macOS command-line tool for emulating mouse and keyboard events. | `auth`, `exec`, `keyboard`, `mouse`, `scripts` |
| [`codex-sessions`](codex-sessions/) | `codex-sessions` | Query and analyze OpenAI Codex session transcripts stored under `~/.codex`. | `auth`, `conversations`, `projects`, `sessions`, `skills`, `subagent-activity`, `timeline`, `todos`, `tool-calls` |
| [`copilot`](copilot/) | `copilot` | Command-line interface for managing Microsoft Copilot Studio agents via the Dataverse API. | `auth`, `cache`, `config`, `copilot`, `whoami` |
| [`dropbox`](dropbox/) | `dropbox` | A command-line interface for [Dropbox](https://www.dropbox.com). Manage files, folders, and account information directly from your terminal. | `account`, `auth`, `cache`, `files`, `folders`, `sharing` |
| [`gemini`](gemini/) | `gemini` | A command-line interface for the [Google Gemini API](https://ai.google.dev/gemini-api/docs). Supports video analysis, content generation, and file management. | `auth`, `cache`, `chat`, `files`, `image`, `models`, `research`, `usage`, `video` |
| [`globiflow`](globiflow/) | `globiflow` | A command-line interface for [Globiflow](https://workflow-automation.podio.com) using browser automation. Globiflow workflow automation for Podio. | `cache`, `flows`, `globiflow`, `search`, `triggers` |
| [`google`](google/) | `google` | Command-line interface for Google Workspace APIs (Docs, Drive, Sheets, Gmail, Calendar, Chat), Google Analytics, Google Search Console, and Google Cloud. | `analytics`, `auth`, `cache`, `calendar`, `chat`, `cloud`, `docs`, `drive`, `gmail`, `lookerstudio`, `searchconsole`, `sheets` |
| [`grammarly`](grammarly/) | `grammarly` | Command-line interface for the Grammarly Plagiarism Detection API. | `auth`, `cache`, `docs`, `plagiarism` |
| [`imessage`](imessage/) | `imessage` | CLI tool for interacting with iMessage on macOS. Uses SQLite for fast reads from the Messages database and AppleScript for sending messages. | `contacts`, `conversations`, `messages` |
| [`lastpass`](lastpass/) | `lastpass` | A standardized command-line wrapper for [lpass](https://github.com/lastpass/lastpass-cli) (LastPass CLI). | `auth`, `cache`, `items`, `sync` |
| [`manus`](manus/) | `manus` | Complete reference for the `manus` command-line interface for interacting with Manus AI services. | `auth`, `cache`, `task` |
| [`mindmeister`](mindmeister/) | `mindmeister` | A command-line interface for the [MindMeister API](https://developers.mindmeister.com/docs) - manage mind maps from the terminal. | `auth`, `cache`, `ideas`, `maps` |
| [`msword`](msword/) | `msword` | Read Word documents, convert to Markdown, and extract comments with context. | `docs`, `msword` |
| [`notifier`](notifier/) | `notifier` | A command-line wrapper for [terminal-notifier](https://github.com/julienXX/terminal-notifier) to send macOS desktop notifications. | Core commands |
| [`notion`](notion/) | `notion` | Complete reference for the `notion` command-line interface for querying and managing Notion databases and pages. | `auth`, `cache`, `comments`, `database`, `field`, `pages` |
| [`onedrive`](onedrive/) | `onedrive` | A command-line interface for [OneDrive for Business](https://learn.microsoft.com/en-us/graph/onedrive-concept-overview) via Microsoft Graph API. | `auth`, `cache`, `drives`, `folders`, `items`, `link` |
| [`reminders`](reminders/) | `reminders` | Command-line interface for managing macOS Reminders using the EventKit framework. | `lists` |
| [`slack`](slack/) | `slack` | A command-line interface for the [Slack API](https://docs.slack.dev). Manage channels, messages, users, files, notifications, and more from the terminal. | `auth`, `cache`, `canvas`, `channels`, `dm`, `files`, `messages`, `notifications`, `reminders`, `users` |
| [`things`](things/) | `things` | A command-line interface for Things 3 on macOS. Uses SQLite for fast reads and AppleScript for reliable writes. | `areas`, `projects`, `tags`, `todos` |

### Infrastructure & Automation

| Tool | Command | What it does | Main command areas |
| --- | --- | --- | --- |
| [`cloudflare`](cloudflare/) | `cloudflare` | A command-line interface for the [Cloudflare API](https://developers.cloudflare.com/api/). Manage Cloudflare zones and cache. | `access-rules`, `auth`, `cache`, `dns`, `zones` |
| [`cryptocom`](cryptocom/) | `cryptocom` | Command-line access to the Crypto.com Exchange REST API for public market data and authenticated account data. | `account`, `book`, `cache`, `candlesticks`, `cryptocom`, `instruments`, `ticker`, `trades` |
| [`freshbooks`](freshbooks/) | `freshbooks` | Complete reference for the `freshbooks` command-line interface for managing FreshBooks accounting data. | `auth`, `cache`, `customer`, `invoice` |
| [`n8n`](n8n/) | `n8n` | Manage n8n server - nodes, executions, credentials, data tables, and logs. | `cache`, `credentials`, `data-tables`, `executions`, `n8n`, `nodes`, `server`, `workflows` |

### Consumer Services & Devices

| Tool | Command | What it does | Main command areas |
| --- | --- | --- | --- |
| [`apple`](apple/) | `apple` | Read-only Apple purchase and subscription history lookup using the private `reportaproblem.apple.com/api/purchase/search` endpoint with a persisted Apple browser session. | `apple`, `cache`, `purchases` |
| [`fitnesspal`](fitnesspal/) | `fitnesspal` | A read-only command-line interface for [MyFitnessPal](https://www.myfitnesspal.com/). View your diary, exercises, measurements, reports, food database, recipes, and saved meals. | `cache`, `diary`, `exercises`, `fitnesspal`, `food`, `meals`, `measurements`, `recipes`, `reports` |
| [`kick`](kick/) | `kick` | A command-line interface for [Kick.co](https://www.kick.co) - the self-driving bookkeeping platform. | `auth`, `cache`, `categories`, `clients`, `entities`, `integrations`, `rule-groups`, `statistics`, `transactions`, `workspaces` |
| [`monarch`](monarch/) | `monarch` | A command-line interface for [Monarch Money](https://monarchmoney.com) personal finance. | `accounts`, `auth`, `budgets`, `cache`, `cashflow`, `categories`, `category-groups`, `institutions`, `merchants`, `rules`, `tags`, `transactions` |
| [`ring`](ring/) | `ring` | A command-line interface for [Ring](https://ring.com/) doorbells, cameras, chimes, and intercoms. Wraps the [`ring-doorbell`](https://python-ring-doorbell.readthedocs.io/) Python library -- same library that powers the Home Assistant integration. | `auth`, `cache`, `chime`, `devices`, `events`, `lights`, `motion`, `siren`, `snapshot`, `volume` |
| [`roomba`](roomba/) | `roomba` | A command-line interface to control iRobot Roomba vacuums using the [roombapy](https://github.com/pschmitt/roombapy) library. | `auth`, `cache`, `control`, `robots`, `status` |

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
```

## Add or Refresh a Tool

```bash
_repo/_scripts/install-cli-tool.sh <tool-folder>
```

Each tool keeps its own package metadata, README, and tests. Use the shared runtime library for common auth, output, cache, and browser-session behavior.
