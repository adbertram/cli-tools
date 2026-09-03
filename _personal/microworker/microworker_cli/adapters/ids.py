"""The one check that turns a site's raw id field into a `task_id`.

Every adapter needs the same thing -- take whatever the site CLI put in its id
field and produce the string half of the `(site, task_id)` primary key -- so the
check lives here once rather than being retyped per adapter and drifting.

It exists because `str(value)` accepts everything. A guard of the shape
`if value is None or str(value) == ""` tests the STRINGIFIED value, so every
non-empty repr walks straight through it and becomes a primary key that does not
exist on the site: JSON `true` is stored as the id `"True"`, and a JSON object
is stored as `"{'oops': 1}"` -- a Python repr whose text depends on dict
insertion order, so the same record can key two different rows. A whitespace-only
id satisfies the task schema's `minLength: 1` while being no identifier at all,
and a 5000-character id becomes a 5000-character primary key.

So the type is checked BEFORE the stringify, not after: only `str` and `int` are
ids. `bool` is excluded explicitly because it is an `int` subclass in Python and
JSON `true` must not silently mean "the task called True". The returned id is
stripped, because surrounding whitespace is never part of a site's identifier
and a padded key would not match the same task on its next sighting.
"""

from __future__ import annotations

from cli_tools_shared.exceptions import ClientError

# Long enough for any real identifier these sites publish (a UUID is 36) and
# short enough that a runaway value is a loud error rather than a stored key.
MAX_LENGTH = 200


def task_id(site: str, value, *, field: str, locator: str) -> str:
    """The record's id as a task_id string, or a `ClientError` naming it.

    `field` is the raw key being read (`campaign_id`, `id`, ...) and `locator`
    is whatever else identifies the offending record in the error message.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ClientError(
            f"{site} record field '{field}' must be a string or an integer, "
            f"got {type(value).__name__} {_short(value)} ({locator})")
    text = str(value).strip()
    if not text:
        raise ClientError(
            f"{site} record field '{field}' is empty ({locator})")
    if len(text) > MAX_LENGTH:
        raise ClientError(
            f"{site} record field '{field}' is {len(text)} characters; a task "
            f"id may be at most {MAX_LENGTH} ({locator})")
    return text


def _short(value) -> str:
    text = repr(value)
    return text if len(text) <= 80 else text[:77] + "..."
