---
name: "facebook-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute facebook operations using the `facebook` CLI tool. Facebook CLI via Playwright browser automation -- Marketplace search, Messenger conversations, Groups posts, and caching. Triggers: facebook, facebook cli, facebook marketplace, facebook messenger, facebook groups, search facebook marketplace, facebook messages, send facebook message, facebook message requests, facebook group posts, read facebook group, list facebook groups"
---

<objective>
Execute facebook operations using the `facebook` CLI. All facebook interactions should use this CLI.
</objective>

<quick_start>
The `facebook` CLI follows this pattern:
```bash
facebook <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search Marketplace | `facebook marketplace list --query "LEGO" --table` |
| Browse Today's picks | `facebook marketplace list --table` |
| Get listing details | `facebook marketplace get ITEM_ID` |
| List group posts | `facebook groups list GROUP_ID --table` |
| Get a group post | `facebook groups get GROUP_ID/posts/POST_ID` |
| List conversations | `facebook messenger list --table` |
| Read messages | `facebook messenger get CONVERSATION_ID` |
| Send message | `facebook messenger send CONVERSATION_ID --text "Hello"` |
| Check auth status | `facebook auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `facebook` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **groups** — Read posts from Facebook Groups (list, get)
- **marketplace** — Search and browse Facebook Marketplace (list, get with price/location filters)
- **messenger** — Messenger conversations (list, get, send, requests)
- **auth** — Manage authentication via headed browser (login, logout, status, test)
- **auth** -- Authentication commands and nested `auth profiles` management
- **cache** — Manage response cache (clear)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<principle name="Group Comment Verification">
`facebook groups posts comment` and `facebook groups posts reply` perform multi-stage verification after submitting (composer-cleared → comment-count delta → markdown-stripped text-on-page) and return:

- `verification`: `"confirmed"` (any stage fired) or `"render-timeout-likely-success"` (stage 1 fired, stages 2-3 inconclusive — treat as success).
- `verificationDetails.signal`: which stage confirmed (`composer-cleared`, `count-delta`, `text-appeared`, or `composer-cleared-but-no-other-evidence`).
- `verificationDetails.commentCountBefore` / `commentCountAfter`: `[role="article"]` count delta inside the post.

A non-zero exit ONLY happens when all three verification signals fail (true submit failure). Never retry on `render-timeout-likely-success` — duplicate comments are worse than missed verification.

Facebook strips Markdown (`**bold**`, `[label](url)`) when rendering comments — never use raw substring matching against submitted text to verify a comment landed.
</principle>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>

## Known Issues

### 1. Group comment posting fails: "Expected one target article for post <id>, found 0"

**Symptom:** `facebook groups posts comment <group>/posts/<id> -m "..."` aborts during composer activation with `Error: Failed to activate comment composer: Expected one target article for post <id>, found 0`. Nothing is typed or submitted. The READ path (`facebook groups posts get ...`) on the same post still works, so auth/session is healthy — only the comment-WRITE locator is broken.

**Cause:** A Facebook DOM structure change. The comment-composer activator in `facebook_cli/client.py::comment_on_post` required exactly one `[role="article"]` inside `[role="main"]` that BOTH contained a post-permalink anchor AND a "Comment" control. Facebook moved the post-permalink anchor and the comment controls OUT of the `[role="article"]` wrapper. Verified against the live DOM on the permalink page: the post-permalink anchor's `closestArticle === false` (it is no longer inside any article), the `[role="main"]` article wrappers contain zero anchors and zero comment controls, and the post's comment composer (a single visible `[role="textbox"][contenteditable="true"][data-lexical-editor="true"]`) is rendered in a React portal OUTSIDE `[role="main"]` (`inMain === false`). So the "one article containing both" requirement matched 0 articles and aborted. Note: the hardcoded permalink href patterns (`/groups/<gid>/posts/<pid>/`) were NOT the problem — those anchors still match; the article-scoping was the broken assumption.

**Fix:** Rewrote the `js_activate` locator in `comment_on_post` to stop requiring a `[role="article"]` match. Because the CLI navigates to the canonical single-post permalink URL (which isolates exactly one target post), the activator now: (1) detects an already-visible comment composer DOCUMENT-WIDE (it lives in a portal outside `[role="main"]`) and uses it when exactly one exists; (2) only if none is present, clicks the post's Comment activator scoped to `[role="main"]`, matched by exact text "comment" or aria-label `leave a comment`/`write a comment`/`comment as`, requiring uniqueness. Post identity stays pinned by the canonical URL plus the existing `_wait_for_comment_on_exact_post` verifier. A secondary trap: the already-visible-composer check must be DOCUMENT-WIDE, not scoped to `[role="main"]` — the composer's `inMain` is false, so a main-scoped check finds 0 and then wrongly clicks an activator that disrupts the open composer, causing a later "Could not find filled comment box" submit failure.

**Verification:** `facebook groups posts comment 2318028917/posts/<id> -m "..."` returned `success: true, verification: "confirmed", signal: "exact-post-comment-found"` with a new `commentId`. Independent read path confirmed `comment_count` incremented 5 → 6 and the comment text was present. (The facebook CLI has no delete-comment command; remove a test comment by driving the comment's `aria-label="Edit or delete this"` menu → Delete menuitem → confirm "Delete Comment?" dialog via the same authenticated session.)

**Recurrence Prevention:** The locator no longer depends on Facebook nesting the permalink anchor and comment controls inside a `[role="article"]`. It relies on the more stable invariants of a single-post permalink page: one visible Lexical composer document-wide, or one comment activator in `[role="main"]`. If Facebook changes the composer/activator selectors again, capture the live DOM FIRST (instantiate `FacebookClient`, call `_get_page(url)`, then `page.evaluate(...)` to dump article/anchor/composer facts) before editing — diagnose from the live page, never from assumptions. The aria-label for the inline activator is currently "Leave a comment"; the composer's `aria-placeholder` is personalized (for example, "Answer as <profile>"), so never match on placeholder text.
