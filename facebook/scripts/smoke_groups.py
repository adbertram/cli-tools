#!/usr/bin/env python3
"""Smoke-test Facebook Groups flows with one browser session."""

import argparse
import json
import os
import sys
import time

from facebook_cli.client import get_client


def _timed(name, fn):
    start = time.monotonic()
    result = fn()
    elapsed = round(time.monotonic() - start, 2)
    return name, elapsed, result


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description="Smoke-test Facebook Groups with one browser session.")
    parser.add_argument("--group-id", default="2318028917")
    parser.add_argument("--post-url")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--skip-joined-groups", action="store_true")
    parser.add_argument("--create-text", default=os.environ.get("FACEBOOK_GROUPS_CREATE_TEXT"))
    parser.add_argument("--comment-text", default=os.environ.get("FACEBOOK_GROUPS_COMMENT_TEXT"))
    parser.add_argument("--reply-text", default=os.environ.get("FACEBOOK_GROUPS_REPLY_TEXT"))
    parser.add_argument("--comment-index", type=int, default=int(os.environ.get("FACEBOOK_GROUPS_COMMENT_INDEX", "1")))
    args = parser.parse_args()

    timings = {}
    write_results = {}
    client = get_client()
    try:
        name, elapsed, auth = _timed("auth", lambda: client._browser.is_authenticated())
        timings[name] = elapsed
        _require(auth.authenticated, "Facebook browser session is not authenticated")
        _require(auth.available, "Facebook browser session is authenticated but not available")

        joined_groups = []
        if not args.skip_joined_groups:
            name, elapsed, joined_groups = _timed(
                "joined_groups",
                lambda: client.list_joined_groups(limit=args.limit),
            )
            timings[name] = elapsed
            _require(joined_groups, "No joined groups were extracted")

        name, elapsed, group = _timed(
            "group_get",
            lambda: client.get_group(args.group_id),
        )
        timings[name] = elapsed
        _require(group.group_id == args.group_id, f"Group get returned {group.group_id}")
        _require(group.name, "Group get returned no name")

        name, elapsed, posts = _timed(
            "posts_list",
            lambda: client.list_group_posts(args.group_id, limit=args.limit),
        )
        timings[name] = elapsed
        _require(posts, f"No posts were extracted from group {args.group_id}")

        post_ref = args.post_url
        if not post_ref:
            post_ref = next((post.url for post in posts if post.url), None)
        _require(post_ref, "No stable post URL was extracted for post get smoke test")

        name, elapsed, post = _timed(
            "post_get",
            lambda: client.get_group_post(post_ref),
        )
        timings[name] = elapsed
        _require(post.post_id, "Post get returned no post_id")
        _require(post.author or post.text, "Post get returned neither author nor text")

        if args.create_text:
            name, elapsed, create_result = _timed(
                "post_create",
                lambda: client.create_group_post(args.group_id, args.create_text),
            )
            timings[name] = elapsed
            _require(create_result.get("verified") is True, "Create post was not verified")
            write_results["create"] = create_result

        if args.comment_text:
            name, elapsed, comment_result = _timed(
                "post_comment",
                lambda: client.comment_on_post(post_ref, args.comment_text),
            )
            timings[name] = elapsed
            _require(comment_result.get("verified") is True, "Comment was not verified")
            write_results["comment"] = comment_result

        if args.reply_text:
            name, elapsed, reply_result = _timed(
                "comment_reply",
                lambda: client.reply_to_comment(post_ref, args.comment_index, args.reply_text),
            )
            timings[name] = elapsed
            _require(reply_result.get("verified") is True, "Reply was not verified")
            write_results["reply"] = reply_result
    finally:
        client.close()

    result = {
        "success": True,
        "group_id": args.group_id,
        "post_ref": post_ref,
        "timings_seconds": timings,
        "joined_groups_count": len(joined_groups),
        "posts_count": len(posts),
        "group": group.model_dump(),
        "post": post.model_dump(),
        "writes": write_results,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(1)
