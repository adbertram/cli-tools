"""HTML parsers for Garrul admin pages that have no JSON equivalent.

Every parser here was written against real DOM captured from a running Garrul
v2.26.1 instance (see tests/fixtures). Each one raises ParseError the moment
expected markup is missing, so a Garrul upgrade that changes a page fails
loudly instead of returning an empty or partial result.
"""

import json
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag
from cli_tools_shared.exceptions import ClientError

COMMENT_STATUSES = ("pending", "approved", "spam", "deleted")
SETTING_GROUPS = (("flags", "flags"), ("nums", "numbers"), ("strs", "strings"), ("texts", "texts"))
NO_VALUE = "—"  # how Garrul renders a missing email or timestamp
ALL_EVENTS_LABEL = "all events"
WEBHOOK_EVENTS = (
    "comment.posted",
    "comment.edited",
    "comment.deleted",
    "comment.approved",
    "comment.spam",
    "comment.reported",
)
_TIMESTAMP = re.compile(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})")


class ParseError(ClientError):
    """An admin page did not contain the markup this CLI was built against."""


def _main(html: str, page: str) -> Tag:
    main = BeautifulSoup(html, "html.parser").find("main")
    if main is None:
        raise ParseError(f"{page}: no <main> element. The admin layout changed or this is not an admin page.")
    return main


def _one(node: Tag, selector: str, what: str) -> Tag:
    found = node.select_one(selector)
    if found is None:
        raise ParseError(f"Expected {what} ({selector!r}) was not found.")
    return found


def _text(node: Tag) -> str:
    return " ".join(node.get_text(" ", strip=True).split())


def _own_text(node: Tag) -> str:
    """Text that belongs to the node itself, excluding badge child elements."""
    return " ".join("".join(node.find_all(string=True, recursive=False)).split())


def _iso_minute(text: str, what: str) -> str:
    match = _TIMESTAMP.search(text)
    if match is None:
        raise ParseError(f"{what}: no 'YYYY-MM-DD HH:MM' timestamp in {text!r}.")
    return f"{match.group(1)}T{match.group(2)}Z"


def _leading_count(title: str, what: str) -> int:
    match = re.match(r"(\d+) ", title)
    if match is None:
        raise ParseError(f"{what}: badge title {title!r} does not start with a count.")
    return int(match.group(1))


def _badge_count(scope: Tag, selector: str, what: str) -> int:
    badge = scope.select_one(selector)
    if badge is None:
        return 0
    return _leading_count(badge.get("title", ""), what)


def _handler_id(node: Tag, function: str, what: str) -> str:
    """Pull the record id out of an Alpine click handler such as act("ID",...)."""
    handler = node.get("@click", "")
    match = re.search(rf'{function}\("([^"]+)"', handler)
    if match is None:
        raise ParseError(f"{what}: no {function}(\"<id>\") call in click handler {handler!r}.")
    return match.group(1)


def _body_rows(table: Tag, columns: int, empty_text: str) -> list[Tag]:
    body = _one(table, "tbody", "table body")
    rows = body.find_all("tr", recursive=False)
    if len(rows) == 1:
        cells = rows[0].find_all("td", recursive=False)
        if len(cells) == 1 and cells[0].get("colspan") == str(columns):
            if _text(cells[0]) != empty_text:
                raise ParseError(f"Unrecognized empty-table message {_text(cells[0])!r}; expected {empty_text!r}.")
            return []
    return rows


def _cells(row: Tag, count: int, what: str) -> list[Tag]:
    cells = row.find_all("td", recursive=False)
    if len(cells) != count:
        raise ParseError(f"{what}: expected {count} cells, found {len(cells)}.")
    return cells


def _next_before(main: Tag) -> Optional[str]:
    pager = _one(main, "div.pager", "pager")
    link = pager.find("a")
    if link is None:
        if _text(pager) != "end":
            raise ParseError(f"Unrecognized pager content {_text(pager)!r}.")
        return None
    before = parse_qs(urlparse(link["href"]).query).get("before")
    if not before:
        raise ParseError(f"Pager link {link['href']!r} has no 'before' cursor.")
    return before[0]


