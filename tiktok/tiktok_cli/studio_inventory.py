"""Bounded caller-owned continuations for exact own-account Studio IDs."""
import hashlib
import json

from .studio import MAX_STUDIO_PAGES, StudioContractError, positive_decimal_id

MAX_MANIFEST_IDS = 1000
MAX_INPUT_BYTES = 64 * 1024
CHECKPOINT_KEYS = {"version", "actor", "request_digest", "semantics_digest", "cursor", "found_ids"}


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    except (ValueError, TypeError, RecursionError):
        raise StudioContractError("Studio inventory input is malformed.") from None


def validate_request(video_ids, continuation, max_pages, expected_account_id):
    if not positive_decimal_id(expected_account_id):
        raise StudioContractError("Studio inventory requires an exact positive account ID string.")
    if type(video_ids) is not list or not 1 <= len(video_ids) <= MAX_MANIFEST_IDS:
        raise StudioContractError("Studio inventory requires between 1 and 1000 exact video IDs.")
    if any(not positive_decimal_id(value) for value in video_ids) or len(set(video_ids)) != len(video_ids):
        raise StudioContractError("Studio inventory video IDs must be unique positive numeric strings.")
    if len(canonical(video_ids)) > MAX_INPUT_BYTES:
        raise StudioContractError("Studio inventory manifest exceeds 64 KiB.")
    if type(max_pages) is not int or not 1 <= max_pages <= MAX_STUDIO_PAGES:
        raise StudioContractError("Studio inventory page budget must be between 1 and 20.")
    digest = hashlib.sha256(canonical(sorted(video_ids))).hexdigest()
    # Reserve the entire allowed actor binding and every potentially found ID.
    # A large accepted manifest must never fail only after an expensive scan.
    largest = {"version":1, "actor":{"padding":"x"*4096}, "request_digest":digest,
               "semantics_digest":"0"*64, "cursor":2**53-1, "found_ids":sorted(video_ids)}
    if len(canonical(largest)) > MAX_INPUT_BYTES:
        raise StudioContractError("Studio inventory manifest leaves insufficient 64 KiB continuation capacity.")
    if continuation is not None:
        if len(canonical(continuation)) > MAX_INPUT_BYTES or type(continuation) is not dict or set(continuation) != CHECKPOINT_KEYS:
            raise StudioContractError("Studio inventory continuation is malformed or exceeds 64 KiB.")
        cp = continuation
        if type(cp["version"]) is not int or cp["version"] != 1:
            raise StudioContractError("Studio inventory continuation version is unsupported.")
        actor = cp["actor"]
        if type(actor) is not dict or set(actor) != {"account_id", "username", "profile"} or any(type(value) is not str or not value for value in actor.values()):
            raise StudioContractError("Studio inventory continuation actor is malformed.")
        if actor["account_id"] != expected_account_id or cp["request_digest"] != digest:
            raise StudioContractError("Studio inventory continuation actor or request set changed.")
        if type(cp["semantics_digest"]) is not str or len(cp["semantics_digest"]) != 64 or any(c not in "0123456789abcdef" for c in cp["semantics_digest"]):
            raise StudioContractError("Studio inventory continuation semantics are malformed.")
        if type(cp["cursor"]) is not int or not 0 < cp["cursor"] <= 2**53 - 1:
            raise StudioContractError("Studio inventory continuation cursor is malformed.")
        found = cp["found_ids"]
        if type(found) is not list or len(found) > len(video_ids) or any(not positive_decimal_id(value) for value in found) or len(set(found)) != len(found) or not set(found) <= set(video_ids):
            raise StudioContractError("Studio inventory continuation found IDs are malformed.")
        if max_pages < 2:
            raise StudioContractError("Studio inventory resume needs at least two pages, including fresh head read.")
        # Copy caller data so subsequent mutation cannot change this invocation.
        continuation = json.loads(canonical(cp))
    return {"ids": frozenset(video_ids), "digest": digest, "continuation": continuation, "max_pages": max_pages}


def batch_read(reader, request):
    actor = {key: reader.identity[key] for key in ("account_id", "username", "profile")}
    cp = request["continuation"]
    if cp is not None and cp["actor"] != actor:
        raise StudioContractError("Studio inventory continuation actor or profile changed.")
    semantics = reader.semantics_digest()
    if cp is not None and cp["semantics_digest"] != semantics:
        raise StudioContractError("Studio inventory continuation native request semantics changed.")
    found = set(cp["found_ids"] if cp else [])
    records = {}
    cursor, pages, provider_end = 0, 0, False
    next_cursor = 0
    while pages < request["max_pages"]:
        items, more, next_cursor = reader.read_page(cursor)
        pages += 1
        for record in items:
            if record["id"] in request["ids"]:
                records[record["id"]] = record
                found.add(record["id"])
        if not more:
            provider_end = True
            break
        if found == request["ids"]:
            break
        # Refresh the head on every invocation; resume only after that fresh read.
        cursor = cp["cursor"] if pages == 1 and cp is not None else next_cursor
    unresolved = sorted(request["ids"] - found)
    continuation = None
    if unresolved and not provider_end:
        continuation = {"version": 1, "actor": actor, "request_digest": request["digest"],
                        "semantics_digest": semantics, "cursor": next_cursor, "found_ids": sorted(found)}
        if len(canonical(continuation)) > MAX_INPUT_BYTES:
            raise StudioContractError("Studio inventory continuation exceeds 64 KiB.")
    return {"actor": actor, "records": list(records.values()), "unresolved_ids": unresolved,
            "unresolved_state": "unknown", "requested_complete": not unresolved,
            "provider_end": provider_end, "pages_read": pages, "continuation": continuation,
            "semantics_digest": semantics, "provenance": "own_account_studio"}