def _xdata_json(main: Tag, key: str, what: str):
    """Decode the JSON value that follows `key:` inside an Alpine x-data blob."""
    marker = f"{key}: "
    for node in main.select("[x-data]"):
        blob = node["x-data"]
        index = blob.find(marker)
        if index >= 0:
            try:
                value, _ = json.JSONDecoder().raw_decode(blob, index + len(marker))
            except json.JSONDecodeError as exc:
                raise ParseError(f"{what}: x-data state {key!r} is not JSON ({exc}).") from exc
            return value
    raise ParseError(f"{what}: no x-data state named {key!r}.")


def _status_pill(scope: Tag, what: str) -> str:
    for pill in scope.select("span.pill"):
        for name in pill.get("class", []):
            if name in COMMENT_STATUSES and _text(pill) == name:
                return name
    raise ParseError(f"{what}: no comment status pill.")


def _author(scope: Tag, what: str) -> dict:
    name_node = _one(scope, ".author-name", f"{what} author name")
    link = scope.select_one('a[href^="/admin/users/"]')
    if link is None:
        raise ParseError(f"{what}: no author link.")
    name_holder = link if link.find_parent(class_="author-name") is not None else name_node
    return {
        "author_name": _own_text(name_holder),
        "author_user_id": link["href"].rsplit("/", 1)[1],
        "author_is_admin": name_node.select_one("span.pill.admin") is not None,
        "author_is_banned": name_node.select_one("span.pill.banned") is not None,
    }


def _body(scope: Tag, what: str) -> dict:
    body = _one(scope, "div.md", f"{what} body")
    return {"body_html": body.decode_contents().strip(), "body_text": body.get_text("\n", strip=True)}


# ---------------------------------------------------------------- comments


def _queue_row(row: Tag) -> dict:
    _, status_cell, author_cell, score_cell, meta_cell, body_cell, _ = _cells(row, 7, "queue row")
    comment_id = _text(_one(meta_cell, "span.cid", "queue row comment id"))
    what = f"queue row {comment_id}"
    score = re.fullmatch(r"(\d+)↑ (\d+)↓", _text(_one(score_cell, "div.muted", f"{what} score")))
    if score is None:
        raise ParseError(f"{what}: unrecognized score cell.")
    codes = [_text(code) for code in meta_cell.select("div > code")]
    if len(codes) != 2:
        raise ParseError(f"{what}: expected host and post slug codes, found {codes!r}.")
    title = meta_cell.select_one("div.meta-title")
    page_link = meta_cell.select_one('a[target="_blank"]')
    strip = body_cell.select_one("div.audit-strip")
    return {
        "id": comment_id,
        "status": _status_pill(status_cell, what),
        "post_slug": codes[1],
        "post_title": _text(title) if title is not None else None,
        "post_url": page_link["href"] if page_link is not None else None,
        "host": codes[0],
        **_author(author_cell, what),
        "author_provider": _text(_one(author_cell, ".author-sub", f"{what} provider")),
        "created_at": _iso_minute(_one(meta_cell, "div.muted[title]", f"{what} timestamp")["title"], what),
        "score_up": int(score.group(1)),
        "score_down": int(score.group(2)),
        "open_reports": _badge_count(status_cell, 'span.pill[title*="open report"]', what),
        "comment_notes": _badge_count(status_cell, "span.note-badge", what),
        "user_notes": _badge_count(author_cell, "span.note-badge", what),
        "last_action": _text(strip) if strip is not None else None,
        **_body(body_cell, what),
    }


def parse_queue(html: str) -> dict:
    """Parse GET /admin/queue into rows plus the server's next-page cursor."""
    main = _main(html, "queue")
    rows = _body_rows(_one(main, "table", "queue table"), 7, "No comments match.")
    return {"rows": [_queue_row(row) for row in rows], "next_before": _next_before(main)}


def _card(card: Tag) -> dict:
    link = _one(card, 'a[href^="/admin/comments/"]', "comment card id link")
    comment_id = link["href"].rsplit("/", 1)[1]
    what = f"comment card {comment_id}"
    meta = link.find_parent("div")
    sub = _one(card, ".author-sub", f"{what} provider")
    return {
        "id": comment_id,
        "status": _status_pill(_one(card, ".comment-card-head", f"{what} head"), what),
        "post_slug": _text(_one(meta, "code", f"{what} post slug")),
        **_author(card, what),
        "author_provider": _own_text(sub).rstrip("· ").strip(),
        "created_at": _iso_minute(_text(meta), what),
        **_body(card, what),
    }


def _cards(main: Tag) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for card in main.select("div.comment-card"):
        label = _text(_one(card, "div.muted", "comment card label"))
        grouped.setdefault(label, []).append(_card(card))
    return grouped


def _section(main: Tag, heading_prefix: str) -> Optional[Tag]:
    for heading in main.find_all("h3"):
        if _text(heading).startswith(heading_prefix):
            return heading.find_parent("div", class_="card")
    return None


def _notes(main: Tag) -> list[dict]:
    card = _section(main, "Moderator notes")
    if card is None:
        raise ParseError("No 'Moderator notes' card on the page.")
    notes = []
    for item in card.select("ul.note-list > li.note"):
        meta = _one(item, ".note-meta", "note meta")
        delete = meta.select_one("button.note-del")
        notes.append(
            {
                "id": _handler_id(delete, "remove", "note") if delete is not None else None,
                "author_name": _text(_one(meta, "strong", "note author")),
                "created_at": _iso_minute(_own_text(meta), "note"),
                "body": _one(item, ".note-body", "note body").get_text("\n", strip=True),
            }
        )
    return notes


def _table_rows(card: Optional[Tag], columns: list[str], what: str) -> list[list[Tag]]:
    if card is None:
        return []
    headers = [_text(th) for th in card.select("thead th")]
    if headers != columns:
        raise ParseError(f"{what}: expected columns {columns!r}, found {headers!r}.")
    return [_cells(row, len(columns), what) for row in _one(card, "tbody", what).find_all("tr", recursive=False)]


def _audit_history(main: Tag, heading: str) -> list[dict]:
    rows = _table_rows(_section(main, heading), ["When", "Action", "Admin", "Reason"], heading)
    return [
        {
            "created_at": _iso_minute(_text(when), heading),
            "action": _text(action),
            "admin_name": _text(admin),
            "reason": _text(reason) or None,
        }
        for when, action, admin, reason in rows
    ]


def parse_comment_detail(html: str) -> dict:
    """Parse GET /admin/comments/:id into one full comment record."""
    main = _main(html, "comment detail")
    cards = _cards(main)
    selected = cards.get("Selected", [])
    if len(selected) != 1:
        raise ParseError(f"Expected exactly one 'Selected' comment card, found {len(selected)}.")
    parents = cards.get("Parent", [])
    markdown = _section(main, "Raw markdown")
    if markdown is None:
        raise ParseError("No 'Raw markdown' card on the comment page.")
    reports = _table_rows(_section(main, "Reader reports"), ["Status", "When", "Reason"], "reader reports")
    verdicts = _table_rows(_section(main, "Spam verdicts"), ["Verdict", "When", "Raw"], "spam verdicts")
    report_rows = [
        {
            "status": _text(status),
            "created_at": _iso_minute(_text(when), "report"),
            "reason": None if reason.select_one("span.muted") is not None else _text(reason),
        }
        for status, when, reason in reports
    ]
    return {
        **selected[0],
        "parent_id": parents[0]["id"] if parents else None,
        "body_md": _one(markdown, "pre", "raw markdown").get_text(),
        "open_reports": sum(1 for report in report_rows if report["status"] == "open"),
        "reports": report_rows,
        "spam_verdicts": [
            {"verdict": _text(verdict), "created_at": _iso_minute(_text(when), "verdict"), "raw": _text(raw)}
            for verdict, when, raw in verdicts
        ],
        "notes": _notes(main),
        "parent": parents[0] if parents else None,
        "replies": cards.get("Reply", []),
        "ip_siblings": cards.get("Same IP-hash", []),
        "author_recent": cards.get("Recent", []),
        "audit": _audit_history(main, "Audit history for this comment"),
    }


# ------------------------------------------------------------------- users


def parse_users(html: str) -> dict:
    """Parse GET /admin/users."""
    main = _main(html, "users")
    records = []
    for row in _body_rows(_one(main, "table", "users table"), 4, "No users match."):
        who, provider, joined, _ = _cells(row, 4, "user row")
        link = _one(who, 'a[href^="/admin/users/"]', "user link")
        user_id = link["href"].rsplit("/", 1)[1]
        email = _text(_one(who, "div.muted", f"user {user_id} email"))
        records.append(
            {
                "id": user_id,
                "name": _text(link),
                "email": None if email == NO_VALUE else email,
                "provider": _text(provider),
                "is_banned": _xdata_bool(row, "banned", f"user {user_id}"),
                "joined_on": _text(joined),
            }
        )
    return {"rows": records, "next_before": _next_before(main)}


def _xdata_bool(node: Tag, key: str, what: str) -> bool:
    match = re.search(rf"\b{key}: (true|false)\b", node.get("x-data", ""))
    if match is None:
        raise ParseError(f"{what}: no boolean x-data state named {key!r}.")
    return match.group(1) == "true"


def _user_comments(main: Tag) -> list[dict]:
    card = _section(main, "Comments by ")
    if card is None:
        raise ParseError("No 'Comments by' card on the user page.")
    headers = [_text(th) for th in card.select("thead th")]
    if headers != ["Status", "When", "Post", "Body", ""]:
        raise ParseError(f"User comments table: unexpected columns {headers!r}.")
    records = []
    for row in _body_rows(_one(card, "table", "user comments table"), 5, "No comments yet."):
        status, when, post, body, link = _cells(row, 5, "user comment row")
        records.append(
            {
                "id": _one(link, 'a[href^="/admin/comments/"]', "user comment link")["href"].rsplit("/", 1)[1],
                "status": _status_pill(status, "user comment row"),
                "post_slug": _text(_one(post, "code", "user comment post slug")),
                "created_at": _iso_minute(_text(when), "user comment row"),
                **_body(body, "user comment row"),
            }
        )
    return records


def parse_user_detail(html: str) -> dict:
    """Parse GET /admin/users/:id."""
    main = _main(html, "user detail")
    meta = _one(main, "div.user-meta", "user header")
    lines = meta.find_all("div", class_="muted", recursive=False)
    if len(lines) != 2:
        raise ParseError(f"User header: expected 2 detail lines, found {len(lines)}.")
    parts = [part.strip() for part in _text(lines[0]).split(" · ")]
    if len(parts) != 3 or not parts[2].startswith("joined "):
        raise ParseError(f"User header: unrecognized identity line {_text(lines[0])!r}.")
    heading = _one(meta, "h2", "user name")
    pills = {_text(pill) for pill in heading.select("span.pill")}
    unknown = pills - {"admin", "mod", "banned", "erased"}
    if unknown:
        raise ParseError(f"User header: unrecognized badge {sorted(unknown)!r}.")
    stats = {}
    for stat in main.select("div.user-stats > div"):
        label = _text(_one(stat, "span.muted", "user stat label")).rstrip(":")
        stats[label.lower().replace(" ", "_")] = _own_text(stat)
    return {
        "id": _text(_one(lines[1], "code", "user id")),
        "name": _own_text(heading),
        "email": None if parts[0] == NO_VALUE else parts[0],
        "provider": parts[1],
        "joined_at": _iso_minute(parts[2], "user joined"),
        # Garrul shows a pill for admin and mod and nothing for a plain user.
        "role": "admin" if "admin" in pills else "mod" if "mod" in pills else "user",
        "is_banned": "banned" in pills,
        "is_erased": "erased" in pills,
        "stats": stats,
        "notes": _notes(main),
        "comments": _user_comments(main),
        "comments_next_before": _next_before(main),
        "audit": _audit_history(main, "Audit history affecting this user"),
    }


# ------------------------------------------------------------------- audit


def parse_audit(html: str) -> dict:
    """Parse GET /admin/audit.

    Garrul renders no audit row id, and shows only the first 8 characters of a
    target id unless the target is a comment or a user (those link to the full
    id). `target_id` is the full id when the page provides it and
    `target_id_prefix` is always the 8-character form.
    """
    main = _main(html, "audit")
    records = []
    for row in _body_rows(_one(main, "table", "audit table"), 7, "No audit rows."):
        when, action, admin, kind, target, reason, meta = _cells(row, 7, "audit row")
        link = target.find("a")
        code = target.find("code")
        meta_text = _text(meta)
        records.append(
            {
                "created_at": _iso_minute(_text(when), "audit row"),
                "action": _text(action),
                "admin_name": _text(admin),
                "target_kind": _text(kind),
                "target_id": link["href"].rsplit("/", 1)[1] if link is not None else None,
                "target_id_prefix": _text(code).rsplit(":", 1)[-1] if code is not None else None,
                "reason": _text(reason) or None,
                "meta": json.loads(meta_text) if meta_text else None,
            }
        )
    applied = {
        name: _one(main, f'select[name="{name}"] option[selected]', f"audit {name} filter")["value"]
        for name in ("action", "target_kind")
    }
    return {"rows": records, "next_before": _next_before(main), "applied": applied}


# ----------------------------------------------------------- subscriptions


def parse_subscriptions(html: str) -> dict:
    """Parse GET /admin/subscriptions.

    The subscription id only exists inside the row's action buttons, and an
    unsubscribed row has no buttons, so `id` is null for unsubscribed rows.
    """
    main = _main(html, "subscriptions")
    records = []
    for row in _body_rows(_one(main, "table", "subscriptions table"), 6, "No subscriptions match."):
        status, created, email, slug, notified, actions = _cells(row, 6, "subscription row")
        state = _text(status)
        button = actions.find("button")
        if button is None and state != "unsubscribed":
            raise ParseError(f"Subscription row in state {state!r} has no action button to read its id from.")
        notified_text = _text(notified)
        records.append(
            {
                "id": _handler_id(button, "act", "subscription") if button is not None else None,
                "status": state,
                "email": _text(email),
                "post_slug": _text(slug),
                "created_at": _iso_minute(_text(created), "subscription"),
                "last_notified_at": None if notified_text == NO_VALUE else _iso_minute(notified_text, "subscription"),
            }
        )
    return {"rows": records, "next_before": _next_before(main)}


# ---------------------------------------------------------------- webhooks


def parse_webhooks(html: str) -> list[dict]:
    """Parse GET /admin/webhooks."""
    main = _main(html, "webhooks")
    records = []
    for row in _body_rows(_one(main, "table", "webhooks table"), 5, "No webhook endpoints configured yet."):
        target, signing, _, created, actions = _cells(row, 5, "webhook row")
        edit = _one(actions, 'a[href^="/admin/webhooks/"]', "webhook edit link")
        detail = _text(_one(target, "div.muted", "webhook events and adapter"))
        events, separator, adapter = detail.rpartition(" · ")
        if not separator:
            raise ParseError(f"Webhook row: unrecognized events/adapter line {detail!r}.")
        records.append(
            {
                "id": edit["href"].rsplit("/", 1)[1],
                "url": _text(_one(target, "code", "webhook url")),
                "adapter": adapter,
                "events": list(WEBHOOK_EVENTS) if events == ALL_EVENTS_LABEL else events.split(", "),
                "signing": _text(signing),
                "enabled": _xdata_bool(row, "enabled", "webhook row"),
                "created_at": _iso_minute(_text(created), "webhook"),
            }
        )
    return records


def parse_webhook_detail(html: str, webhook_id: str) -> dict:
    """Parse GET /admin/webhooks/:id (the edit form). The secret is write-only."""
    main = _main(html, "webhook detail")
    form = _one(main, "form", "webhook form")
    adapter = _one(form, 'select[name="adapter"] option[selected]', "selected webhook adapter")
    return {
        "id": webhook_id,
        "url": _one(form, 'input[name="url"]', "webhook url")["value"],
        "adapter": adapter["value"],
        "events": [
            box["name"].removeprefix("event_")
            for box in form.select('input[type="checkbox"][name^="event_"]')
            if box.has_attr("checked")
        ],
        "enabled": _one(form, 'input[name="enabled"]', "webhook enabled box").has_attr("checked"),
    }


# ------------------------------------------------------- settings and ops


def parse_settings(html: str) -> list[dict]:
    """Parse GET /admin/settings into one row per runtime setting."""
    main = _main(html, "settings")
    rows = []
    for key, group in SETTING_GROUPS:
        values = _xdata_json(main, key, "settings")
        if not isinstance(values, dict):
            raise ParseError(f"Settings state {key!r} is not an object.")
        rows.extend({"key": name, "group": group, "value": value} for name, value in values.items())
    return rows


def parse_about(html: str) -> dict:
    """Parse GET /admin/about for the running version and cached releases."""
    main = _main(html, "about")
    version = None
    for paragraph in main.find_all("p"):
        if _text(paragraph).startswith("Running version:"):
            version = _text(_one(paragraph, "code", "running version"))
    if version is None:
        raise ParseError("About page has no 'Running version:' line.")
    releases = []
    for card in main.select("article.release-card"):
        link = _one(card, "h3.release-head a", "release link")
        releases.append(
            {
                "tag": _text(link),
                "url": link["href"],
                "name": _text(_one(card, "span.release-name", "release name")),
                "published_on": _text(_one(card, "h3.release-head span.muted", "release date")).lstrip("· ").strip(),
            }
        )
    return {"version": version, "recent_releases": releases}


def parse_dashboard(html: str) -> dict:
    """Parse GET /admin (the overview tiles and the per-domain table)."""
    main = _main(html, "dashboard")
    tiles = {}
    for tile in main.select("div.stat"):
        label = _text(_one(tile, "div.l", "stat label"))
        tiles[label.lower().replace(" ", "_").replace("(", "").replace(")", "")] = _text(_one(tile, "div.v", "stat value"))
    if not tiles:
        raise ParseError("Dashboard has no stat tiles.")
    hosts = []
    card = _section(main, "Comments by domain")
    for cells in _table_rows(card, ["Host", "Total", "Pending", "Spam", "Spam %"], "comments by domain"):
        host, total, pending, spam, rate = (_text(cell) for cell in cells)
        hosts.append({"host": host, "total": int(total), "pending": int(pending), "spam": int(spam), "spam_rate": rate})
    return {"overview": tiles, "by_host": hosts}


def parse_telegram(html: str) -> dict:
    """Parse GET /admin/telegram for bot configuration state."""
    main = _main(html, "telegram")
    secrets = {}
    for row in _one(main, "table tbody", "telegram configuration table").find_all("tr", recursive=False):
        name, state, _ = _cells(row, 3, "telegram configuration row")
        secrets[_text(name)] = _text(state)
    if not secrets:
        raise ParseError("Telegram page lists no bot configuration rows.")
    linked = _section(main, "Your linked account")
    if linked is None:
        if _section(main, "Link your Telegram account") is None:
            raise ParseError("Telegram page has neither a linked-account card nor a link card.")
        return {"bot_configuration": secrets, "linked": False, "linked_at": None, "digest": None}
    return {
        "bot_configuration": secrets,
        "linked": True,
        "linked_at": _iso_minute(_text(_one(linked, "p.muted", "telegram linked line")), "telegram link"),
        "digest": _xdata_bool(linked, "digest", "telegram digest"),
    }


def parse_operator(html: str) -> dict:
    """Parse GET /admin/operator.

    The rerender card has a fixed shape. The two retention cards are prose whose
    wording changes with the configured window, so they are returned as the
    page's own sentences rather than guessed into fields.
    """
    main = _main(html, "operator")
    rerender = _section(main, "Rerender comments")
    if rerender is None:
        raise ParseError("Operator page has no 'Rerender comments' card.")
    line = _one(rerender, "p.muted", "rerender summary")
    counts = [_text(node) for node in line.find_all("strong")]
    if len(counts) != 2 or not _text(line).startswith("Current renderer version:"):
        raise ParseError(f"Unrecognized rerender summary {_text(line)!r}.")
    result = {
        "rerender": {
            "current_version": int(_text(_one(line, "code", "renderer version"))),
            "up_to_date": int(counts[0]),
            "stale": int(counts[1]),
        }
    }
    for key, heading in (("ip_retention", "IP-hash retention"), ("audit_retention", "Audit-log retention")):
        card = _section(main, heading)
        if card is None:
            raise ParseError(f"Operator page has no {heading!r} card.")
        result[key] = [_text(paragraph) for paragraph in card.find_all("p", class_="muted")]
    result["seed_demo_available"] = _section(main, "Seed demo post") is not None
    return result
